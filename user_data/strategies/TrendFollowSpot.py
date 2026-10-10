"""
TrendFollowSpot - pure single-timeframe trend following (long only).

Split out from the mixed TrendGrid port: this file does trend only,
GridBank10 does grid only. No informative dependency, no DCA.

- Entry: 30m MA10/20 alignment flips sideways/bear -> bull (0 -> 1).
- Exit: alignment flips to bear (-1), any profit or loss.
- Safety: engine stoploss -0.08 (trend flips can arrive late).
- No ROI / trailing / DCA.
"""
from pandas import DataFrame

from bullseye.strategy import DecimalParameter, IntParameter, IStrategy


def _int(value) -> int:
    """Unwrap hyperopt parameters on old and new engines."""
    return int(getattr(value, "value", value))


def _float(value) -> float:
    """Unwrap hyperopt parameters on old and new engines."""
    return float(getattr(value, "value", value))


class TrendFollowSpot(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "30m"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = -0.08
    trailing_stop = False

    position_adjustment_enable = False

    mam_fast = IntParameter(5, 20, default=10, space="buy", optimize=True)
    mam_slow = IntParameter(15, 40, default=20, space="buy", optimize=True)
    gap = DecimalParameter(0.001, 0.010, default=0.003, space="buy",
                           optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        fast = _int(self.mam_fast)
        slow = _int(self.mam_slow)
        if slow <= fast:
            slow = fast + 1
        dataframe["mam_10"] = dataframe["close"].rolling(fast).mean()
        dataframe["mam_20"] = dataframe["close"].rolling(slow).mean()
        gap = _float(self.gap)
        bull = (dataframe["mam_10"] > dataframe["mam_20"] * (1 + gap))
        bear = (dataframe["mam_10"] < dataframe["mam_20"] * (1 - gap))
        dataframe["trend"] = 0
        dataframe.loc[bull, "trend"] = 1
        dataframe.loc[bear, "trend"] = -1
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        prev = dataframe["trend"].shift(1).fillna(0)
        dataframe.loc[
            (
                (dataframe["trend"] == 1)
                & (prev == 0)
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "trend_flip_long")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None
        if dataframe["trend"].iloc[-1] == -1:
            return "trend_reversed"
        return None
