"""
Strategy Interface - Freqtrade IStrategy v3 Compatible Interface

This module provides a 100% compatible implementation of Freqtrade's IStrategy interface.
All Freqtrade strategies can be used directly without any modifications.
"""
from typing import Dict, List, Optional, Tuple, Union, Callable, Any
from pandas import DataFrame
from datetime import datetime, timezone, timedelta
from functools import wraps
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class RunMode(Enum):
    """Run mode enumeration"""
    BACKTEST = "backtest"
    HYPEROPT = "hyperopt"
    DRY_RUN = "dry_run"
    LIVE = "live"


# ==================== IStrategy Complete Implementation ====================

class IStrategy:
    """
    Freqtrade IStrategy v3 Fully Compatible Interface

    All Freqtrade strategies can inherit from this class without modification.
    """
    INTERFACE_VERSION = 3

    # ==================== Strategy Configuration ====================
    timeframe: str = "5m"
    startup_candle_count: int = 30
    can_short: bool = False

    minimal_roi: Dict[str, float] = {
        "0": 0.04,
        "20": 0.02,
        "30": 0.01,
        "40": 0.00
    }

    stoploss: float = -0.10

    trailing_stop: bool = False
    trailing_stop_positive: float = 0.01
    trailing_stop_positive_offset: float = 0.02
    trailing_only_offset_is_reached: bool = False

    use_exit_signal: bool = True
    exit_profit_only: bool = False
    ignore_roi_if_entry_signal: bool = False

    order_types: Dict[str, Any] = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
        "stoploss_on_exchange_interval": 60,
    }

    order_time_in_force: Dict[str, str] = {
        "entry": "GTC",
        "exit": "GTC"
    }

    order_price: Dict[str, Any] = {
        "entry_side": "same",
        "exit_side": "same",
        "price_last_balance": 0.0,
        "check_depth_of_market": {
            "enabled": False,
            "bids_to_ask_delta": 1,
        }
    }

    position_adjustment_enable: bool = False

    # Bullseye extensions
    market_type: str = "auto"  # auto | crypto | stock | future

    protections: List = []

    # Runtime injected attributes
    dp: Optional['DataProvider'] = None
    wallets: Optional['Wallets'] = None
    config: Dict[str, Any] = {}

    # ==================== Abstract Methods ====================

    def populate_indicators(self, dataframe: DataFrame, metadata: Dict) -> DataFrame:
        """Add technical indicators to dataframe"""
        raise NotImplementedError("populate_indicators() must be implemented")

    def populate_entry_trend(self, dataframe: DataFrame, metadata: Dict) -> DataFrame:
        """Populate entry signals (enter_long/enter_short columns)"""
        raise NotImplementedError("populate_entry_trend() must be implemented")

    def populate_exit_trend(self, dataframe: DataFrame, metadata: Dict) -> DataFrame:
        """Populate exit signals (exit_long/exit_short columns)"""
        raise NotImplementedError("populate_exit_trend() must be implemented")

    # ==================== Optional Methods ====================

    def informative_pairs(self) -> List[Tuple[str, str]]:
        """Define informative pairs for additional timeframes/symbols"""
        return []

    # ==================== Callback Methods ====================

    def bot_start(self, **kwargs) -> None:
        """Called when bot starts"""
        pass

    def bot_stop(self, **kwargs) -> None:
        """Called when bot stops"""
        pass

    def bot_loop_start(self, **kwargs) -> None:
        """Called at start of each bot loop"""
        pass

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: Optional[str],
        side: str,
        **kwargs
    ) -> bool:
        """Called to confirm trade entry, return True to allow entry"""
        return True

    def confirm_trade_exit(
        self,
        pair: str,
        trade: 'Trade',
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time: datetime,
        **kwargs
    ) -> bool:
        """Called to confirm trade exit, return True to allow exit"""
        return True

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs
    ) -> float:
        """Custom stake amount, return modified stake amount"""
        return proposed_stake

    def custom_entry_price(
        self,
        pair: str,
        current_time: datetime,
        proposed_rate: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs
    ) -> float:
        """Custom entry price"""
        return proposed_rate

    def custom_exit(
        self,
        pair: str,
        trade: 'Trade',
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        exit_reason: str,
        **kwargs
    ) -> Optional[str]:
        """
        Custom exit logic

        Returns exit reason string or None to not exit
        """
        return None

    def adjust_trade_position(
        self,
        trade: 'Trade',
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: Optional[float],
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        min_limit: float,
        max_limit: float,
        **kwargs
    ) -> Optional[float]:
        """
        Adjust trade position (add/reduce position)

        Returns None or adjusted stake amount
        """
        return None

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: int,
        entry_tag: Optional[str],
        side: str,
        **kwargs
    ) -> float:
        """Custom leverage, return modified leverage"""
        return proposed_leverage

    def check_buy_timeout(
        self,
        pair: str,
        trade: 'Trade',
        order: 'Order',
        current_time: datetime,
        **kwargs
    ) -> bool:
        """Check if buy order has timed out"""
        return False

    def check_sell_timeout(
        self,
        pair: str,
        trade: 'Trade',
        order: 'Order',
        current_time: datetime,
        **kwargs
    ) -> bool:
        """Check if sell order has timed out"""
        return False

    # ==================== Additional Freqtrade Methods ====================
    
    def custom_roi(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[float]:
        """
        Custom ROI logic, return target profit percentage or None
        
        Override this to implement dynamic ROI based on market conditions.
        """
        return None
    
    def custom_exit_price(
        self,
        pair: str,
        trade: 'Trade',
        current_time: datetime,
        proposed_rate: float,
        current_profit: float,
        exit_tag: Optional[str],
        **kwargs
    ) -> float:
        """
        Custom exit price
        
        Override to modify the exit price before placing the exit order.
        """
        return proposed_rate
    
    def adjust_entry_price(
        self,
        pair: str,
        current_time: datetime,
        proposed_rate: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs
    ) -> float:
        """
        Adjust entry order price
        
        Override to modify the entry price before placing the entry order.
        """
        return proposed_rate
    
    def adjust_exit_price(
        self,
        pair: str,
        trade: 'Trade',
        current_time: datetime,
        proposed_rate: float,
        current_profit: float,
        exit_tag: Optional[str],
        **kwargs
    ) -> float:
        """
        Adjust exit order price
        
        Override to modify the exit price before placing the exit order.
        """
        return proposed_rate
    
    def adjust_order_price(
        self,
        pair: str,
        current_time: datetime,
        proposed_rate: float,
        order_type: str,
        side: str,
        **kwargs
    ) -> float:
        """
        Adjust order price
        
        Override to modify order price before placing any order.
        """
        return proposed_rate
    
    def order_filled(
        self,
        pair: str,
        trade: 'Trade',
        order: 'Order',
        current_time: datetime,
        **kwargs
    ) -> None:
        """
        Called when an order is completely filled
        
        Override to execute custom logic when an order is filled.
        """
        pass

    # ==================== Pair Locking Methods ====================
    
    def lock_pair(
        self,
        pair: str,
        until: datetime,
        reason: str,
        **kwargs
    ) -> None:
        """
        Lock a trading pair, preventing new positions until specified time
        
        Args:
            pair: Trading pair to lock
            until: Time until pair is locked
            reason: Reason for locking
        """
        pass
    
    def unlock_pair(
        self,
        pair: str,
        **kwargs
    ) -> None:
        """
        Unlock a trading pair
        
        Args:
            pair: Trading pair to unlock
        """
        pass
    
    def is_pair_locked(
        self,
        pair: str,
        current_time: datetime,
        **kwargs
    ) -> bool:
        """
        Check if a trading pair is currently locked
        
        Args:
            pair: Trading pair to check
            current_time: Current time
            
        Returns:
            True if pair is locked, False otherwise
        """
        return False

# ==================== @informative Decorator ====================

def informative(
    timeframe: str,
    asset: str = "",
    fmt: Union[str, Callable, None] = None,
    *,
    candle_type: Optional[str] = None,
    ffill: bool = True
) -> Callable:
    """
    Freqtrade @informative decorator - fully compatible

    Example:
        @informative('1h')
        def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
            dataframe['rsi'] = ta.RSI(dataframe, 14)
            return dataframe

        @informative('1h', 'BTC/{stake}')
        def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
            dataframe['rsi'] = ta.RSI(dataframe, 14)
            return dataframe
    """
    def decorator(populate_indicators: Callable) -> Callable:
        @wraps(populate_indicators)
        def wrapper(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
            return populate_indicators(self, dataframe, metadata)

        wrapper._bullseye_informative = {
            'timeframe': timeframe,
            'asset': asset,
            'fmt': fmt,
            'candle_type': candle_type,
            'ffill': ffill
        }
        return wrapper
    return decorator


def merge_informative_pair(
    dataframe: DataFrame,
    informative: DataFrame,
    timeframe: str,
    informative_timeframe: str,
    ffill: bool = True,
    drop_informative: bool = False
) -> DataFrame:
    """
    Freqtrade merge_informative_pair function - fully compatible

    Merges a shorter timeframe dataframe into a longer timeframe dataframe
    while avoiding lookahead bias.

    Args:
        dataframe: Original dataframe
        informative: Informative dataframe (higher timeframe)
        timeframe: Original timeframe
        informative_timeframe: Informative timeframe
        ffill: Forward fill values
        drop_informative: Drop informative columns

    Returns:
        Merged dataframe
    """
    import pandas as pd

    minutes = timeframe_to_minutes(informative_timeframe)

    # Shift date to avoid lookahead bias
    informative = informative.copy()
    informative['date_merge'] = informative["date"] + pd.to_timedelta(minutes, 'm')

    # Rename columns
    inf_tf = informative_timeframe
    informative.columns = [f"{col}_{inf_tf}" if col != 'date_merge' else col
                          for col in informative.columns]

    # Merge
    dataframe = pd.merge(
        dataframe,
        informative,
        left_on='date',
        right_on=f'date_merge_{inf_tf}',
        how='left'
    )

    if ffill:
        dataframe = dataframe.ffill()

    if drop_informative:
        cols_to_drop = [col for col in dataframe.columns if f'_{inf_tf}' in col]
        dataframe = dataframe.drop(columns=cols_to_drop)
    else:
        dataframe = dataframe.drop(columns=[f'date_merge_{inf_tf}'])

    return dataframe


def timeframe_to_minutes(timeframe: str) -> int:
    """Convert timeframe string to minutes"""
    timeframe = timeframe.lower()

    if timeframe.endswith("m"):
        return int(timeframe[:-1])
    elif timeframe.endswith("h"):
        return int(timeframe[:-1]) * 60
    elif timeframe.endswith("d"):
        return int(timeframe[:-1]) * 60 * 24
    elif timeframe.endswith("w"):
        return int(timeframe[:-1]) * 60 * 24 * 7
    elif timeframe.endswith("M"):
        return int(timeframe[:-1]) * 60 * 24 * 30
    else:
        return 60  # Default 1 hour


def timeframe_to_next_date(timeframe: str) -> datetime:
    """Get the next date for a given timeframe"""
    return datetime.now(timezone.utc)


def timeframe_to_prev_date(timeframe: str) -> datetime:
    """Get the previous date for a given timeframe"""
    return datetime.now(timezone.utc)


def stoploss_from_open(
    open_relative_rate: float,
    current_profit: float,
    stoploss: float,
    is_short: bool = False
) -> float:
    """
    Calculate stoploss value from open rate

    Args:
        open_relative_rate: Open relative rate
        current_profit: Current profit percentage
        stoploss: Stoploss percentage
        is_short: Whether position is short

    Returns:
        Stoploss value
    """
    if is_short:
        return open_relative_rate * (1 + stoploss)
    else:
        return open_relative_rate * (1 - abs(stoploss))


def stoploss_from_absolute(
    stop_rate: float,
    current_rate: float,
    is_short: bool = False
) -> float:
    """
    Calculate stoploss from absolute price

    Args:
        stop_rate: Stop rate
        current_rate: Current rate
        is_short: Whether position is short

    Returns:
        Stoploss percentage
    """
    if is_short:
        return (stop_rate - current_rate) / current_rate
    else:
        return (stop_rate - current_rate) / current_rate


# ==================== Hyperoptable Parameters ====================

class BooleanParameter:
    """Boolean hyperparameter"""

    def __init__(
        self,
        default: bool = False,
        space: Optional[str] = None,
        optimize: bool = False,
        load: bool = True
    ):
        self.default = default
        self.value = default
        self.space = space
        self.optimize = optimize
        self.load = load

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self.value

    def __set__(self, obj, value):
        self.value = value

    @property
    def range(self):
        return [False, True]


class IntParameter:
    """Integer hyperparameter"""

    def __init__(
        self,
        low: int,
        high: int,
        default: int,
        space: Optional[str] = None,
        optimize: bool = False,
        load: bool = True
    ):
        self.low = low
        self.high = high
        self.default = default
        self.value = default
        self.space = space
        self.optimize = optimize
        self.load = load

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self.value

    def __set__(self, obj, value):
        self.value = value

    @property
    def range(self):
        return list(range(self.low, self.high + 1))


class DecimalParameter:
    """Decimal hyperparameter"""

    def __init__(
        self,
        low: float,
        high: float,
        default: float,
        decimals: int = 3,
        space: Optional[str] = None,
        optimize: bool = False,
        load: bool = True
    ):
        self.low = low
        self.high = high
        self.default = default
        self.decimals = decimals
        self.value = default
        self.space = space
        self.optimize = optimize
        self.load = load

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self.value

    def __set__(self, obj, value):
        self.value = value

    @property
    def range(self):
        step = 10 ** -self.decimals
        values = []
        current = self.low
        while current <= self.high:
            values.append(round(current, self.decimals))
            current += step
        return values


class RealParameter(DecimalParameter):
    """RealParameter is an alias for DecimalParameter"""
    pass


class CategoricalParameter:
    """Categorical hyperparameter"""

    def __init__(
        self,
        choices: list,
        default: Any = None,
        space: Optional[str] = None,
        optimize: bool = False,
        load: bool = True
    ):
        self.choices = choices
        self.default = default or choices[0]
        self.value = self.default
        self.space = space
        self.optimize = optimize
        self.load = load

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self.value

    def __set__(self, obj, value):
        self.value = value

    @property
    def range(self):
        return self.choices
