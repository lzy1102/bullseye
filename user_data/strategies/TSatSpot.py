"""
TSatSpot - satellite T leg of the base+T prototype.

5m mean-reversion around a core position that this leg assumes exists:
only trades while the daily trend is up (same SMA20/SMA60 1d gate as
BaseSpot). Buys 2% dips below the 5m SMA20, sells on reversion to the
mean with a hard -2% stoploss, and never holds overnight: anything
not reverted is closed before the close. Entries stop after 14:30 so
a satellite always has room to revert. No DCA, no ROI; the daily gate
going bear also clears any open satellite. Intended blend:
70% BaseSpot / 30% TSatSpot.
"""
import pandas as pd
from bullseye.strategy import IStrategy, informative
from pandas import DataFrame


class TSatSpot(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = -0.02
    trailing_stop = False

    position_adjustment_enable = False

    # Dip depth below the 5m SMA20 that opens a satellite T.
    dip_dev: float = 0.02
    # No new satellites after this time (a T needs room to revert).
    entry_cutoff_hour: int = 14
    entry_cutoff_minute: int = 30

    @informative("1d")
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ma20d"] = dataframe["close"].rolling(20).mean()
        dataframe["ma60d"] = dataframe["close"].rolling(60).mean()
        dataframe["trend"] = 0
        dataframe.loc[dataframe["ma20d"] > dataframe["ma60d"], "trend"] = 1
        dataframe.loc[dataframe["ma20d"] < dataframe["ma60d"], "trend"] = -1
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ma20_5m"] = dataframe["close"].rolling(20).mean()
        dataframe["lower_5m"] = dataframe["ma20_5m"] * (1 - self.dip_dev)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        gate = (
            dataframe["trend_1d"].fillna(0) == 1
            if "trend_1d" in dataframe
            else False
        )
        below = dataframe["close"] < dataframe["lower_5m"]
        was_above = (
            dataframe["close"].shift(1) >= dataframe["lower_5m"].shift(1)
        ).fillna(False)
        cutoff = (
            self.entry_cutoff_hour * 60 + self.entry_cutoff_minute
        )
        daytime = dataframe["date"].dt.hour * 60 + dataframe["date"].dt.minute
        dataframe.loc[
            (
                gate
                & below
                & was_above
                & (daytime < cutoff)
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "sat_t")
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
        last = dataframe.iloc[-1]
        if "trend_1d" in dataframe and last["trend_1d"] == -1:
            return "gate_off"
        if "ma20_5m" in dataframe and last["close"] >= last["ma20_5m"]:
            return "sat_reverted"
        # Same-day discipline: never hold a satellite overnight.
        try:
            if pd.to_datetime(trade.open_date).date() < pd.to_datetime(
                current_time
            ).date():
                return "eod_close"
        except (TypeError, ValueError, AttributeError):
            pass
        return None
