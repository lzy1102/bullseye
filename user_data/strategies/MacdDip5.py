"""
MacdDip5 - MACD golden-cross dip-buying with histogram-fade exits.

Rules (per pair, long only, 1d):
- Setup: DIF crosses above DEA (golden cross). Tranche 1 opens on the
  cross bar close.
- Adds (tranches 2-5): each red day (close below previous close) adds
  one equal tranche, only while the cross is still valid (DIF > DEA).
  If price keeps rising (no red days), fewer tranches ride.
- Exit all: histogram is BELOW zero and still declining 3 days in a
  row (hist[t] < 0 with hist[t] < hist[t-1] < hist[t-2] < hist[t-3]).
  Shrinking while above zero is normal breathing - hold. Any profit
  or loss on exit.
No ROI, no stoploss, no trailing: the fade exit is the only way out.
"""
from typing import Dict, Optional

from bullseye.strategy import IStrategy
from pandas import DataFrame


class MacdDip5(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = True

    # Fixed by spec: 5 equal tranches.
    max_tranches: int = 5

    def __init__(self):
        self._adds: Dict[str, int] = {}

    def _auto_tranche(self) -> float:
        try:
            total = self.wallets.get_total_stake_amount()
        except Exception:
            total = 0.0
        if total <= 0:
            return 0.0
        return total / max(1, int(self.max_tranches))

    def custom_stake_amount(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> Optional[float]:
        auto = self._auto_tranche()
        if auto > 0:
            return min(auto, max_stake)
        return None

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(
            span=26, adjust=False).mean()
        sig = macd.ewm(span=9, adjust=False).mean()
        dataframe["macd"] = macd
        dataframe["macd_sig"] = sig
        dataframe["hist"] = macd - sig
        h = dataframe["hist"]
        dataframe["fade3"] = (
            (h < 0)
            & (h < h.shift(1)) & (h.shift(1) < h.shift(2))
            & (h.shift(2) < h.shift(3))
        ).fillna(False)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cross = (
            (dataframe["macd"] > dataframe["macd_sig"])
            & (dataframe["macd"].shift(1) <= dataframe["macd_sig"].shift(1))
        ).fillna(False)
        dataframe.loc[
            (cross & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "macd_cross")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["fade3"] & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "hist_fade3")
        return dataframe

    def adjust_trade_position(
        self,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        min_stake: Optional[float],
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        min_limit: float,
        max_limit: float,
        **kwargs,
    ) -> Optional[float]:
        if trade.nr_of_successful_entries >= self.max_tranches:
            return None
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(
                trade.pair, self.timeframe)
        except Exception:
            return None
        if dataframe is None or dataframe.empty:
            return None
        last = dataframe.iloc[-1]
        # Cross dead: no more dip-buying.
        if last["macd"] <= last["macd_sig"]:
            return None
        # Only red days add (dp frame ends at the previous bar, so the
        # previous close is the reference for today's bar).
        if current_rate >= last["close"]:
            return None
        size = self._auto_tranche()
        if size <= 0:
            return None
        return min(size, max_stake)
