"""
GridBank10 - A-share grid averaging-down strategy.

Rules (per pair):
- Capital is split into 5 equal tranches; tranche 1 opens on the first
  signal candle, tranches 2-5 are added by adjust_trade_position().
- Trend gate: no first entry while the daily trend is down
  (SMA20 <= SMA60). Open grids keep their DCA/exit rules.
- Add one tranche each time the price falls 5% below the last buy price.
- No fixed take-profit: exits via the engine trailing stop
  (Freqtrade semantics). Static stoploss is disabled (0), so a grid that
  never reaches the offset is never sold red; once net profit passes
  trailing_stop_positive_offset, the stop jumps to
  peak * (1 - trailing_stop_positive) and ratchets up only.
- No ROI.

Position sizing note: set tranche_stake so one tranche buys >= 100 shares
at the traded price (A-share lot rule), e.g. 12000 for a ~40 CNY stock.
"""
from typing import Dict, Optional

from bullseye.strategy import DecimalParameter, IntParameter, IStrategy
from pandas import DataFrame


def _int(value) -> int:
    """Unwrap hyperopt parameters on old and new engines."""
    return int(getattr(value, "value", value))


def _float(value) -> float:
    """Unwrap hyperopt parameters on old and new engines."""
    return float(getattr(value, "value", value))


class GridBank10(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    # Daily-trend gate for the first tranche (SMA20 > SMA60).
    trend_gate: bool = True

    # No ROI. Static stoploss off (0): grids hold dips until the
    # trailing offset is reached, so nothing is ever sold red.
    minimal_roi: dict = {}
    stoploss: float = 0

    # Freqtrade-style trailing stop (engine-driven, price-based, net of
    # fees). Offset > positive guarantees the first trailed stop already
    # locks in profit: 1.05 * (1 - 0.03) = 1.0185.
    trailing_stop = True
    trailing_stop_positive = 0.03
    trailing_stop_positive_offset = 0.05
    trailing_only_offset_is_reached = True

    position_adjustment_enable = True

    max_tranches = IntParameter(3, 8, default=5, space="buy", optimize=True)
    dip_step = DecimalParameter(0.03, 0.10, default=0.05, space="buy",
                                optimize=True)
    # Trailing-stop tuning knobs. The engine reads the plain
    # trailing_stop_positive/_offset attributes, so populate_indicators
    # syncs them from these parameters every run (see below).
    trail_pos = DecimalParameter(0.01, 0.06, default=0.03, space="buy",
                                 optimize=True)
    trail_offset = DecimalParameter(0.03, 0.10, default=0.05, space="buy",
                                    optimize=True)
    # Per-tranche stake. <= 0 means AUTO: total equity / max_tranches,
    # so position sizing follows the account with no manual tuning.
    tranche_stake: float = 0.0

    def __init__(self):
        # Per-(run, pair) grid state; a fresh instance starts every run.
        self._adds: Dict[str, int] = {}
        self._last_buy: Dict[str, float] = {}
        self._open_trade_id: Dict[str, str] = {}

    def _reset_if_new_trade(self, pair: str, trade_id: str) -> None:
        if self._open_trade_id.get(pair) != trade_id:
            self._open_trade_id[pair] = trade_id
            self._adds[pair] = 0
            self._last_buy.pop(pair, None)

    def _auto_tranche(self) -> float:
        """One tranche = total equity / max_tranches (auto sizing)."""
        try:
            total = self.wallets.get_total_stake_amount()
        except Exception:
            total = 0.0
        if total <= 0:
            return 0.0
        return total / max(1, _int(self.max_tranches))

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
        # Sync hyperopt-tuned knobs into the plain attributes the engine
        # reads directly (trailing_stop_positive/_offset must stay floats;
        # a Parameter object would break the engine's arithmetic).
        self.trailing_stop_positive = _float(self.trail_pos)
        self.trailing_stop_positive_offset = _float(self.trail_offset)
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
        if self._adds.get(pair, 0) >= _int(self.max_tranches) - 1:
            return None  # all tranches deployed
        ref = self._last_buy.get(pair, trade.open_rate)
        if ref and current_rate <= ref * (1 - _float(self.dip_step)):
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


