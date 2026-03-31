"""
Position Manager - Trade and position management for Bullseye.

Manages local trades, calculates profits, and handles stop-loss/ROI logic.
Supports automatic T+1/T+0 detection for different markets.

Compatible with Freqtrade v3 strategy interface.

T+1 Auto Detection:
- A-shares (000001.SZ, 600000.SH): T+1
- US Stocks (AAPL, GOOGL): T+0
- HK Stocks (00700.HK): T+0
- Crypto (BTC/USDT): T+0
- Futures (AU2506@SHFE): T+0
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from bullseye.configuration.config import Config
from bullseye.strategy.interface import IStrategy
from bullseye.wallets.wallets import Wallets
from bullseye.order.settlement import (
    SettlementDetector,
    SettlementRule,
    SettlementType,
    detect_settlement_rule,
    is_t1_market,
    get_settlement_date as calc_settlement_date,
)

logger = logging.getLogger(__name__)


class MarketType(Enum):
    """
    Market type enumeration.

    Different markets have different trading rules:
    - AUTO: Auto-detect from pair format
    - CRYPTO: T+0, can trade 24/7
    - STOCK: T+1 for A-shares, T+0 for US/HK stocks
    - FUTURE: T+0, with leverage
    """
    AUTO = "auto"
    CRYPTO = "crypto"
    STOCK = "stock"
    FUTURE = "future"


class ExitType(Enum):
    """Exit reason types."""
    ROI = "roi"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    EXIT_SIGNAL = "exit_signal"
    CUSTOM_EXIT = "custom_exit"
    FORCE_EXIT = "force_exit"
    LIQUIDATION = "liquidation"
    T1_RESTRICTION = "t1_restriction"  # Attempted to sell before T+1


@dataclass
class LocalTrade:
    """
    Local trade record for position tracking.

    This represents a single trade (position) from open to close.
    In dry-run mode, this is the primary trade tracking mechanism.

    Compatible with Freqtrade v3 strategy interface.

    T+1 Support:
    - For STOCK market type, settlement_date is set to T+1 from open_date
    - available_for_sale property checks if position can be sold
    """

    # ==================== Identification ====================
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    pair: str = ""
    exchange: str = ""
    strategy: str = ""
    timeframe: str = ""

    # ==================== Market Type ====================
    market_type: MarketType = MarketType.CRYPTO

    # ==================== Opening Information ====================
    open_date: datetime = field(default_factory=datetime.now)
    open_rate: float = 0.0
    open_rate_requested: Optional[float] = None
    amount: float = 0.0
    amount_requested: Optional[float] = None
    stake_amount: float = 0.0
    max_stake_amount: float = 0.0
    fee_open: float = 0.0
    fee_open_cost: Optional[float] = None
    enter_tag: Optional[str] = None
    is_short: bool = False

    # ==================== Closing Information ====================
    close_date: Optional[datetime] = None
    close_rate: Optional[float] = None
    close_rate_requested: Optional[float] = None
    fee_close: float = 0.0
    fee_close_cost: Optional[float] = None
    exit_reason: Optional[str] = None
    exit_order_status: Optional[str] = None

    # ==================== Profit Tracking ====================
    realized_profit: float = 0.0

    # ==================== Stop Loss Tracking ====================
    stop_loss: float = 0.0
    stop_loss_pct: Optional[float] = None
    initial_stop_loss: Optional[float] = None
    initial_stop_loss_pct: Optional[float] = None
    is_stop_loss_trailing: bool = False

    # ==================== Rate Tracking ====================
    max_rate: float = 0.0
    min_rate: float = float("inf")

    # ==================== Leverage (for futures/margin) ====================
    leverage: float = 1.0
    interest_rate: float = 0.0

    # ==================== Orders ====================
    orders: List[Dict[str, Any]] = field(default_factory=list)

    # ==================== T+1 Support ====================
    # Settlement rule (auto-detected if None)
    settlement_rule: Optional[SettlementRule] = None
    # Cached settlement date
    settlement_date: Optional[datetime] = None

    def __post_init__(self):
        """Initialize computed fields after dataclass creation."""
        # Auto-detect settlement rule if not provided
        if self.settlement_rule is None:
            self.settlement_rule = detect_settlement_rule(self.pair, self.exchange)

        # Calculate settlement date for T+N markets
        if self.settlement_rule.settlement_type != SettlementType.T0:
            if self.settlement_date is None:
                self.settlement_date = calc_settlement_date(
                    self.open_date, self.pair, self.exchange
                )

    # ==================== T+1 Properties ====================

    @property
    def available_for_sale(self) -> bool:
        """
        Check if the position is available for sale.

        Auto-detected based on pair format:
        - T+0: Crypto, US stocks, HK stocks, futures
        - T+1: A-shares (China stocks)

        Returns:
            bool: True if position can be sold
        """
        if self.settlement_rule is None:
            # Fallback: auto-detect
            return not is_t1_market(self.pair, self.exchange)

        if self.settlement_rule.settlement_type == SettlementType.T0:
            return True

        # T+N: Check if settlement date has passed
        if self.settlement_date is None:
            return False

        return datetime.now() >= self.settlement_date

    @property
    def trading_mode(self) -> str:
        """Get trading mode string."""
        if self.settlement_rule:
            return self.settlement_rule.market_name
        return "Unknown"

    @property
    def is_t1_restricted(self) -> bool:
        """Check if this trade is under T+1 restriction."""
        return self.settlement_rule is not None and \
               self.settlement_rule.settlement_type != SettlementType.T0 and \
               not self.available_for_sale

    @property
    def time_in_trade(self) -> timedelta:
        """Get time since trade was opened."""
        end_date = self.close_date or datetime.now()
        return end_date - self.open_date

    @property
    def minutes_in_trade(self) -> float:
        """Get minutes since trade was opened."""
        return self.time_in_trade.total_seconds() / 60

    # ==================== Core Properties ====================

    @property
    def is_open(self) -> bool:
        """Check if trade is still open."""
        return self.close_date is None

    @property
    def open_trade_value(self) -> float:
        """Calculate the total value of the open trade."""
        return self.stake_amount + self.fee_open

    @property
    def entry_side(self) -> str:
        """Get entry side (buy/sell)."""
        return "sell" if self.is_short else "buy"

    @property
    def exit_side(self) -> str:
        """Get exit side (sell/buy)."""
        return "buy" if self.is_short else "sell"

    @property
    def close_profit(self) -> Optional[float]:
        """Calculate the profit ratio after closing."""
        if self.close_rate is None:
            return None
        return self.calc_profit_ratio(self.close_rate)

    @property
    def close_profit_abs(self) -> Optional[float]:
        """Calculate the absolute profit after closing."""
        if self.close_rate is None:
            return None
        return self.calc_profit(self.close_rate)

    @property
    def current_profit(self) -> float:
        """Get current profit ratio (for open trades, use current market rate)."""
        # This should be updated with current rate externally
        return 0.0

    # ==================== Profit Calculation ====================

    def calc_profit_ratio(self, current_rate: float) -> float:
        """
        Calculate profit ratio at given rate.

        Args:
            current_rate: Current or closing price

        Returns:
            Profit ratio (e.g., 0.05 for 5% profit)
        """
        import math

        # Validate inputs
        if self.open_rate == 0 or not math.isfinite(self.open_rate):
            return 0.0
        if not math.isfinite(current_rate):
            return 0.0

        # For leveraged trades
        leverage = self.leverage or 1.0

        if self.is_short:
            # Short: profit when price goes down
            profit = (self.open_rate - current_rate) / self.open_rate
        else:
            # Long: profit when price goes up
            profit = (current_rate - self.open_rate) / self.open_rate

        result = profit * leverage

        # Ensure result is finite
        if not math.isfinite(result):
            return 0.0

        return result

    def calc_profit(self, current_rate: float) -> float:
        """
        Calculate absolute profit at given rate.

        Args:
            current_rate: Current or closing price

        Returns:
            Absolute profit in stake currency
        """
        import math

        # Validate inputs
        if self.open_rate == 0 or not math.isfinite(self.open_rate):
            return 0.0
        if not math.isfinite(current_rate):
            return 0.0

        # Current value
        current_value = current_rate * self.amount
        open_value = self.open_rate * self.amount

        if self.is_short:
            profit = open_value - current_value
        else:
            profit = current_value - open_value

        # Subtract fees
        profit -= self.fee_open
        if self.close_rate is not None:
            profit -= self.fee_close

        # Add realized profit from partial closes
        profit += self.realized_profit

        # Ensure result is finite
        if not math.isfinite(profit):
            return 0.0

        return profit

    # ==================== Rate Tracking ====================

    def update_rate(self, current_rate: float) -> None:
        """
        Update the max and min rates seen during trade.

        Args:
            current_rate: Current market price
        """
        self.max_rate = max(self.max_rate, current_rate)
        if self.min_rate == float("inf"):
            self.min_rate = current_rate
        else:
            self.min_rate = min(self.min_rate, current_rate)

    def adjust_stop_loss(self, current_rate: float, stop_loss_pct: float) -> None:
        """
        Adjust stop loss level based on current rate.

        For trailing stops, this will move the stop loss up but never down.

        Args:
            current_rate: Current market price
            stop_loss_pct: Stop loss percentage (negative, e.g., -0.1 for 10%)
        """
        if stop_loss_pct == 0:
            return

        # Calculate new stop loss price
        new_stop_price = current_rate * (1 + stop_loss_pct)

        # Only move stop loss up (for long positions)
        if new_stop_price > self.stop_loss:
            self.stop_loss = new_stop_price
            self.is_stop_loss_trailing = True
            logger.debug(f"Adjusted stop loss for {self.pair} to {self.stop_loss}")

    def __repr__(self) -> str:
        status = "open" if self.is_open else "closed"
        t1_status = f", T+1={self.available_for_sale}" if self.market_type == MarketType.STOCK else ""
        return f"LocalTrade({self.pair}, {status}, stake={self.stake_amount}{t1_status})"


class PositionManager:
    """
    Position Manager for Bullseye.

    Manages open trades, calculates profits, and handles
    stop-loss, trailing stop, ROI, and T+1 logic.

    Thread Safety:
    - All trade operations are protected by a lock
    - Safe for concurrent access from strategy runner and callbacks
    """

    def __init__(
        self,
        config: Config,
        wallets: Wallets,
        strategy: Optional[IStrategy] = None,
    ):
        """
        Initialize the Position Manager.

        Args:
            config: Configuration object
            wallets: Wallet manager
            strategy: Strategy instance for stop-loss/ROI settings
        """
        from threading import Lock

        self._config = config
        self._wallets = wallets
        self._strategy = strategy

        # Thread safety
        self._lock = Lock()

        # Active trades: pair -> LocalTrade
        self._trades: Dict[str, LocalTrade] = {}

        # Closed trades history
        self._closed_trades: List[LocalTrade] = []

        # Settings
        self._max_open_trades = config.max_open_trades
        self._fee_rate = 0.001  # Default 0.1% fee
        self._market_type = self._get_market_type(config)

    def _get_market_type(self, config: Config) -> MarketType:
        """Get market type from configuration."""
        market_str = config.market_type.lower()
        if market_str == "stock":
            return MarketType.STOCK
        elif market_str == "future":
            return MarketType.FUTURE
        else:
            return MarketType.CRYPTO

    def set_strategy(self, strategy: IStrategy) -> None:
        """Set the strategy instance."""
        self._strategy = strategy

    # ==================== Trade Management ====================

    def get_open_trades(self) -> List[LocalTrade]:
        """Get all open trades (thread-safe copy)."""
        with self._lock:
            return list(self._trades.values())

    def get_trade(self, trade_id: str) -> Optional[LocalTrade]:
        """Get a trade by ID."""
        with self._lock:
            for trade in self._trades.values():
                if trade.id == trade_id:
                    return trade
        return None

    def get_trade_for_pair(self, pair: str) -> Optional[LocalTrade]:
        """Get the open trade for a pair."""
        with self._lock:
            return self._trades.get(pair)

    def has_open_trade(self, pair: str) -> bool:
        """Check if there's an open trade for a pair."""
        with self._lock:
            return pair in self._trades

    def can_open_trade(self) -> bool:
        """Check if a new trade can be opened."""
        with self._lock:
            return len(self._trades) < self._max_open_trades

    def get_open_trade_count(self) -> int:
        """Get the count of open trades."""
        with self._lock:
            return len(self._trades)

    def get_closed_trades(self) -> List[LocalTrade]:
        """Get all closed trades (thread-safe copy)."""
        with self._lock:
            return self._closed_trades.copy()

    # ==================== Open/Close Trade ====================

    def open_trade(
        self,
        pair: str,
        rate: float,
        amount: float,
        stake_amount: float,
        enter_tag: Optional[str] = None,
        market_type: Optional[MarketType] = None,
    ) -> LocalTrade:
        """
        Open a new trade.

        Args:
            pair: Trading pair
            rate: Entry price
            amount: Amount of asset
            stake_amount: Stake currency amount
            enter_tag: Entry signal tag
            market_type: Market type (default: from config)

        Returns:
            The created LocalTrade

        Raises:
            ValueError: If pair already has an open trade
        """
        with self._lock:
            # Check if pair already has an open trade
            if pair in self._trades:
                raise ValueError(f"Trade already open for {pair}")

            # Calculate fee
            fee = stake_amount * self._fee_rate

            # Use provided market type or default from config
            mt = market_type or self._market_type

            # Create trade
            trade = LocalTrade(
                pair=pair,
                exchange=self._config.exchange_name,
                strategy=self._config.strategy or "Unknown",
                timeframe=self._config.timeframe,
                market_type=mt,
                open_date=datetime.now(),
                open_rate=rate,
                amount=amount,
                stake_amount=stake_amount,
                fee_open=fee,
                enter_tag=enter_tag,
                max_rate=rate,
                min_rate=rate,
            )

            # Set initial stop loss if strategy has one
            if self._strategy and hasattr(self._strategy, 'stoploss') and self._strategy.stoploss:
                trade.stop_loss_pct = self._strategy.stoploss
                trade.stop_loss = rate * (1 + self._strategy.stoploss)
                trade.initial_stop_loss_pct = self._strategy.stoploss
                trade.initial_stop_loss = trade.stop_loss

            # Register trade
            self._trades[pair] = trade

        # Update wallet (outside lock to avoid deadlock)
        self._wallets.deduct_amount(self._config.stake_currency, stake_amount + fee)

        # Log T+1 info for stocks
        if mt == MarketType.STOCK:
            logger.info(
                f"Opened T+1 trade: {pair} @ {rate}, amount={amount}, stake={stake_amount}, "
                f"settlement={trade.settlement_date}"
            )
        else:
            logger.info(f"Opened trade: {pair} @ {rate}, amount={amount}, stake={stake_amount}")

        return trade

    def close_trade(
        self,
        trade: LocalTrade,
        rate: float,
        exit_reason: str,
    ) -> LocalTrade:
        """
        Close an open trade.

        Args:
            trade: Trade to close
            rate: Exit price
            exit_reason: Reason for exit

        Returns:
            The closed LocalTrade

        Raises:
            ValueError: If trade cannot be sold (T+1 restriction) or not found
        """
        # Check T+1 restriction (outside lock for performance)
        if not trade.available_for_sale:
            raise ValueError(
                f"Cannot close trade for {trade.pair}: T+1 restriction. "
                f"Settlement date: {trade.settlement_date}"
            )

        with self._lock:
            # Verify trade exists
            if trade.pair not in self._trades:
                raise ValueError(f"No open trade found for {trade.pair}")

            # Calculate closing value and fee
            close_value = rate * trade.amount
            fee = close_value * self._fee_rate

            # Update trade
            trade.close_date = datetime.now()
            trade.close_rate = rate
            trade.fee_close = fee
            trade.exit_reason = exit_reason

            # Calculate final profit
            profit = trade.calc_profit(rate)

            # Remove from open trades
            del self._trades[trade.pair]

            # Add to closed trades
            self._closed_trades.append(trade)

        # Update wallet - return stake + profit (outside lock to avoid deadlock)
        total_return = trade.stake_amount + profit
        self._wallets.add_amount(self._config.stake_currency, total_return)

        logger.info(
            f"Closed trade: {trade.pair} @ {rate}, "
            f"profit={profit:.4f} ({(trade.close_profit or 0) * 100:.2f}%), "
            f"reason={exit_reason}"
        )
        return trade

    # ==================== Profit Calculation ====================

    def calc_profit(self, trade: LocalTrade, current_rate: float) -> float:
        """Calculate current profit for a trade."""
        return trade.calc_profit(current_rate)

    def calc_profit_ratio(self, trade: LocalTrade, current_rate: float) -> float:
        """Calculate current profit ratio for a trade."""
        return trade.calc_profit_ratio(current_rate)

    # ==================== Stop Loss ====================

    def check_stoploss(self, trade: LocalTrade, current_rate: float) -> bool:
        """
        Check if stop loss should be triggered.

        Args:
            trade: Trade to check
            current_rate: Current market price

        Returns:
            True if stop loss should trigger
        """
        if not self._strategy:
            return False

        stoploss = getattr(self._strategy, 'stoploss', 0)
        if stoploss == 0:
            return False

        # Update trade's max/min rate tracking
        trade.update_rate(current_rate)

        # Adjust trailing stop if enabled
        if getattr(self._strategy, 'trailing_stop', False):
            self._adjust_trailing_stop(trade, current_rate)

        # Check if price has hit stop loss level
        if trade.stop_loss > 0 and current_rate <= trade.stop_loss:
            logger.info(f"Stop loss triggered for {trade.pair} at {current_rate}")
            return True

        return False

    def _adjust_trailing_stop(self, trade: LocalTrade, current_rate: float) -> None:
        """
        Adjust trailing stop loss.

        Args:
            trade: Trade to adjust
            current_rate: Current market price
        """
        if not self._strategy:
            return

        trailing_stop_positive = getattr(self._strategy, 'trailing_stop_positive', 0.01)
        trailing_stop_positive_offset = getattr(self._strategy, 'trailing_stop_positive_offset', 0.0)
        trailing_only_offset_is_reached = getattr(self._strategy, 'trailing_only_offset_is_reached', False)

        # Calculate profit ratio
        profit_ratio = trade.calc_profit_ratio(current_rate)

        # Check if we should start trailing
        if trailing_only_offset_is_reached:
            if profit_ratio < trailing_stop_positive_offset:
                return

        # Only adjust stop loss upward (for long positions)
        if current_rate > trade.max_rate:
            new_stop_price = current_rate * (1 - trailing_stop_positive)
            if new_stop_price > trade.stop_loss:
                trade.stop_loss = new_stop_price
                logger.debug(
                    f"Trailing stop adjusted for {trade.pair}: "
                    f"new_stop={new_stop_price}, rate={current_rate}"
                )

    # ==================== ROI ====================

    def check_roi(
        self,
        trade: LocalTrade,
        current_rate: float,
        current_time: Optional[datetime] = None,
    ) -> Optional[str]:
        """
        Check if ROI target has been reached.

        Args:
            trade: Trade to check
            current_rate: Current market price
            current_time: Current time (default: now)

        Returns:
            Exit reason string if ROI triggered, None otherwise
        """
        if not self._strategy:
            return None

        minimal_roi = getattr(self._strategy, 'minimal_roi', {})
        if not minimal_roi:
            return None

        current_time = current_time or datetime.now()

        # Calculate trade duration in minutes
        trade_duration = trade.minutes_in_trade

        # Calculate current profit ratio
        profit_ratio = trade.calc_profit_ratio(current_rate)

        # Check ROI table (sorted by time descending)
        for minutes_str, roi_value in sorted(
            minimal_roi.items(),
            key=lambda x: int(x[0]) if str(x[0]).isdigit() else float("inf"),
            reverse=True,
        ):
            try:
                minutes = int(minutes_str)
            except ValueError:
                continue

            if trade_duration >= minutes:
                if profit_ratio >= roi_value:
                    return f"roi_{minutes}m"

        return None

    # ==================== T+1 Helpers ====================

    def get_trades_available_for_sale(self) -> List[LocalTrade]:
        """
        Get all trades that can be sold (respects T+1 for stocks).

        Returns:
            List of trades available for sale
        """
        return [t for t in self._trades.values() if t.available_for_sale]

    def get_trades_pending_settlement(self) -> List[LocalTrade]:
        """
        Get trades that are pending T+1 settlement.

        Returns:
            List of trades waiting for settlement
        """
        return [t for t in self._trades.values() if not t.available_for_sale]

    # ==================== Statistics ====================

    def get_stats(self) -> Dict[str, Any]:
        """
        Get trading statistics.

        Returns:
            Dictionary with trading statistics
        """
        closed = self._closed_trades

        if not closed:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_profit": 0.0,
                "avg_profit": 0.0,
                "max_profit": 0.0,
                "max_loss": 0.0,
                "open_trades": len(self._trades),
                "pending_settlement": len(self.get_trades_pending_settlement()),
            }

        profits = [t.close_profit_abs for t in closed if t.close_profit_abs is not None]
        winning = [p for p in profits if p > 0]
        losing = [p for p in profits if p < 0]

        return {
            "total_trades": len(closed),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": len(winning) / len(closed) if closed else 0.0,
            "total_profit": sum(profits),
            "avg_profit": sum(profits) / len(profits) if profits else 0.0,
            "max_profit": max(profits) if profits else 0.0,
            "max_loss": min(profits) if profits else 0.0,
            "open_trades": len(self._trades),
            "pending_settlement": len(self.get_trades_pending_settlement()),
        }

    def reset(self) -> None:
        """Reset all trades."""
        self._trades.clear()
        self._closed_trades.clear()
        logger.info("Position manager reset")
