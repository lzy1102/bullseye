"""
VolPriceSpot - pure volume-price trend entries (long only, no patterns).

Entry legs (any one fires, daily gate must be up):
- obv_break: OBV crosses above its prior-20-day max (money flow leads
  price; accumulation spotted before the run).
- mfi_rev: MFI(14) crosses up through 30 (capitulation wash-out bounce).
- vol_surge: volume ratio > 1.5 for 3 straight days with price rising
  (sustained accumulation, not a single frenzy bar).

Exit: daily gate turns bear (SMA20 < SMA60) only. No DCA, no ROI, no
stoploss: this experiment isolates ENTRY timing against BaseSpot
(gate-flip entries), so exits stay identical.
"""
import numpy as np
from bullseye.strategy import DecimalParameter, IntParameter, IStrategy
from pandas import DataFrame


def _int(value) -> int:
    """Unwrap hyperopt parameters on old and new engines."""
    return int(getattr(value, "value", value))


def _float(value) -> float:
    """Unwrap hyperopt parameters on old and new engines."""
    return float(getattr(value, "value", value))


def _mfi(high, low, close, volume, period=14):
    tp = (high + low + close) / 3.0
    mf = tp * volume
    direction = tp.diff()
    pos = mf.where(direction > 0, 0.0)
    neg = mf.where(direction < 0, 0.0)
    pos_sum = pos.rolling(period).sum()
    neg_sum = neg.rolling(period).sum()
    mr = pos_sum / neg_sum.replace(0, np.nan)
    out = 100.0 - 100.0 / (1.0 + mr)
    return out.fillna(50.0)


class VolPriceSpot(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    obv_window = IntParameter(10, 30, default=20, space="buy", optimize=True)
    mfi_period = IntParameter(7, 21, default=14, space="buy", optimize=True)
    mfi_trigger = DecimalParameter(20.0, 40.0, default=30.0, space="buy",
                                     optimize=True)
    vol_window: int = 20
    vol_mult = DecimalParameter(1.0, 2.5, default=1.5, space="buy",
                                optimize=True)
    vol_days: int = 3

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        volume = dataframe["volume"]
        dataframe["ma20"] = close.rolling(20).mean()
        dataframe["ma60"] = close.rolling(60).mean()
        # OBV and its prior-window max (shifted: new high vs history).
        signed = np.sign(close.diff()).fillna(0.0) * volume
        dataframe["obv"] = signed.cumsum()
        dataframe["obv_max"] = (
            dataframe["obv"].rolling(_int(self.obv_window)).max().shift(1)
        )
        dataframe["mfi"] = _mfi(
            dataframe["high"], dataframe["low"], close, volume,
            _int(self.mfi_period),
        )
        dataframe["vol_ma"] = volume.rolling(self.vol_window).mean().shift(1)
        dataframe["vol_ratio"] = volume / dataframe["vol_ma"]
        dataframe["up3"] = close > close.shift(self.vol_days)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        gate = (dataframe["ma20"] > dataframe["ma60"]).fillna(False)
        obv_break = (
            (dataframe["obv"] > dataframe["obv_max"])
            & (dataframe["volume"] > 0)
        ).fillna(False)
        trig = _float(self.mfi_trigger)
        mfi_rev = (
            (dataframe["mfi"] > trig)
            & (dataframe["mfi"].shift(1) <= trig)
            & (dataframe["volume"] > 0)
        ).fillna(False)
        mult = _float(self.vol_mult)
        vol_surge = (
            (dataframe["vol_ratio"] > mult)
            & (dataframe["vol_ratio"].shift(1) > mult)
            & (dataframe["vol_ratio"].shift(2) > mult)
            & dataframe["up3"]
            & (dataframe["volume"] > 0)
        ).fillna(False)
        base = gate & (dataframe["volume"] > 0)
        dataframe.loc[base & obv_break, ["enter_long", "enter_tag"]] = (
            1, "obv_break")
        dataframe.loc[
            base & ~obv_break & mfi_rev, ["enter_long", "enter_tag"]] = (
            1, "mfi_rev")
        dataframe.loc[
            base & ~obv_break & ~mfi_rev & vol_surge,
            ["enter_long", "enter_tag"]] = (1, "vol_surge")
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
