"""
Order Executor - Order execution and trade management for Bullseye.

Handles the execution of entry and exit orders, including position sizing,
trailing stop management, and T+1 compliance checking.

Two execution modes:
- Simulated (default / dry-run): trades are booked locally at the given rate.
- Live (gateway wired + dry_run=False): orders are sent through the
  gateway, confirmed by polling query_order, and booked at the actual
  fill price/quantity.
"""
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from bullseye.configuration.config import Config
from bullseye.order.position_manager import LocalTrade, PositionManager, MarketType
from bullseye.strategy.interface import IStrategy
from bullseye.trader.object import Direction, Offset, OrderData, OrderType, Status
from bullseye.wallets.wallets import Wallets

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = (Status.ALLTRADED, Status.CANCELLED, Status.REJECTED)


class OrderExecutor:
    """
    Order Executor for Bullseye.

    Handles the execution of entry and exit orders in dry-run mode,
    including position sizing, fee calculation, order tracking, and T+1 compliance.

    Freqtrade Compatible:
    - Supports custom_stake_amount callback
    - Supports confirm_trade_entry/confirm_trade_exit callbacks
    - Supports T+1 mechanism for stock trading
    """

    def __init__(
        self,
        config: Config,
        position_manager: PositionManager,
        wallets: Wallets,
        strategy: Optional[IStrategy] = None,
    ):
        """
        Initialize the Order Executor.

        Args:
            config: Configuration object
            position_manager: Position manager for trade tracking
            wallets: Wallet manager for balance tracking
            strategy: Strategy instance
        """
        self._config = config
        self._pm = position_manager
        self._wallets = wallets
        self._strategy = strategy
        self._gateway = None

        # Settings
        self._fee_rate = 0.001  # Default 0.1% fee (flat fallback)
        from bullseye.order.fees import FeeModel
        self._fee_model = FeeModel.from_config(config)
        self._stake_currency = config.stake_currency

        # Market type from config
        self._market_type = self._get_market_type_from_config()

    def set_gateway(self, gateway) -> None:
        """Wire the trading gateway used for live order routing."""
        self._gateway = gateway

    @property
    def is_live(self) -> bool:
        """Live execution: gateway present and not in dry-run mode."""
        return self._gateway is not None and not self._config.dry_run

    def _get_market_type_from_config(self) -> MarketType:
        """Get market type from configuration."""
        market_str = self._config.market_type.lower()
        if market_str == "stock":
            return MarketType.STOCK
        elif market_str == "future":
            return MarketType.FUTURE
        else:
            return MarketType.CRYPTO

    def set_strategy(self, strategy: IStrategy) -> None:
        """Set the strategy instance."""
        self._strategy = strategy
        self._pm.set_strategy(strategy)

    # ==================== Position Sizing ====================

    def _resolve_leverage(
        self,
        pair: str,
        current_rate: float,
        current_time: datetime,
        entry_tag: Optional[str],
        side: str,
    ) -> float:
        """Resolve leverage via strategy.leverage() (default 1.0)."""
        if not self._strategy:
            return 1.0
        try:
            lev = self._strategy.leverage(
                pair=pair,
                current_time=current_time,
                current_rate=current_rate,
                proposed_leverage=1.0,
                max_leverage=10,
                entry_tag=entry_tag,
                side=side,
            )
            lev_f = float(lev or 1.0)
            if lev_f <= 0 or lev_f != lev_f:
                return 1.0
            return lev_f
        except AttributeError:
            return 1.0
        except Exception as e:
            logger.warning(f"Error resolving leverage: {e}")
            return 1.0

    def calculate_stake_amount(
        self,
        pair: str,
        side: str = "long",
        entry_tag: Optional[str] = None,
        current_rate: float = 0.0,
        current_time: Optional[datetime] = None,
    ) -> float:
        """
        Calculate the stake amount for a new trade.

        Uses strategy's custom_stake_amount if available, otherwise
        uses config settings. Leverage is resolved first so custom
        sizing sees the real value (previously hardcoded 1.0).

        Args:
            pair: Trading pair
            side: "long" or "short"
            entry_tag: Entry signal tag
            current_rate: Current market price
            current_time: Current time (default: now)

        Returns:
            Stake amount in stake currency
        """
        # Get base stake amount from wallet
        base_stake = self._wallets.get_trade_stake_amount(pair)
        current_time = current_time or datetime.now()

        # Check for custom stake amount from strategy
        if self._strategy:
            try:
                leverage = self._resolve_leverage(
                    pair, current_rate, current_time, entry_tag, side
                )
                custom_stake = self._strategy.custom_stake_amount(
                    pair=pair,
                    current_time=current_time,
                    current_rate=current_rate,
                    proposed_stake=base_stake,
                    min_stake=0.0,
                    max_stake=self._wallets.get_available_stake_amount(),
                    leverage=leverage,
                    entry_tag=entry_tag,
                    side=side,
                )
                if custom_stake is not None:
                    base_stake = custom_stake
            except AttributeError:
                # Strategy doesn't implement custom_stake_amount
                pass
            except Exception as e:
                logger.warning(f"Error getting custom stake amount: {e}")

        return base_stake

    def _fire_order_filled(self, pair: str, trade: LocalTrade, order) -> None:
        """Invoke order_filled(); fills must never break execution."""
        if not self._strategy:
            return
        try:
            self._strategy.order_filled(
                pair=pair,
                trade=trade,
                order=order,
                current_time=getattr(order, "order_filled_date", None)
                or datetime.now(),
            )
        except AttributeError:
            pass
        except Exception as e:
            logger.warning(f"Error in order_filled: {e}")

    def calculate_amount(self, rate: float, stake_amount: float) -> float:
        """
        Calculate the asset amount for a given stake.

        Args:
            rate: Entry price
            stake_amount: Stake currency amount

        Returns:
            Amount of asset to buy
        """
        if rate <= 0:
            return 0.0

        # Simple calculation: amount = stake / price
        amount = stake_amount / rate

        return amount

    # ==================== Entry Execution ====================

    def execute_entry(
        self,
        pair: str,
        rate: float,
        enter_tag: Optional[str] = None,
        stake_amount: Optional[float] = None,
        side: str = "long",
        current_time: Optional[datetime] = None,
    ) -> Optional[LocalTrade]:
        """
        Execute an entry order (simulated in dry-run mode).

        Args:
            pair: Trading pair
            rate: Entry price
            enter_tag: Entry signal tag
            stake_amount: Override stake amount (optional)
            side: "long" or "short"
            current_time: Current time (default: now)

        Returns:
            The created LocalTrade if successful, None otherwise
        """
        from bullseye.order.stock_rules import (
            LOT_SIZE,
            detect_market_type,
            floor_to_lots,
        )

        current_time = current_time or datetime.now()

        # Check if we can open a new trade
        if not self._pm.can_open_trade():
            logger.warning(f"Cannot open trade for {pair}: max_open_trades reached")
            return None

        # Check if pair already has an open trade
        if self._pm.has_open_trade(pair):
            logger.debug(f"Trade already open for {pair}")
            return None

        # Calculate stake amount
        if stake_amount is None:
            stake_amount = self.calculate_stake_amount(
                pair, side=side, entry_tag=enter_tag,
                current_rate=rate, current_time=current_time,
            )

        if stake_amount <= 0:
            logger.warning(f"Invalid stake amount for {pair}: {stake_amount}")
            return None

        # Check available balance
        available = self._wallets.get_available_stake_amount()
        if stake_amount > available:
            logger.warning(
                f"Insufficient balance for {pair}: "
                f"needed={stake_amount}, available={available}"
            )
            stake_amount = available

        if stake_amount <= 0:
            logger.warning(f"No available balance for {pair}")
            return None

        # Custom entry price (e.g. limit offset), then size the amount.
        if self._strategy:
            try:
                custom_rate = self._strategy.custom_entry_price(
                    pair=pair,
                    current_time=current_time,
                    proposed_rate=rate,
                    entry_tag=enter_tag,
                    side=side,
                )
                if custom_rate is not None and float(custom_rate) > 0:
                    rate = float(custom_rate)
            except AttributeError:
                pass
            except Exception as e:
                logger.warning(f"Error in custom_entry_price: {e}")

        # Calculate amount
        amount = self.calculate_amount(rate, stake_amount)

        if amount <= 0:
            logger.warning(f"Invalid amount for {pair}: {amount}")
            return None

        # A-share lot rule (mirrors backtests).
        if detect_market_type(pair) == "stock" and side != "short":
            floored = floor_to_lots(amount)
            if floored < LOT_SIZE:
                logger.warning(
                    f"Entry rejected for {pair}: {amount:.2f} shares < 1 lot"
                )
                return None
            amount = floored
            stake_amount = amount * rate

        # Confirm entry with strategy if available
        if self._strategy:
            try:
                confirmed = self._strategy.confirm_trade_entry(
                    pair=pair,
                    order_type="market",
                    amount=amount,
                    rate=rate,
                    time_in_force="GTC",
                    current_time=datetime.now(),
                    entry_tag=enter_tag,
                    side="long",
                )
                if not confirmed:
                    logger.info(f"Entry signal rejected by strategy for {pair}")
                    return None
            except AttributeError:
                # Strategy doesn't implement confirm_trade_entry
                pass
            except Exception as e:
                logger.warning(f"Error in confirm_trade_entry: {e}")

        # Live mode: route through the gateway and book the actual fill
        if self.is_live:
            return self._execute_entry_live(pair, rate, amount, stake_amount, enter_tag)

        # Execute the trade (simulated)
        trade = self._pm.open_trade(
            pair=pair,
            rate=rate,
            amount=amount,
            stake_amount=stake_amount,
            enter_tag=enter_tag,
            market_type=self._market_type,
            is_short=(side == "short"),
        )

        logger.info(
            f"Executed entry for {pair}: "
            f"rate={rate}, amount={amount}, stake={stake_amount}, tag={enter_tag}"
        )

        from bullseye.order.stock_rules import make_fill_order

        self._fire_order_filled(
            pair, trade,
            make_fill_order(
                pair, "buy" if side != "short" else "sell",
                rate, amount, current_time,
            ),
        )

        return trade

    # ==================== Exit Execution ====================

    def execute_exit(
        self,
        trade: LocalTrade,
        rate: float,
        exit_reason: str,
    ) -> Optional[LocalTrade]:
        """
        Execute an exit order (simulated in dry-run mode).

        **T+1 Check**: For stock trades, this method will check if the position
        is available for sale before executing the exit.

        Args:
            trade: Trade to close
            rate: Exit price
            exit_reason: Reason for exit

        Returns:
            The closed LocalTrade if successful, None otherwise
        """
        # T+1 Check: Verify position is available for sale
        if not trade.available_for_sale:
            logger.warning(
                f"Cannot close trade for {trade.pair}: T+1 restriction. "
                f"Settlement date: {trade.settlement_date}"
            )
            return None

        # Confirm exit with strategy if available
        if self._strategy:
            try:
                confirmed = self._strategy.confirm_trade_exit(
                    pair=trade.pair,
                    trade=trade,
                    order_type="market",
                    amount=trade.amount,
                    rate=rate,
                    time_in_force="GTC",
                    exit_reason=exit_reason,
                    current_time=datetime.now(),
                )
                if not confirmed:
                    logger.info(f"Exit signal rejected by strategy for {trade.pair}")
                    return None
            except AttributeError:
                # Strategy doesn't implement confirm_trade_exit
                pass
            except Exception as e:
                logger.warning(f"Error in confirm_trade_exit: {e}")

        # Live mode: route the close through the gateway first
        if self.is_live:
            return self._execute_exit_live(trade, rate, exit_reason)

        # Close the trade (simulated)
        closed_trade = self._pm.close_trade(
            trade=trade,
            rate=rate,
            exit_reason=exit_reason,
        )

        if closed_trade is not None:
            from bullseye.order.stock_rules import make_fill_order

            self._fire_order_filled(
                trade.pair, closed_trade,
                make_fill_order(
                    trade.pair, "sell" if not trade.is_short else "buy",
                    rate, trade.amount, datetime.now(),
                ),
            )

        return closed_trade

    # ==================== Live Execution (gateway-routed) ====================

    def _execute_entry_live(
        self,
        pair: str,
        rate: float,
        amount: float,
        stake_amount: float,
        enter_tag: Optional[str],
    ) -> Optional[LocalTrade]:
        """
        Send an entry order through the gateway and book the confirmed fill.

        Confirmation model: send_order returns an orderid, then the order
        state is polled via query_order until terminal or timeout. The
        LocalTrade is created from ACTUAL fill price and quantity.
        """
        orderid = self._gateway.send_order({
            "symbol": pair,
            "direction": Direction.LONG,
            "offset": Offset.OPEN,
            "order_type": OrderType.MARKET,
            "price": rate,
            "volume": amount,
        })
        if not orderid:
            logger.error(f"Live entry for {pair} rejected by gateway (no orderid)")
            return None

        order = self._wait_for_fill(orderid, trade=None, is_entry=True)
        if order is None:
            logger.error(
                f"Live entry for {pair}: no order state from gateway "
                f"(orderid={orderid}); not booking any position"
            )
            self._safe_cancel(orderid)
            return None

        if order.traded <= 0:
            logger.warning(
                f"Live entry for {pair} not filled "
                f"(status={order.status.value}, orderid={orderid})"
            )
            if order.status not in _TERMINAL_STATUSES:
                self._safe_cancel(orderid)
            return None

        if order.status == Status.PARTTRADED:
            logger.warning(
                f"Live entry for {pair} partially filled "
                f"{order.traded}/{amount}; cancelling remainder and booking filled part"
            )
            self._safe_cancel(orderid)

        fill_price = order.price if order.price > 0 else rate
        fill_amount = order.traded
        fill_stake = fill_price * fill_amount

        trade = self._pm.open_trade(
            pair=pair,
            rate=fill_price,
            amount=fill_amount,
            stake_amount=fill_stake,
            enter_tag=enter_tag,
            market_type=self._market_type,
        )
        logger.info(
            f"Live entry executed for {pair}: orderid={orderid}, "
            f"price={fill_price}, amount={fill_amount}, stake={fill_stake:.4f}"
        )

        from bullseye.order.stock_rules import make_fill_order

        self._fire_order_filled(
            pair, trade,
            make_fill_order(
                pair, "buy", fill_price, fill_amount, datetime.now()
            ),
        )
        return trade

    def _execute_exit_live(
        self,
        trade: LocalTrade,
        rate: float,
        exit_reason: str,
    ) -> Optional[LocalTrade]:
        """
        Send a close order through the gateway and close the trade on fill.

        Partial exit fills are treated conservatively: the remainder is
        cancelled, an error is logged, and the trade is kept open. The
        already-sold portion must be reconciled manually - safer than
        booking a wrong final state.
        """
        orderid = self._gateway.send_order({
            "symbol": trade.pair,
            "direction": Direction.SHORT,
            "offset": Offset.CLOSE,
            "order_type": OrderType.MARKET,
            "price": rate,
            "volume": trade.amount,
        })
        if not orderid:
            logger.error(f"Live exit for {trade.pair} rejected by gateway (no orderid)")
            return None

        order = self._wait_for_fill(orderid, trade=trade, is_entry=False)
        if order is None:
            logger.error(
                f"Live exit for {trade.pair}: no order state from gateway "
                f"(orderid={orderid}); trade remains open"
            )
            self._safe_cancel(orderid)
            return None

        if order.traded <= 0:
            logger.warning(
                f"Live exit for {trade.pair} not filled "
                f"(status={order.status.value}, orderid={orderid}); trade remains open"
            )
            if order.status not in _TERMINAL_STATUSES:
                self._safe_cancel(orderid)
            return None

        if order.traded < trade.amount - 1e-12:
            self._safe_cancel(orderid)
            logger.error(
                f"Live exit for {trade.pair} only partially filled "
                f"({order.traded}/{trade.amount}, orderid={orderid}). Trade kept open; "
                "reconcile the sold portion manually before the next exit attempt."
            )
            return None

        fill_price = order.price if order.price > 0 else rate
        closed_trade = self._pm.close_trade(
            trade=trade,
            rate=fill_price,
            exit_reason=exit_reason,
        )
        logger.info(
            f"Live exit executed for {trade.pair}: orderid={orderid}, "
            f"price={fill_price}, reason={exit_reason}"
        )

        from bullseye.order.stock_rules import make_fill_order

        self._fire_order_filled(
            trade.pair, closed_trade,
            make_fill_order(
                trade.pair, "sell" if not trade.is_short else "buy",
                fill_price, trade.amount, datetime.now(),
            ),
        )
        return closed_trade

    def execute_adjust(
        self,
        trade: LocalTrade,
        rate: float,
        current_time: Optional[datetime] = None,
    ) -> Optional[float]:
        """Evaluate and book a DCA add for a live open trade.

        Calls strategy.adjust_trade_position() (gated by
        position_adjustment_enable) and books a positive stake via
        PositionManager.adjust_position(). Live gateway routing for adds
        is not yet implemented: in live mode the add is booked locally
        after logging a warning (dry-run semantics).

        Returns the booked add stake, or None when no add happened.
        """
        if not self._strategy:
            return None
        if not getattr(self._strategy, "position_adjustment_enable", False):
            return None
        if trade.is_short:
            return None

        current_time = current_time or datetime.now()
        available = self._wallets.get_available_stake_amount()
        if available <= 0:
            return None

        try:
            net = trade.calc_profit_ratio(rate)
            add = self._strategy.adjust_trade_position(
                trade=trade,
                current_time=current_time,
                current_rate=rate,
                current_profit=net,
                min_stake=0.0,
                max_stake=available,
                current_entry_rate=rate,
                current_exit_rate=rate,
                current_entry_profit=net,
                current_exit_profit=net,
                min_limit=0.0,
                max_limit=available,
            )
        except AttributeError:
            return None
        except Exception as e:
            logger.warning(f"Error in adjust_trade_position: {e}")
            return None

        if add is None:
            return None
        if isinstance(add, (tuple, list)) and len(add) == 2:
            add = add[0]
            if add is None:
                return None
        try:
            add = float(add)
        except (TypeError, ValueError):
            return None
        if add <= 0:
            return None

        if self.is_live:
            logger.warning(
                f"Live DCA for {trade.pair} is not gateway-routed yet; "
                "booking locally with dry-run semantics"
            )
        if self._pm.adjust_position(trade, min(add, available), rate):
            return min(add, available)
        return None

    def _wait_for_fill(
        self,
        orderid: str,
        trade: Optional[LocalTrade] = None,
        is_entry: bool = True,
    ) -> Optional[OrderData]:
        """
        Poll gateway.query_order until terminal status or timeout.

        On timeout the strategy's check_buy/check_sell_timeout decides:
        True cancels and returns the last state, False extends the wait
        by another window (Freqtrade semantics).

        Returns the last observed OrderData, or None if the gateway never
        reported any state.
        """
        timeout = float(self._config.get("execution.order_timeout", 10.0))
        interval = float(self._config.get("execution.order_poll_interval", 0.5))
        deadline = time.monotonic() + timeout
        last: Optional[OrderData] = None

        while True:
            try:
                order = self._gateway.query_order({"orderid": orderid})
            except Exception as e:
                logger.warning(f"query_order failed for {orderid}: {e}")
                order = None

            if order is not None:
                last = order
                if order.status in _TERMINAL_STATUSES:
                    return order

            if time.monotonic() >= deadline:
                if self._check_order_timeout(orderid, trade, is_entry, last):
                    return last
                deadline = time.monotonic() + timeout

            time.sleep(max(0.01, interval))

    def _check_order_timeout(
        self,
        orderid: str,
        trade: Optional[LocalTrade],
        is_entry: bool,
        last: Optional[OrderData],
    ) -> bool:
        """Ask the strategy whether a timed-out order should be cancelled.

        Returns True to cancel (default when no callback), False to wait.
        """
        if self._strategy is not None and trade is not None:
            try:
                cb = (self._strategy.check_buy_timeout if is_entry
                      else self._strategy.check_sell_timeout)
                pair = trade.pair if trade else ""
                keep_waiting = cb(
                    pair=pair, trade=trade, order=last,
                    current_time=datetime.now(),
                )
                # Freqtrade convention: True means "timed out, cancel it".
                if keep_waiting is True:
                    logger.info(f"Order {orderid} timed out (strategy confirmed)")
                    return True
                if keep_waiting is False:
                    logger.info(f"Order {orderid} extended by strategy")
                    return False
            except AttributeError:
                pass
            except Exception as e:
                logger.warning(f"Error in order timeout callback: {e}")
        logger.warning(
            f"Order {orderid} not confirmed within timeout "
            f"(last status: {last.status.value if last else 'unknown'})"
        )
        return True

    def _safe_cancel(self, orderid: str) -> None:
        """Best-effort cancel used on timeout/partial fills."""
        try:
            self._gateway.cancel_order({"orderid": orderid})
            logger.info(f"Cancel requested for {orderid}")
        except Exception as e:
            logger.warning(f"Cancel attempt failed for {orderid}: {e}")

    # ==================== Trailing Stop ====================

    def check_trailing_stop(
        self,
        trade: LocalTrade,
        current_rate: float,
    ) -> bool:
        """
        Check if trailing stop should be triggered.

        Args:
            trade: Trade to check
            current_rate: Current market price

        Returns:
            True if trailing stop should trigger
        """
        if not self._strategy:
            return False

        try:
            trailing_stop = getattr(self._strategy, 'trailing_stop', False)
            if not trailing_stop:
                return False
        except AttributeError:
            return False

        # Update trade's rate tracking
        trade.update_rate(current_rate)

        # Check if we should start trailing
        try:
            trailing_only_offset_is_reached = getattr(
                self._strategy, 'trailing_only_offset_is_reached', False
            )
            trailing_stop_positive_offset = getattr(
                self._strategy, 'trailing_stop_positive_offset', 0.0
            )

            if trailing_only_offset_is_reached:
                profit_ratio = trade.calc_profit_ratio(current_rate)
                if profit_ratio < trailing_stop_positive_offset:
                    return False
        except AttributeError:
            pass

        # Calculate trailing stop price
        try:
            trailing_stop_positive = getattr(self._strategy, 'trailing_stop_positive', 0.01)
        except AttributeError:
            trailing_stop_positive = 0.01

        stop_price = trade.max_rate * (1 - trailing_stop_positive)

        # Check if current rate has dropped below trailing stop
        if current_rate <= stop_price:
            logger.info(
                f"Trailing stop triggered for {trade.pair}: "
                f"max_rate={trade.max_rate}, current={current_rate}, "
                f"stop_price={stop_price}"
            )
            return True

        return False

    # ==================== Custom Exit ====================

    def check_custom_exit(
        self,
        trade: LocalTrade,
        current_rate: float,
        current_time: datetime,
    ) -> Optional[str]:
        """
        Check for custom exit condition from strategy.

        Args:
            trade: Trade to check
            current_rate: Current market price
            current_time: Current time

        Returns:
            Exit reason string if custom exit triggered, None otherwise
        """
        if not self._strategy:
            return None

        try:
            current_profit = trade.calc_profit_ratio(current_rate)

            exit_reason = self._strategy.custom_exit(
                pair=trade.pair,
                trade=trade,
                current_time=current_time,
                current_rate=current_rate,
                current_profit=current_profit,
                exit_reason=None,
            )

            if exit_reason:
                logger.info(f"Custom exit triggered for {trade.pair}: {exit_reason}")
                return exit_reason

        except AttributeError:
            # Strategy doesn't implement custom_exit
            pass
        except Exception as e:
            logger.warning(f"Error checking custom exit: {e}")

        return None

    # ==================== T+1 Helpers ====================

    def can_sell_trade(self, trade: LocalTrade) -> bool:
        """
        Check if a trade can be sold (respects T+1 for stocks).

        Args:
            trade: Trade to check

        Returns:
            True if trade can be sold
        """
        return trade.available_for_sale

    def get_trades_available_for_sale(self) -> list:
        """
        Get all trades that can be sold (respects T+1 for stocks).

        Returns:
            List of trades available for sale
        """
        return self._pm.get_trades_available_for_sale()

    def get_trades_pending_settlement(self) -> list:
        """
        Get trades that are pending T+1 settlement.

        Returns:
            List of trades waiting for settlement
        """
        return self._pm.get_trades_pending_settlement()

    # ==================== Order Info ====================

    def get_order_fee(self, order_type: str, amount: float, rate: float) -> float:
        """
        Calculate fee for an order.

        Args:
            order_type: "entry" or "exit"
            amount: Order amount
            rate: Order price

        Returns:
            Fee amount in stake currency
        """
        value = amount * rate
        if self._fee_model is not None:
            return self._fee_model.fee(value, is_sell=(order_type == "exit"))
        return value * self._fee_rate

    def get_total_profit(self) -> float:
        """
        Get total realized profit from closed trades.

        Returns:
            Total profit in stake currency
        """
        stats = self._pm.get_stats()
        return stats.get("total_profit", 0.0)

    def get_open_trade_value(self) -> float:
        """
        Get total value of open trades.

        Returns:
            Total value in stake currency
        """
        total = 0.0
        for trade in self._pm.get_open_trades():
            total += trade.stake_amount
        return total

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get trading statistics.

        Returns:
            Dictionary with trading statistics
        """
        return self._pm.get_stats()
