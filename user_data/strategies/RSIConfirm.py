"""RSIConfirm - RSI oversold + stabilization confirmation (long only).

Experiment: does waiting for confirmation beat buying the panic bar?
- Setup: RSI(period) crosses below `oversold` (same as RSIPlain).
- Entry (tag 'rsi_confirm'): within the next 1-3 bars, the FIRST bar
  where close makes no new low (close >= min close of prior 3 bars)
  AND volume shrinks (vol_ratio < 1 vs prior-20-day mean). Otherwise
  the setup expires (keeps falling = knife, skip).
- Exit: inherited from RSIPlain (RSI crosses above `overbought`).
No gate, no DCA, no ROI, no stoploss: isolates the confirmation effect.
"""
import numpy as np
import pandas as pd
from bullseye.strategy import IntParameter
from pandas import DataFrame

try:
    # Production: engine puts user_data/ on sys.path before import.
    from RSIPlain import RSIPlain, _int
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.RSIPlain import RSIPlain, _int


class RSIConfirm(RSIPlain):
    INTERFACE_VERSION = 3

    # Defaults = RSIPlain leaders-tuned values (16/35/80).
    rsi_period = IntParameter(7, 21, default=16, space="buy", optimize=True)
    oversold = IntParameter(15, 40, default=35, space="buy", optimize=True)
    overbought = IntParameter(60, 85, default=80, space="buy", optimize=True)

    # Confirmation window (bars after the cross).
    confirm_window: int = 3
    vol_window: int = 20

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        vol = dataframe["volume"]
        dataframe["vol_ma"] = vol.rolling(self.vol_window).mean().shift(1)
        dataframe["vol_ratio"] = vol / dataframe["vol_ma"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        os_ = _int(self.oversold)
        cross = (
            (dataframe["rsi"] < os_)
            & (dataframe["rsi"].shift(1) >= os_)
        ).fillna(False)
        idx = np.arange(len(dataframe))
        cross_idx = pd.Series(idx, index=dataframe.index).where(cross).ffill()
        age = idx - cross_idx
        no_new_low = (
            dataframe["close"] >= dataframe["close"].shift(1).rolling(3).min()
        ).fillna(False)
        shrink = (dataframe["vol_ratio"] < 1.0).fillna(False)
        dataframe.loc[
            (
                (age >= 1)
                & (age <= self.confirm_window)
                & no_new_low
                & shrink
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "rsi_confirm")
        return dataframe
