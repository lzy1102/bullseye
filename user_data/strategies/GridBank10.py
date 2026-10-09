"""
GridBank10 - A-share grid averaging-down strategy.

Rules (per pair):
- Capital is split into 5 equal tranches; tranche 1 opens on the first
  signal candle, tranches 2-5 are added by adjust_trade_position().
- Add one tranche each time the price falls 5% below the last buy price.
- Never close at a loss: exits only via custom_exit once net profit
  reaches the take-profit target (default +5%).
- No stoploss / ROI / trailing (a stoploss would violate "never sell red").

Position sizing note: set tranche_stake so one tranche buys >= 100 shares
at the traded price (A-share lot rule), e.g. 12000 for a ~40 CNY stock.
"""
from typing import Dict, Optional

from bullseye.strategy import IStrategy
from pandas import DataFrame


class GridBank10(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 5
    can_short = False

    # All exit timing lives in custom_exit; built-ins stay off.
    minimal_roi: dict = {}
    stoploss: float = 0
    trailing_stop = False

    position_adjustment_enable = True

    max_tranches: int = 5
    dip_step: float = 0.05
    take_profit: float = 0.05
    tranche_stake: float = 12000.0

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

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Grid starts on the first available candle.
        dataframe.loc[
            (dataframe["volume"] > 0),
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
            return min(self.tranche_stake, max_stake)
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
        # Never sell red: only a net-profitable grid may close.
        if current_profit >= self.take_profit:
            self._adds.pop(pair, None)
            self._last_buy.pop(pair, None)
            self._open_trade_id.pop(pair, None)
            return "grid_take_profit"
        return None
