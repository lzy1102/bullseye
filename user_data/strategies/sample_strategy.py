"""
Sample Strategy - Freqtrade compatible example strategy

This strategy demonstrates the 100% compatibility with Freqtrade.
You can use it directly with Bullseye or Freqtrade without any modifications.
"""
from bullseye.strategy import (
    IStrategy, informative, merge_informative_pair,
    IntParameter, DecimalParameter, BooleanParameter
)
from pandas import DataFrame
import talib.abstract as ta


class SampleStrategy(IStrategy):
    """
    Sample Strategy - Freqtrade Compatible

    This is a sample strategy that demonstrates Bullseye's compatibility
    with Freqtrade's strategy interface.

    Strategy Logic:
    - Buy when RSI is below 30 (oversold)
    - Sell when RSI is above 70 (overbought)
    - Use EMA20 as trend filter
    """

    # ==================== Strategy Settings ====================
    timeframe = '5m'
    startup_candle_count = 30
    can_short = False

    # ROI settings
    minimal_roi = {
        "0": 0.05,
        "30": 0.03,
        "60": 0.01,
        "120": 0.00
    }

    # Stoploss
    stoploss = -0.10

    # Trailing stop
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = False

    # ==================== Hyperoptable Parameters ====================
    # RSI threshold parameters
    buy_rsi = IntParameter(low=20, high=40, default=30, space="buy", optimize=True)
    sell_rsi = IntParameter(low=60, high=80, default=70, space="sell", optimize=True)

    # EMA period
    ema_period = IntParameter(low=10, high=50, default=20, space="buy", optimize=True)

    # ==================== Informative Pairs ====================
    def informative_pairs(self):
        """
        Define additional pairs for analysis

        Returns:
            List of (pair, timeframe) tuples
        """
        return [
            ("ETH/USDT", "1h"),
            ("BTC/USDT", "1h"),
        ]

    # ==================== Indicators ====================
    @informative('1h')
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Populate indicators for 1h timeframe

        This will be available in the main dataframe as rsi_1h, ema_1h, etc.
        """
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['ema'] = ta.EMA(dataframe, timeperiod=self.ema_period.value)
        return dataframe

    @informative('1h', 'BTC/{stake}')
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Populate indicators for BTC/USDT 1h timeframe

        This will be available as btc_rsi_1h, btc_ema_1h, etc.
        """
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['ema'] = ta.EMA(dataframe, timeperiod=20)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Populate indicators for the main timeframe

        Args:
            dataframe: OHLCV dataframe
            metadata: Additional info (contains pair, etc.)

        Returns:
            Dataframe with indicators added
        """
        # RSI
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)

        # EMA
        dataframe['ema20'] = ta.EMA(dataframe, timeperiod=self.ema_period.value)
        dataframe['ema50'] = ta.EMA(dataframe, timeperiod=50)

        # Volume moving average
        dataframe['volume_mean'] = dataframe['volume'].rolling(window=20).mean()

        return dataframe

    # ==================== Entry Trend ====================
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Populate entry signals

        Sets the 'enter_long' column to 1 for entry signals.
        Can also set 'enter_tag' to label the entry reason.

        Args:
            dataframe: Dataframe with indicators
            metadata: Additional info

        Returns:
            Dataframe with entry signals
        """
        # Get stake currency for dynamic column naming
        stake = self.config.get('stake_currency', 'USDT')

        # Entry conditions:
        # 1. RSI crosses below buy_rsi threshold
        # 2. Price is above EMA20 (uptrend)
        # 3. Volume is above average
        # 4. Optional: BTC 1h RSI is also low (market-wide oversold)
        dataframe.loc[
            (
                (dataframe['rsi'] < self.buy_rsi.value) &  # RSI oversold
                (dataframe['close'] > dataframe['ema20']) &  # Uptrend
                (dataframe['volume'] > dataframe['volume_mean']) &  # Sufficient volume
                (dataframe['volume'] > 0)  # Ensure volume exists
            ),
            ['enter_long', 'enter_tag']
        ] = (1, 'rsi_oversold')

        # Optional: Use BTC 1h RSI as additional filter
        if f'btc_{stake}_rsi_1h' in dataframe.columns:
            dataframe.loc[
                (
                    (dataframe['rsi'] < self.buy_rsi.value) &
                    (dataframe['close'] > dataframe['ema20']) &
                    (dataframe[f'btc_{stake}_rsi_1h'] < 40) &  # BTC also oversold
                    (dataframe['volume'] > 0)
                ),
                ['enter_long', 'enter_tag']
            ] = (1, 'rsi_oversold_btc_confirmed')

        return dataframe

    # ==================== Exit Trend ====================
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Populate exit signals

        Sets the 'exit_long' column to 1 for exit signals.
        Can also set 'exit_tag' to label the exit reason.

        Args:
            dataframe: Dataframe with indicators
            metadata: Additional info

        Returns:
            Dataframe with exit signals
        """
        # Exit conditions:
        # 1. RSI crosses above sell_rsi threshold
        # 2. Volume is positive
        dataframe.loc[
            (
                (dataframe['rsi'] > self.sell_rsi.value) &  # RSI overbought
                (dataframe['volume'] > 0)  # Ensure volume exists
            ),
            ['exit_long', 'exit_tag']
        ] = (1, 'rsi_overbought')

        # Additional exit: Price crosses below EMA20
        dataframe.loc[
            (
                (dataframe['close'] < dataframe['ema20']) &
                (dataframe['volume'] > 0)
            ),
            ['exit_long', 'exit_tag']
        ] = (1, 'trend_reversal')

        return dataframe

    # ==================== Optional Callbacks ====================

    def bot_start(self, **kwargs):
        """
        Called when bot starts

        Can be used for initialization or sending notifications.
        """
        self.dp.send_msg(f"SampleStrategy bot started!")

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time,
        entry_tag: Optional[str],
        side: str,
        **kwargs
    ) -> bool:
        """
        Confirm trade entry before placing order

        Return False here to reject an entry.
        """
        return True

    def confirm_trade_exit(
        self,
        pair: str,
        trade,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time,
        **kwargs
    ) -> bool:
        """
        Confirm trade exit before placing order

        Return False here to reject an exit.
        """
        return True

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        exit_reason: str,
        **kwargs
    ) -> Optional[str]:
        """
        Custom exit logic

        Return a string here to exit with a custom reason.
        Return None to use the normal exit logic.
        """
        # Example: Exit if profit exceeds 10%
        if current_profit > 0.10:
            return "high_profit"

        return None
