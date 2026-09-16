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
        self._fee_rate = 0.001  # Default 0.1% fee
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

    def calculate_stake_amount(self, pair: str) -> float:
        """
        Calculate the stake amount for a new trade.

        Uses strategy's custom_stake_amount if available, otherwise
        uses config settings.

        Args:
            pair: Trading pair

        Returns:
            Stake amount in stake currency
        """
        # Get base stake amount from wallet
        base_stake = self._wallets.get_trade_stake_amount(pair)

        # Check for custom stake amount from strategy
        if self._strategy:
            try:
                custom_stake = self._strategy.custom_stake_amount(
                    pair=pair,
                    current_time=datetime.now(),
                    current_rate=0.0,  # Will be updated before order
                    proposed_stake=base_stake,
                    min_stake=0.0,
                    max_stake=self._wallets.get_available_stake_amount(),
                    leverage=1.0,
                    entry_tag=None,
                    side="long",
                )
                if custom_stake is not None:
                    base_stake = custom_stake
            except AttributeError:
                # Strategy doesn't implement custom_stake_amount
                pass
            except Exception as e:
                logger.warning(f"Error getting custom stake amount: {e}")

        return base_stake

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
    ) -> Optional[LocalTrade]:
        """
        Execute an entry order (simulated in dry-run mode).

        Args:
            pair: Trading pair
            rate: Entry price
            enter_tag: Entry signal tag
            stake_amount: Override stake amount (optional)

        Returns:
            The created LocalTrade if successful, None otherwise
        """
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
            stake_amount = self.calculate_stake_amount(pair)

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

        # Calculate amount
        amount = self.calculate_amount(rate, stake_amount)

        if amount <= 0:
            logger.warning(f"Invalid amount for {pair}: {amount}")
            return None

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
        )

        logger.info(
            f"Executed entry for {pair}: "
            f"rate={rate}, amount={amount}, stake={stake_amount}, tag={enter_tag}"
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

        order = self._wait_for_fill(orderid)
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

        order = self._wait_for_fill(orderid)
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
        return closed_trade

    def _wait_for_fill(self, orderid: str) -> Optional[OrderData]:
        """
        Poll gateway.query_order until terminal status or timeout.

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
                logger.warning(
                    f"Order {orderid} not confirmed within {timeout}s "
                    f"(last status: {last.status.value if last else 'unknown'})"
                )
                return last

            time.sleep(max(0.01, interval))

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
