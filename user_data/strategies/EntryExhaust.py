"""
EntryExhaust - buy the base: N days without a new low + sideways range.

Entry (tag 'exhaust_base'): lowest low of the last 5 days is NOT lower
than the 5 days before that (selling exhausted), AND the 10-day
high-low range is < 8% of close (chopping sideways, not trending).
Fires on the first bar both hold.

Exit: MA20 < MA60 (death cross). No ROI/stoploss/DCA.
"""
from bullseye.strategy import IStrategy
from pandas import DataFrame


class EntryExhaust(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    lookback: int = 5
    range_window: int = 10
    range_pct: float = 0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        low = dataframe["low"]
        high = dataframe["high"]
        close = dataframe["close"]
        dataframe["ma20"] = close.rolling(20).mean()
        dataframe["ma60"] = close.rolling(60).mean()
        lb = int(self.lookback)
        lowest_now = low.rolling(lb).min()
        lowest_prev = low.shift(lb).rolling(lb).min()
        no_new_low = lowest_now >= lowest_prev
        rw = int(self.range_window)
        rng = (high.rolling(rw).max() - low.rolling(rw).min()) / close
        sideways = rng < self.range_pct
        dataframe["setup"] = (no_new_low.fillna(False)
                               & sideways.fillna(False))
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        fresh = dataframe["setup"] & (~dataframe["setup"].shift(1).fillna(False))
        dataframe.loc[
            (fresh & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "exhaust_base")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["ma20"] < dataframe["ma60"])
                & (dataframe["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "trend_bear")
        return dataframe
