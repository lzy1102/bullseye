"""
MyTestStrategy - Minimal Strategy Template

A minimal strategy template with only essential methods.
"""
from bullseye.strategy import IStrategy
from pandas import DataFrame


class Myteststrategy(IStrategy):
    """
    MyTestStrategy - Minimal Strategy

    A simple strategy template with basic buy/sell logic.
    """

    # Strategy settings
    timeframe = "5m"
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
