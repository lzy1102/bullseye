"""
RSIPlain - textbook RSI mean reversion, no filters.

Entry: RSI(14) crosses below 30 (fresh oversold).
Exit: RSI(14) crosses above 70 (fresh overbought).
No gate, no DCA, no ROI, no stoploss: isolates the indicator itself.
"""
from bullseye.strategy import IStrategy
from pandas import DataFrame


class RSIPlain(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    rsi_period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        delta = dataframe["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / self.rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / self.rsi_period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, float("nan"))
        dataframe["rsi"] = (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cross_down = (
            (dataframe["rsi"] < self.oversold)
            & (dataframe["rsi"].shift(1) >= self.oversold)
        ).fillna(False)
        dataframe.loc[
            (cross_down & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "rsi_oversold")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cross_up = (
            (dataframe["rsi"] > self.overbought)
            & (dataframe["rsi"].shift(1) <= self.overbought)
        ).fillna(False)
        dataframe.loc[
            (cross_up & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "rsi_overbought")
        return dataframe
