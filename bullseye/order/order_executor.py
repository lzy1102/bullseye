"""
Order Executor - Order execution and trade management for Bullseye.

Handles the execution of entry and exit orders, including position sizing,
trailing stop management, and T+1 compliance checking.
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from bullseye.configuration.config import Config
from bullseye.order.position_manager import LocalTrade, PositionManager, MarketType
from bullseye.strategy.interface import IStrategy
from bullseye.wallets.wallets import Wallets

logger = logging.getLogger(__name__)


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

        # Settings
        self._fee_rate = 0.001  # Default 0.1% fee
        self._stake_currency = config.stake_currency

        # Market type from config
        self._market_type = self._get_market_type_from_config()

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

        # Execute the trade
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

        # Close the trade
        closed_trade = self._pm.close_trade(
            trade=trade,
            rate=rate,
            exit_reason=exit_reason,
        )

        return closed_trade

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
