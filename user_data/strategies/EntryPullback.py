"""
EntryPullback - buy the retest: breakout then pullback to the level.

Entry (tag 'bo_pullback'): a fresh 20-day-high breakout fired within the
last 15 bars, and today's close is back near that level
(0.98x..1.03x). No volume filter, no wave structure: pure price.

Exit: MA20 < MA60 (death cross). No ROI/stoploss/DCA.
"""
import numpy as np
import pandas as pd
from bullseye.strategy import IStrategy
from pandas import DataFrame


class EntryPullback(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    break_window: int = 20
    max_wait: int = 15
    band_lo: float = 0.98
    band_hi: float = 1.03

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        dataframe["ma20"] = close.rolling(20).mean()
        dataframe["ma60"] = close.rolling(60).mean()
        hh = dataframe["high"].shift(1).rolling(self.break_window).max()
        dataframe["bo_level"] = hh
        broke = (
            (close > hh) & (close.shift(1) <= hh.shift(1))
        ).fillna(False)
        idx = np.arange(len(dataframe))
        bo_idx = pd.Series(idx, index=dataframe.index).where(broke).ffill()
        dataframe["bo_age"] = idx - bo_idx
        dataframe["bo_lv"] = hh.where(broke).ffill()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        in_band = (
            (dataframe["close"] >= dataframe["bo_lv"] * self.band_lo)
            & (dataframe["close"] <= dataframe["bo_lv"] * self.band_hi)
        )
        dataframe.loc[
            (
                (dataframe["bo_age"] >= 1)
                & (dataframe["bo_age"] <= self.max_wait)
                & in_band.fillna(False)
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "bo_pullback")
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
