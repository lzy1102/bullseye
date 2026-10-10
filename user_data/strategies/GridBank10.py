"""
GridBank10 - A-share grid averaging-down strategy.

Rules (per pair):
- Capital is split into 5 equal tranches; tranche 1 opens on the first
  signal candle, tranches 2-5 are added by adjust_trade_position().
- Trend gate: no first entry while the daily trend is down
  (SMA20 <= SMA60). Open grids keep their DCA/exit rules.
- Add one tranche each time the price falls 5% below the last buy price.
- No fixed take-profit: exits via a trailing stop on net profit. Each
  trade tracks its peak net profit; it closes once profit gives back
  trail_distance (default 3%) from the peak. The trail arms only above
  break-even, so a grid that never turns green is never sold red.
- No stoploss / ROI (a stoploss would violate "never sell red").

Position sizing note: set tranche_stake so one tranche buys >= 100 shares
at the traded price (A-share lot rule), e.g. 12000 for a ~40 CNY stock.
"""
from typing import Dict, Optional

from bullseye.strategy import IStrategy
from pandas import DataFrame


class GridBank10(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    # Daily-trend gate for the first tranche (SMA20 > SMA60).
    trend_gate: bool = True

    # All exit timing lives in custom_exit; built-ins stay off.
    minimal_roi: dict = {}
    stoploss: float = 0
    trailing_stop = False

    position_adjustment_enable = True

    max_tranches: int = 5
    dip_step: float = 0.05
    # Trailing-stop on net profit: close once profit falls this far
    # below its peak for the trade. No fixed take-profit level.
    trail_distance: float = 0.03
    # Trail arms only above this net profit (0 = break-even).
    trail_arm: float = 0.0
    # Per-tranche stake. <= 0 means AUTO: total equity / max_tranches,
    # so position sizing follows the account with no manual tuning.
    tranche_stake: float = 0.0

    def __init__(self):
        # Per-(run, pair) grid state; a fresh instance starts every run.
        self._adds: Dict[str, int] = {}
        self._last_buy: Dict[str, float] = {}
        self._open_trade_id: Dict[str, str] = {}
        self._peak: Dict[str, float] = {}

    def _reset_if_new_trade(self, pair: str, trade_id: str) -> None:
        if self._open_trade_id.get(pair) != trade_id:
            self._open_trade_id[pair] = trade_id
            self._adds[pair] = 0
            self._last_buy.pop(pair, None)
            self._peak.pop(pair, None)

    def _auto_tranche(self) -> float:
        """One tranche = total equity / max_tranches (auto sizing)."""
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
        # Auto mode: first tranche equals every other tranche.
        if self.tranche_stake <= 0:
            auto = self._auto_tranche()
            if auto > 0:
                return min(auto, max_stake)
        return None  # fall back to engine/config stake

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ma20"] = dataframe["close"].rolling(20).mean()
        dataframe["ma60"] = dataframe["close"].rolling(60).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Grid starts on the first available candle with the daily
        # trend up (SMA20 > SMA60); downtrends are skipped entirely.
        cond = dataframe["volume"] > 0
        if self.trend_gate:
            cond = cond & (dataframe["ma20"] > dataframe["ma60"])
        dataframe.loc[
            cond,
            ["enter_long", "enter_tag"],
        ] = (1, "grid_start")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exits come only from custom_exit (profitable closes).
        dataframe["exit_long"] = 0
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
        pair = trade.pair
        self._reset_if_new_trade(pair, trade.id)
        if self._adds.get(pair, 0) >= self.max_tranches - 1:
            return None  # all 10 tranches deployed
        ref = self._last_buy.get(pair, trade.open_rate)
        if ref and current_rate <= ref * (1 - self.dip_step):
            self._adds[pair] = self._adds.get(pair, 0) + 1
            self._last_buy[pair] = current_rate
            size = (self.tranche_stake if self.tranche_stake > 0
                    else self._auto_tranche())
            if size <= 0:
                # No measurable equity (e.g. wallets unavailable): skip.
                self._adds[pair] -= 1
                self._last_buy[pair] = ref
                return None
            return min(size, max_stake)
        if pair not in self._last_buy:
            # Record the initial fill for the dip ladder.
            self._last_buy[pair] = trade.open_rate
        return None

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        exit_reason: str,
        **kwargs,
    ) -> Optional[str]:
        # Trailing stop on net profit: track the peak, exit on give-back.
        # Never sell red: the trail arms only above break-even.
        peak = self._peak.get(pair)
        if peak is None or current_profit > peak:
            peak = current_profit
            self._peak[pair] = peak
        if peak > self.trail_arm and current_profit <= peak - self.trail_distance:
            self._adds.pop(pair, None)
            self._last_buy.pop(pair, None)
            self._open_trade_id.pop(pair, None)
            self._peak.pop(pair, None)
            return "grid_trailing_stop"
        return None
