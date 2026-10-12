"""
RSIPlain - textbook RSI mean reversion, no filters.

Entry: RSI(14) crosses below 30 (fresh oversold).
Exit: RSI(14) crosses above 70 (fresh overbought).
No gate, no DCA, no ROI, no stoploss: isolates the indicator itself.
"""
from bullseye.strategy import IntParameter, IStrategy
from pandas import DataFrame


def _int(value) -> int:
    """Unwrap hyperopt parameters on old and new engines."""
    return int(getattr(value, "value", value))


class RSIPlain(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    rsi_period = IntParameter(7, 21, default=14, space="buy", optimize=True)
    oversold = IntParameter(15, 40, default=30, space="buy", optimize=True)
    overbought = IntParameter(60, 85, default=70, space="buy", optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        period = _int(self.rsi_period)
        delta = dataframe["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, float("nan"))
        dataframe["rsi"] = (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        os_ = _int(self.oversold)
        cross_down = (
            (dataframe["rsi"] < os_)
            & (dataframe["rsi"].shift(1) >= os_)
        ).fillna(False)
        dataframe.loc[
            (cross_down & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "rsi_oversold")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ob = _int(self.overbought)
        cross_up = (
            (dataframe["rsi"] > ob)
            & (dataframe["rsi"].shift(1) <= ob)
        ).fillna(False)
        dataframe.loc[
            (cross_up & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "rsi_overbought")
        return dataframe
