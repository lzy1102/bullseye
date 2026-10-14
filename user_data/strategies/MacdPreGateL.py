"""
MacdPreGateL - leaders variant of MacdPreGate (SMA8/58 gate).

Same pre-cross entry, fast gate for volatile leaders.
"""
from typing import Dict, Optional

from bullseye.strategy import IStrategy
from pandas import DataFrame


class MacdPreGateL(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 130
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = True
    max_tranches: int = 5
    gate_fast: int = 8
    gate_slow: int = 58

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
        self, pair: str, current_time, current_rate: float,
        proposed_stake: float, min_stake: Optional[float],
        max_stake: float, leverage: float,
        entry_tag: Optional[str], side: str, **kwargs,
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
        dataframe["ma_fast"] = close.rolling(self.gate_fast).mean()
        dataframe["ma_slow"] = close.rolling(self.gate_slow).mean()
        dataframe["bull"] = (dataframe["ma_fast"] > dataframe["ma_slow"]).fillna(False)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        h = dataframe["hist"]
        dif_up = (dataframe["macd"] > dataframe["macd"].shift(1)).fillna(False)
        rising2 = ((h > h.shift(1)) & (h.shift(1) > h.shift(2))).fillna(False)
        early = ((h < 0) & rising2 & dif_up).fillna(False)
        cross = (
            (dataframe["macd"] > dataframe["macd_sig"])
            & (dataframe["macd"].shift(1) <= dataframe["macd_sig"].shift(1))
        ).fillna(False)
        dataframe.loc[
            ((early | cross) & dataframe["bull"] & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "macd_pre_gate_l")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        bear = (dataframe["ma_fast"] < dataframe["ma_slow"]).fillna(False)
        dataframe.loc[
            (bear & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "gate_bear")
        return dataframe

    def adjust_trade_position(
        self, trade, current_time, current_rate: float,
        current_profit: float, min_stake: Optional[float],
        max_stake: float, current_entry_rate: float,
        current_exit_rate: float, current_entry_profit: float,
        current_exit_profit: float, min_limit: float,
        max_limit: float, **kwargs,
    ) -> Optional[float]:
        if trade.nr_of_successful_entries >= self.max_tranches:
            return None
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
        except Exception:
            return None
        if dataframe is None or dataframe.empty:
            return None
        last = dataframe.iloc[-1]
        if not last["bull"]:
            return None
        if current_rate >= last["close"]:
            return None
        size = self._auto_tranche()
        if size <= 0:
            return None
        return min(size, max_stake)
