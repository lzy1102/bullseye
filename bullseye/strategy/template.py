"""
Strategy Template Generator - Create strategy files from templates

This module provides functionality to generate strategy template files
compatible with Freqtrade's IStrategy interface.
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


# ==================== Strategy Templates ====================

TEMPLATE_MINIMAL = '''"""
{strategy_name} - Minimal Strategy Template

A minimal strategy template with only essential methods.
"""
from bullseye.strategy import IStrategy
from pandas import DataFrame


class {class_name}(IStrategy):
    """
    {strategy_name} - Minimal Strategy

    A simple strategy template with basic buy/sell logic.
    """

    # Strategy settings
    timeframe = "{timeframe}"
    startup_candle_count = 30

    # Risk management
    stoploss = -0.10

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Add technical indicators to the dataframe.

        Args:
            dataframe: OHLCV dataframe
            metadata: Pair metadata

        Returns:
            DataFrame with indicators
        """
        # Add your indicators here
        # Example: RSI
        # import talib.abstract as ta
        # dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Generate entry signals.

        Args:
            dataframe: DataFrame with indicators
            metadata: Pair metadata

        Returns:
            DataFrame with entry signals
        """
        # Set entry conditions
        # dataframe.loc[
        #     (dataframe['rsi'] < 30) &  # Oversold
        #     (dataframe['volume'] > 0),
        #     'enter_long'
        # ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Generate exit signals.

        Args:
            dataframe: DataFrame with indicators
            metadata: Pair metadata

        Returns:
            DataFrame with exit signals
        """
        # Set exit conditions
        # dataframe.loc[
        #     (dataframe['rsi'] > 70) &  # Overbought
        #     (dataframe['volume'] > 0),
        #     'exit_long'
        # ] = 1

        return dataframe
'''


TEMPLATE_FULL = '''"""
{strategy_name} - Full Strategy Template

A comprehensive strategy template with all common features.
"""
from typing import Dict, Optional
from datetime import datetime

from bullseye.strategy import (
    IStrategy,
    informative,
    IntParameter,
    DecimalParameter,
    BooleanParameter,
)
from pandas import DataFrame
import talib.abstract as ta


class {class_name}(IStrategy):
    """
    {strategy_name} - Full Feature Strategy

    A comprehensive strategy template demonstrating:
    - Multiple indicators
    - Multi-timeframe analysis
    - Hyperoptable parameters
    - Custom exit logic
    """

    # ==================== Strategy Configuration ====================

    # Timeframe
    timeframe = "{timeframe}"
    startup_candle_count = 100

    # Enable shorting (for futures/margin)
    can_short = False

    # Minimal ROI (take profit levels)
    # Format: {"minutes": profit_percentage}
    minimal_roi = {{
        "0": 0.10,    # 10% profit immediately
        "30": 0.05,   # 5% after 30 minutes
        "60": 0.03,   # 3% after 1 hour
        "120": 0.01   # 1% after 2 hours
    }}

    # Stop loss
    stoploss = -0.10  # 10% stop loss

    # Trailing stop
    trailing_stop = False
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = False

    # Order types
    order_types = {{
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }}

    # ==================== Hyperoptable Parameters ====================

    # RSI parameters
    rsi_period = IntParameter(7, 21, default=14, space="buy", optimize=True)
    rsi_buy_threshold = DecimalParameter(20, 40, default=30, space="buy", optimize=True)
    rsi_sell_threshold = DecimalParameter(60, 80, default=70, space="sell", optimize=True)

    # Enable/disable features
    use_rsi = BooleanParameter(default=True, space="buy", optimize=True)

    # ==================== Informative Timeframes ====================

    @informative('1h')
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Add indicators for 1-hour timeframe.

        Higher timeframe indicators help identify the overall trend.
        """
        # EMA trend
        dataframe['ema_50'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema_200'] = ta.EMA(dataframe, timeperiod=200)

        # Trend direction
        dataframe['uptrend'] = dataframe['ema_50'] > dataframe['ema_200']

        return dataframe

    # ==================== Main Indicators ====================

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Add technical indicators to the dataframe.

        This method is called once per candle for each pair.
        """
        # RSI
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=self.rsi_period.value)

        # MACD
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']

        # Bollinger Bands
        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2, nbdevdn=2)
        dataframe['bb_lowerband'] = bollinger['lowerband']
        dataframe['bb_middleband'] = bollinger['middleband']
        dataframe['bb_upperband'] = bollinger['upperband']
        dataframe['bb_percent'] = (
            (dataframe['close'] - dataframe['bb_lowerband']) /
            (dataframe['bb_upperband'] - dataframe['bb_lowerband'])
        )

        # EMA
        dataframe['ema_9'] = ta.EMA(dataframe, timeperiod=9)
        dataframe['ema_21'] = ta.EMA(dataframe, timeperiod=21)

        # Volume
        dataframe['volume_mean'] = dataframe['volume'].rolling(20).mean()

        return dataframe

    # ==================== Entry Signals ====================

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Generate long entry signals.

        Conditions are combined with AND logic.
        """
        conditions_long = []

        # RSI oversold
        if self.use_rsi.value:
            conditions_long.append(dataframe['rsi'] < self.rsi_buy_threshold.value)

        # Price above EMA (trend following)
        conditions_long.append(dataframe['close'] > dataframe['ema_21'])

        # Higher timeframe uptrend
        conditions_long.append(dataframe['uptrend_1h'] == True)

        # MACD bullish
        conditions_long.append(dataframe['macd'] > dataframe['macdsignal'])

        # Volume confirmation
        conditions_long.append(dataframe['volume'] > 0)

        # Combine conditions
        if conditions_long:
            dataframe.loc[
                (conditions_long[0]) if len(conditions_long) == 1
                else conditions_long[0] & conditions_long[1],
                'enter_long'
            ] = 1
            # For multiple conditions:
            # dataframe.loc[
            #     reduce(lambda x, y: x & y, conditions_long),
            #     'enter_long'
            # ] = 1

        return dataframe

    # ==================== Exit Signals ====================

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Generate long exit signals.
        """
        conditions_exit = []

        # RSI overbought
        if self.use_rsi.value:
            conditions_exit.append(dataframe['rsi'] > self.rsi_sell_threshold.value)

        # Price below EMA
        conditions_exit.append(dataframe['close'] < dataframe['ema_9'])

        # MACD bearish
        conditions_exit.append(dataframe['macd'] < dataframe['macdsignal'])

        # Volume confirmation
        conditions_exit.append(dataframe['volume'] > 0)

        # Combine conditions
        if conditions_exit:
            dataframe.loc[
                conditions_exit[0],
                'exit_long'
            ] = 1

        return dataframe

    # ==================== Custom Methods ====================

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
        Custom exit logic.

        Returns exit reason string or None to not exit.
        """
        # Exit if profit > 5% after holding for 1 hour
        if current_profit > 0.05:
            hold_time = (current_time - trade.open_date_utc).total_seconds() / 3600
            if hold_time > 1:
                return 'profit_5pct_1h'

        # Exit on strong reversal
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe) > 0:
            last_candle = dataframe.iloc[-1]
            if last_candle['rsi'] > 80:
                return 'rsi_overbought'

        return None

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
        """
        Called right before placing a entry order.

        Use this to add extra confirmation logic.
        """
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
        """
        Called right before placing a exit order.

        Use this to add extra confirmation logic.
        """
        return True
'''


TEMPLATE_ADVANCED = '''"""
{strategy_name} - Advanced Strategy Template

An advanced strategy template with all features including:
- Multi-timeframe analysis
- Position adjustment (DCA)
- Custom stop loss
- Market regime detection
- Advanced risk management
"""
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timezone
from functools import reduce

from bullseye.strategy import (
    IStrategy,
    informative,
    merge_informative_pair,
    IntParameter,
    DecimalParameter,
    BooleanParameter,
    CategoricalParameter,
    stoploss_from_open,
)
from pandas import DataFrame
import talib.abstract as ta
import numpy as np


class {class_name}(IStrategy):
    """
    {strategy_name} - Advanced Strategy

    A feature-rich strategy demonstrating all Bullseye capabilities.
    """

    # ==================== Strategy Configuration ====================

    INTERFACE_VERSION = 3

    timeframe = "{timeframe}"
    startup_candle_count = 200
    can_short = True  # Enable shorting

    # Position adjustment (DCA)
    position_adjustment_enable = True
    max_entry_position_adjustment = 3  # Max 3 additional entries

    # Risk management
    minimal_roi = {{
        "0": 0.15,
        "30": 0.10,
        "60": 0.05,
        "120": 0.03,
        "240": 0.01
    }}

    stoploss = -0.15

    # Trailing stop
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    # Exit signal settings
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # Order configuration
    order_types = {{
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
        "stoploss_on_exchange_interval": 60,
    }}

    order_time_in_force = {{
        "entry": "GTC",
        "exit": "GTC",
    }}

    # ==================== Hyperoptable Parameters ====================

    # Entry parameters
    entry_rsi_period = IntParameter(7, 21, default=14, space="buy", optimize=True)
    entry_rsi_lower = DecimalParameter(20, 40, default=30, space="buy", optimize=True)
    entry_rsi_upper = DecimalParameter(60, 80, default=70, space="sell", optimize=True)

    # EMA parameters
    ema_short = IntParameter(5, 15, default=9, space="buy", optimize=True)
    ema_long = IntParameter(20, 35, default=21, space="buy", optimize=True)

    # Risk parameters
    stoploss_pct = DecimalParameter(-0.20, -0.05, default=-0.10, space="sell", optimize=True)

    # Feature toggles
    use_macd = BooleanParameter(default=True, space="buy", optimize=True)
    use_bb = BooleanParameter(default=True, space="buy", optimize=True)
    use_volume = BooleanParameter(default=True, space="buy", optimize=True)

    # Strategy variant
    strategy_variant = CategoricalParameter(
        ["trend_follow", "mean_reversion", "breakout"],
        default="trend_follow",
        space="buy",
        optimize=True
    )

    # ==================== Informative Timeframes ====================

    @informative('4h')
    def populate_indicators_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Higher timeframe trend analysis"""
        dataframe['ema_50'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema_200'] = ta.EMA(dataframe, timeperiod=200)
        dataframe['trend'] = np.where(
            dataframe['ema_50'] > dataframe['ema_200'], 1, -1
        )
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        return dataframe

    @informative('1h')
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Medium timeframe momentum"""
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['macd'] = ta.MACD(dataframe)['macd']
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

    # ==================== Main Indicators ====================

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Add all technical indicators"""

        # Trend indicators
        dataframe['ema_short'] = ta.EMA(dataframe, timeperiod=self.ema_short.value)
        dataframe['ema_long'] = ta.EMA(dataframe, timeperiod=self.ema_long.value)

        # Momentum indicators
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=self.entry_rsi_period.value)

        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']

        # Volatility indicators
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)

        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe['bb_lower'] = bollinger['lowerband']
        dataframe['bb_middle'] = bollinger['middleband']
        dataframe['bb_upper'] = bollinger['upperband']
        dataframe['bb_width'] = (
            (dataframe['bb_upper'] - dataframe['bb_lower']) / dataframe['bb_middle']
        )
        dataframe['bb_percent'] = (
            (dataframe['close'] - dataframe['bb_lower']) /
            (dataframe['bb_upper'] - dataframe['bb_lower'])
        )

        # Trend strength
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['plus_di'] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe, timeperiod=14)

        # Volume indicators
        dataframe['volume_mean'] = dataframe['volume'].rolling(20).mean()
        dataframe['volume_ratio'] = dataframe['volume'] / dataframe['volume_mean']

        # Market regime detection
        dataframe['regime'] = self._detect_regime(dataframe)

        # Support/Resistance levels
        dataframe = self._add_sr_levels(dataframe)

        return dataframe

    def _detect_regime(self, dataframe: DataFrame) -> DataFrame:
        """Detect market regime (trending/ranging)"""
        # Use ADX for regime detection
        regime = np.where(dataframe['adx'] > 25, 1, 0)  # 1 = trending, 0 = ranging
        return regime

    def _add_sr_levels(self, dataframe: DataFrame) -> DataFrame:
        """Add support/resistance levels"""
        # Simple pivot-based S/R
        dataframe['support'] = dataframe['low'].rolling(20).min()
        dataframe['resistance'] = dataframe['high'].rolling(20).max()
        return dataframe

    # ==================== Entry Signals ====================

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Generate entry signals based on strategy variant"""

        if self.strategy_variant.value == "trend_follow":
            dataframe = self._trend_follow_entry(dataframe)
        elif self.strategy_variant.value == "mean_reversion":
            dataframe = self._mean_reversion_entry(dataframe)
        elif self.strategy_variant.value == "breakout":
            dataframe = self._breakout_entry(dataframe)

        return dataframe

    def _trend_follow_entry(self, dataframe: DataFrame) -> DataFrame:
        """Trend following entry logic"""
        # Long conditions
        conditions_long = [
            dataframe['trend_4h'] == 1,  # Higher timeframe uptrend
            dataframe['close'] > dataframe['ema_short'],
            dataframe['ema_short'] > dataframe['ema_long'],
            dataframe['rsi'] < self.entry_rsi_upper.value,
            dataframe['volume'] > 0,
        ]

        dataframe.loc[
            reduce(lambda x, y: x & y, conditions_long),
            'enter_long'
        ] = 1

        # Short conditions
        conditions_short = [
            dataframe['trend_4h'] == -1,  # Higher timeframe downtrend
            dataframe['close'] < dataframe['ema_short'],
            dataframe['ema_short'] < dataframe['ema_long'],
            dataframe['rsi'] > self.entry_rsi_lower.value,
            dataframe['volume'] > 0,
        ]

        dataframe.loc[
            reduce(lambda x, y: x & y, conditions_short),
            'enter_short'
        ] = 1

        return dataframe

    def _mean_reversion_entry(self, dataframe: DataFrame) -> DataFrame:
        """Mean reversion entry logic"""
        # Long conditions - oversold
        conditions_long = [
            dataframe['bb_percent'] < 0.2,  # Near lower BB
            dataframe['rsi'] < self.entry_rsi_lower.value,
            dataframe['trend_4h'] == 1,  # Still in higher timeframe uptrend
            dataframe['volume'] > 0,
        ]

        dataframe.loc[
            reduce(lambda x, y: x & y, conditions_long),
            'enter_long'
        ] = 1

        # Short conditions - overbought
        conditions_short = [
            dataframe['bb_percent'] > 0.8,  # Near upper BB
            dataframe['rsi'] > self.entry_rsi_upper.value,
            dataframe['trend_4h'] == -1,  # Still in higher timeframe downtrend
            dataframe['volume'] > 0,
        ]

        dataframe.loc[
            reduce(lambda x, y: x & y, conditions_short),
            'enter_short'
        ] = 1

        return dataframe

    def _breakout_entry(self, dataframe: DataFrame) -> DataFrame:
        """Breakout entry logic"""
        # Long conditions - resistance breakout
        conditions_long = [
            dataframe['close'] > dataframe['resistance'].shift(1),
            dataframe['volume_ratio'] > 1.5,  # High volume
            dataframe['adx'] > 20,  # Trend strength
            dataframe['volume'] > 0,
        ]

        dataframe.loc[
            reduce(lambda x, y: x & y, conditions_long),
            'enter_long'
        ] = 1

        # Short conditions - support breakdown
        conditions_short = [
            dataframe['close'] < dataframe['support'].shift(1),
            dataframe['volume_ratio'] > 1.5,
            dataframe['adx'] > 20,
            dataframe['volume'] > 0,
        ]

        dataframe.loc[
            reduce(lambda x, y: x & y, conditions_short),
            'enter_short'
        ] = 1

        return dataframe

    # ==================== Exit Signals ====================

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Generate exit signals"""
        # Long exit
        conditions_exit_long = [
            dataframe['rsi'] > 75,
            dataframe['close'] < dataframe['ema_short'],
            dataframe['volume'] > 0,
        ]

        dataframe.loc[
            reduce(lambda x, y: x & y, conditions_exit_long),
            'exit_long'
        ] = 1

        # Short exit
        conditions_exit_short = [
            dataframe['rsi'] < 25,
            dataframe['close'] > dataframe['ema_short'],
            dataframe['volume'] > 0,
        ]

        dataframe.loc[
            reduce(lambda x, y: x & y, conditions_exit_short),
            'exit_short'
        ] = 1

        return dataframe

    # ==================== Position Adjustment (DCA) ====================

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
        Adjust position - add to winning/losing positions.

        Returns stake amount for additional position or None.
        """
        # Only add to positions that are losing
        if current_profit < -0.05:  # Down 5%
            # Add 50% of original stake
            return trade.stake_amount * 0.5

        return None

    # ==================== Custom Methods ====================

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
        """Custom exit logic"""
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

        if len(dataframe) < 1:
            return None

        last_candle = dataframe.iloc[-1]

        # Exit on extreme overbought/oversold
        if trade.is_short:
            if last_candle['rsi'] < 30:
                return 'rsi_oversold_exit_short'
        else:
            if last_candle['rsi'] > 70:
                return 'rsi_overbought_exit_long'

        # Exit on trend reversal
        if trade.is_short:
            if last_candle['trend_4h'] == 1:
                return 'trend_reversal_exit_short'
        else:
            if last_candle['trend_4h'] == -1:
                return 'trend_reversal_exit_long'

        return None

    def custom_stoploss(
        self,
        pair: str,
        trade: 'Trade',
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs
    ) -> Optional[float]:
        """
        Custom stop loss.

        Returns stop loss value or None for default.
        """
        # Tighten stop loss when profitable
        if current_profit > 0.05:
            return stoploss_from_open(0.02, current_profit, self.stoploss_pct.value)

        return None

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs
    ) -> float:
        """Custom leverage for futures trading"""
        # Use lower leverage in ranging markets
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe) > 0:
            last_candle = dataframe.iloc[-1]
            if last_candle['regime'] == 0:  # Ranging market
                return min(proposed_leverage, 2.0)

        return proposed_leverage

    # ==================== Trade Confirmation ====================

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
        """Confirm trade entry"""
        # Add extra validation here
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
        """Confirm trade exit"""
        return True

    # ==================== Bot Lifecycle ====================

    def bot_start(self, **kwargs) -> None:
        """Called when bot starts"""
        self.logger.info(f"{{self.__class__.__name__}} strategy started")

    def bot_loop_start(self, **kwargs) -> None:
        """Called at the start of each bot loop"""
        pass
'''


# Template mapping
TEMPLATES = {
    "minimal": TEMPLATE_MINIMAL,
    "full": TEMPLATE_FULL,
    "advanced": TEMPLATE_ADVANCED,
}


def create_strategy_template(
    strategy_name: str,
    template: str = "full",
    output_dir: Optional[str] = None,
    timeframe: str = "5m",
) -> str:
    """
    Create a new strategy file from template.

    Args:
        strategy_name: Name of the strategy (will be used as class name)
        template: Template type (minimal, full, advanced)
        output_dir: Output directory (default: user_data/strategies)
        timeframe: Default timeframe for the strategy

    Returns:
        Path to the created file
    """
    # Validate strategy name
    if not strategy_name:
        raise ValueError("Strategy name is required")

    # Sanitize strategy name for class (keep original case for first letter)
    # Convert my_strategy or MyStrategy to MyStrategy
    parts = strategy_name.replace("-", "_").split("_")
    class_name = "".join(word.capitalize() for word in parts)
    if not class_name[0].isalpha():
        class_name = "Strategy" + class_name

    # Get template
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template: {template}. Available: {list(TEMPLATES.keys())}")

    template_content = TEMPLATES[template]

    # Generate content
    content = template_content.format(
        strategy_name=strategy_name,
        class_name=class_name,
        timeframe=timeframe,
    )

    # Determine output path
    if output_dir is None:
        output_dir = "user_data/strategies"

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    file_path = output_path / f"{strategy_name}.py"

    # Check if file exists
    if file_path.exists():
        raise FileExistsError(f"Strategy file already exists: {file_path}")

    # Write file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    logger.info(f"Created strategy file: {file_path}")
    return str(file_path)


def list_available_templates() -> Dict[str, str]:
    """
    List available strategy templates.

    Returns:
        Dictionary of template name -> description
    """
    return {
        "minimal": "Minimal template with only essential methods (RSI example)",
        "full": "Full template with indicators, multi-timeframe, hyperopt parameters",
        "advanced": "Advanced template with DCA, custom stoploss, market regime detection",
    }
