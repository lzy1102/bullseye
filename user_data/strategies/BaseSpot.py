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

    # Bollinger early-exit parameters (exit leg only).
    boll_period: int = 20
    boll_std: float = 2.0

    def _boll_on(self) -> bool:
        # Kill-switch for the experiment: set use_boll_exit: false
        # in the config to run the pre-Bollinger baseline.
        cfg = getattr(self, "config", None)
        if isinstance(cfg, dict):
            return bool(cfg.get("use_boll_exit", True))
        return True

    @informative("1d")
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ma20d"] = dataframe["close"].rolling(20).mean()
        dataframe["ma60d"] = dataframe["close"].rolling(60).mean()
        dataframe["trend"] = 0
        dataframe.loc[dataframe["ma20d"] > dataframe["ma60d"], "trend"] = 1
        dataframe.loc[dataframe["ma20d"] < dataframe["ma60d"], "trend"] = -1
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        mid = dataframe["close"].rolling(self.boll_period).mean()
        sd = dataframe["close"].rolling(self.boll_period).std()
        dataframe["bb_lower"] = mid - self.boll_std * sd
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
        last = dataframe.iloc[-1]
        if last["trend_1d"] == -1:
            return "trend_bear"
        if (
            self._boll_on()
            and "bb_lower" in dataframe
            and last["close"] < last["bb_lower"]
        ):
            return "boll_dead"
        return None
