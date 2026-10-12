"""
DcaFixed - plain scheduled averaging-down (定投).

Rules (per pair, long only, 1d):
- Tranche 1: after N straight red days (close < prev close, N in a row).
- Adds (tranches 2-5): each time ANOTHER full N-day red run completes
  after the last fill.
- Exit all: net profit reaches R (fixed ROI target), OR the daily
  gate turns bear (MA20 < MA60) -> exit at market even at a loss
  ("gate_bear"). No stoploss, no trailing.
- Gate also guards entries: no first tranche while the gate is down
  (prevents reopening into an ongoing bear market right after a cut).
"""
from typing import Dict, Optional

from bullseye.strategy import IStrategy
from pandas import DataFrame


class DcaFixed(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = True

    # Straight red days that trigger a buy.
    red_days: int = 3
    # Fixed take-profit on net profit. Below it: never sell.
    target_roi: float = 0.08
    max_tranches: int = 5
    # Swing-low breakdown exit: close below the lowest low of the prior
    # N bars (excl. current) exits immediately, without waiting for the
    # slow death cross. Catches fast breakdowns the MA gate misses.
    swing_window: int = 20

    def __init__(self):
        # Last fill date per pair (first fill = trade open date).
        self._last_buy: Dict[str, object] = {}
        self._open_trade_id: Dict[str, str] = {}

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

    @staticmethod
    def _streak(close) -> object:
        red = (close < close.shift(1)).fillna(False)
        grp = (~red).cumsum()
        return red.groupby(grp).cumsum()

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["red_streak"] = self._streak(dataframe["close"])
        dataframe["ma20"] = dataframe["close"].rolling(20).mean()
        dataframe["ma60"] = dataframe["close"].rolling(60).mean()
        dataframe["swing_low"] = (
            dataframe["low"].shift(1).rolling(self.swing_window).min()
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        fresh = (
            (dataframe["red_streak"] == self.red_days)
            & (dataframe["red_streak"].shift(1) != self.red_days)
        ).fillna(False)
        gate_up = (dataframe["ma20"] > dataframe["ma60"]).fillna(False)
        dataframe.loc[
            (fresh & gate_up & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "dca_start")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["close"] < dataframe["swing_low"])
                & (dataframe["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "swing_break")
        dataframe.loc[
            (
                (dataframe["ma20"] < dataframe["ma60"])
                & (dataframe["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "gate_bear")
        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        if current_profit >= self.target_roi:
            self._last_buy.pop(pair, None)
            self._open_trade_id.pop(pair, None)
            return "dca_target"
        return None

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
        pair = trade.pair
        if self._open_trade_id.get(pair) != trade.id:
            self._open_trade_id[pair] = trade.id
            self._last_buy[pair] = trade.open_date
        if trade.nr_of_successful_entries >= self.max_tranches:
            return None
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        except Exception:
            return None
        if dataframe is None or dataframe.empty:
            return None
        streak = self._streak(dataframe["close"])
        # A fresh N-run completed on the latest closed bar, strictly
        # after the last fill.
        last = dataframe.iloc[-1]
        try:
            import pandas as pd

            last_buy_day = pd.to_datetime(self._last_buy.get(pair)).date()
            bar_day = pd.to_datetime(last["date"]).date()
        except Exception:
            return None
        if bar_day <= last_buy_day:
            return None
        if int(streak.iloc[-1]) != self.red_days:
            return None
        # Ensure the streak that just completed is a NEW run (not the
        # same bars as the entry run): require an up day in between.
        size = self._auto_tranche()
        if size <= 0:
            return None
        self._last_buy[pair] = last["date"]
        return min(size, max_stake)
