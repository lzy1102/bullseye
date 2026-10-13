"""RSIExitSmart - three-branch exits after heat (long only).

Experiment: after RSI exceeds `overbought`, do not sell immediately.
- Branch A, blowoff (tag 'blowoff_top'): fresh 20-day high on
  >= `blowoff_vol`x average volume while still hot (rsi > line).
  天量天价 = profit-taking flood, outlook poor -> sell now.
- Branch B, stall (tag 'stall_exit'): hot within the last
  `heat_window` bars but NO fresh 20-day high in the last
  `stall_days` bars (pulled back / stopped making highs / chopping).
- Branch C, continuation: still making new highs on normal volume
  -> hold (no signal).

Entry inherited from RSIConfirmExit (== RSIConfirm entries).
No gate, no DCA, no ROI, no stoploss: isolates the exit effect.
"""
import pandas as pd
from pandas import DataFrame

try:
    from RSIConfirmExit import RSIConfirmExit, _int
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.RSIConfirmExit import RSIConfirmExit, _int


class RSIExitSmart(RSIConfirmExit):
    INTERFACE_VERSION = 3

    # Remember heat this far back (bars).
    heat_window: int = 10
    # Fresh-high lookback for the blowoff level (bars).
    newhigh_window: int = 20
    # 天量 threshold (x prior-20d mean volume).
    blowoff_vol: float = 2.0
    # Stall = no fresh high this many bars.
    stall_days: int = 3

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        ob = _int(self.overbought)
        hot = (dataframe["rsi"] > ob).fillna(False)
        dataframe["hot_recent"] = (
            hot.rolling(self.heat_window, min_periods=1).max() == 1
        )
        hh = dataframe["close"].shift(1).rolling(self.newhigh_window).max()
        dataframe["new_high"] = (dataframe["close"] > hh).fillna(False)
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ob = _int(self.overbought)
        hot_now = (dataframe["rsi"] > ob).fillna(False)
        blowoff = (
            dataframe["new_high"]
            & (dataframe["vol_ratio"] > self.blowoff_vol)
            & hot_now
            & (dataframe["volume"] > 0)
        ).fillna(False)
        no_high = (
            dataframe["new_high"].rolling(self.stall_days).sum() == 0
        ).fillna(False)
        stall = (
            dataframe["hot_recent"]
            & no_high
            & (dataframe["volume"] > 0)
        ).fillna(False)
        dataframe.loc[blowoff, ["exit_long", "exit_tag"]] = (1, "blowoff_top")
        dataframe.loc[
            stall & (dataframe["exit_long"] != 1), ["exit_long", "exit_tag"]
        ] = (1, "stall_exit")
        return dataframe
