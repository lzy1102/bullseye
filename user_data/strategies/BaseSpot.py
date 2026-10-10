"""
BaseSpot - base position leg of the base+T prototype.

Holds a long base position while the daily trend is up
(SMA20 > SMA60 on 1d via @informative), exits when the daily trend
turns bear. No DCA, no ROI, no stoploss: the daily gate is the only
risk control. Intended to run alongside TSatSpot (satellite T leg);
blend 70% base / 30% satellite by return.
"""
from bullseye.strategy import IStrategy, informative
from pandas import DataFrame


class BaseSpot(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    @informative("1d")
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ma20d"] = dataframe["close"].rolling(20).mean()
        dataframe["ma60d"] = dataframe["close"].rolling(60).mean()
        dataframe["trend"] = 0
        dataframe.loc[dataframe["ma20d"] > dataframe["ma60d"], "trend"] = 1
        dataframe.loc[dataframe["ma20d"] < dataframe["ma60d"], "trend"] = -1
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if "trend_1d" in dataframe:
            t = dataframe["trend_1d"].fillna(0)
        else:
            t = 0
        prev = t.shift(1).fillna(0) if hasattr(t, "shift") else 0
        dataframe.loc[
            (
                (t == 1)
                & (prev != 1)
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "base")
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
        if "trend_1d" not in dataframe:
            return None
        if dataframe["trend_1d"].iloc[-1] == -1:
            return "trend_bear"
        return None
