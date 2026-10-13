"""RSIIntraKDJ - daily RSI regime, intraday KDJ cross timing (long only).

Design: 1d informative decides WHETHER (same buy_sig/sell_state as
RSIIntra); the base frame (15m, or 5m via CLI) decides WHERE via KDJ:
- Entry: first KDJ golden cross (K up through D) while buy_sig active.
- Exit: first KDJ death cross (K down through D) while sell_state active.
Unlike single-bar red/green triggers, a cross needs two consecutive
bars of directional agreement, filtering intraday chop.
No gate/DCA/ROI/stoploss beyond the regime gating.
"""
import numpy as np
import pandas as pd
from pandas import DataFrame

try:
    from RSIIntra import RSIIntra
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.RSIIntra import RSIIntra


def _kdj(close, high, low, n=9, m1=3, m2=3):
    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    denom = (high_n - low_n).replace(0, np.nan)
    rsv = (close - low_n) / denom * 100.0
    k = rsv.ewm(alpha=1 / m1, adjust=False).mean()
    d = k.ewm(alpha=1 / m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


class RSIIntraKDJ(RSIIntra):
    INTERFACE_VERSION = 3

    timeframe = "15m"

    kdj_n: int = 9
    kdj_m1: int = 3
    kdj_m2: int = 3

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        k, d, j = _kdj(dataframe["close"], dataframe["high"],
                       dataframe["low"], self.kdj_n, self.kdj_m1,
                       self.kdj_m2)
        dataframe["kdj_k"] = k
        dataframe["kdj_d"] = d
        dataframe["kdj_j"] = j
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        regime = (
            dataframe["buy_sig_1d"].fillna(False)
            if "buy_sig_1d" in dataframe else False
        )
        gold = (
            (dataframe["kdj_k"] > dataframe["kdj_d"])
            & (dataframe["kdj_k"].shift(1) <= dataframe["kdj_d"].shift(1))
        ).fillna(False)
        dataframe.loc[
            (regime & gold & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "kdj_gold")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        regime = (
            dataframe["sell_state_1d"].fillna(False)
            if "sell_state_1d" in dataframe else False
        )
        dead = (
            (dataframe["kdj_k"] < dataframe["kdj_d"])
            & (dataframe["kdj_k"].shift(1) >= dataframe["kdj_d"].shift(1))
        ).fillna(False)
        dataframe.loc[
            (regime & dead & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "kdj_dead")
        return dataframe
