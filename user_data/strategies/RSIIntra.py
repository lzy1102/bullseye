"""RSIIntra - daily RSI regime, intraday 30m timing (long only).

Design: 1d decides WHETHER, 30m decides WHERE (intraday high-low
ranges differ a lot: banks ~1.8%, leaders ~3% daily amplitude).
- Daily (informative 1d): RSIConfirm-style confirmed setup -> buy_sig
  event; cool state -> sell_state (rsi back <= line while overheated
  within the last `cool_window` bars, persists ~5 days for timing).
- 30m base: buy on the first RED 30m bar while buy_sig is active
  (intraday dip); sell on the first GREEN 30m bar while sell_state
  is active (intraday bounce).
T+1 settlement is enforced by the engine; no gate/DCA/ROI/stoploss.
"""
import numpy as np
import pandas as pd
from bullseye.strategy import IntParameter, IStrategy, informative
from pandas import DataFrame


def _int(value) -> int:
    return int(getattr(value, "value", value))


def _rsi(close, period):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)


class RSIIntra(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "30m"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    # Defaults = leaders-tuned RSI values (16/35/80).
    rsi_period = IntParameter(7, 21, default=16, space="buy", optimize=True)
    oversold = IntParameter(15, 40, default=35, space="buy", optimize=True)
    overbought = IntParameter(60, 85, default=80, space="buy", optimize=True)
    confirm_window: int = 3
    vol_window: int = 20
    cool_window: int = 5

    @informative("1d")
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        period = _int(self.rsi_period)
        os_ = _int(self.oversold)
        ob = _int(self.overbought)
        close = dataframe["close"]
        vol = dataframe["volume"]
        dataframe["rsi_d"] = _rsi(close, period)
        # Setup event: fresh cross below oversold.
        cross = (
            (dataframe["rsi_d"] < os_)
            & (dataframe["rsi_d"].shift(1) >= os_)
        ).fillna(False)
        idx = np.arange(len(dataframe))
        cross_idx = pd.Series(idx, index=dataframe.index).where(cross).ffill()
        age = idx - cross_idx
        dataframe["vol_ma"] = vol.rolling(self.vol_window).mean().shift(1)
        dataframe["vol_ratio"] = vol / dataframe["vol_ma"]
        no_new_low = (
            close >= close.shift(1).rolling(3).min()
        ).fillna(False)
        shrink = (dataframe["vol_ratio"] < 1.0).fillna(False)
        dataframe["buy_sig"] = (
            (age >= 1)
            & (age <= self.confirm_window)
            & no_new_low
            & shrink
            & (vol > 0)
        )
        # Cool state: back at/below the line while overheated within the
        # last cool_window bars (persists so 30m has room to time it).
        hot = (dataframe["rsi_d"] > ob).fillna(False)
        was_hot = (hot.shift(1).rolling(self.cool_window).max() == 1)
        dataframe["sell_state"] = (
            (dataframe["rsi_d"] <= ob)
            & was_hot.fillna(False)
            & (vol > 0)
        )
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        regime = (
            dataframe["buy_sig_1d"].fillna(False)
            if "buy_sig_1d" in dataframe else False
        )
        red30 = (dataframe["close"] < dataframe["close"].shift(1)).fillna(False)
        dataframe.loc[
            (regime & red30 & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "intra_dip")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        regime = (
            dataframe["sell_state_1d"].fillna(False)
            if "sell_state_1d" in dataframe else False
        )
        green30 = (dataframe["close"] > dataframe["close"].shift(1)).fillna(False)
        dataframe.loc[
            (regime & green30 & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "intra_bounce")
        return dataframe
