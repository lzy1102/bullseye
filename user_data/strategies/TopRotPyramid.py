"""
TopRotPyramid - TopRot + 强势加仓 (金字塔), 1d.

目标: 在大波段里放大仓位 (最大化吃波段), 同时用小底仓降低错误进场的损失.
- 底仓: total/(top_n*2) (比原版 total/top_n 轻一半).
- 加仓: 已盈利 + 收盘创近10日新高 + 大盘门禁通过 + 仍在MA20之上, 每次加一份底仓大小,
        最多加 max_adds 次 (即单只最多 3 份).
- 出场沿用 TopRot: MA20两日跌破 / -10%认错 / 30天到期.
"""
from typing import Optional

import pandas as pd

try:
    from strategies.TopRot import TopRot
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.TopRot import TopRot


class TopRotPyramid(TopRot):
    INTERFACE_VERSION = 3

    position_adjustment_enable = True
    max_adds: int = 2
    add_window: int = 10

    def custom_stake_amount(
        self, pair: str, current_time, current_rate: float,
        proposed_stake: float, min_stake, max_stake: float,
        leverage: float, entry_tag, side: str, **kwargs,
    ):
        try:
            total = self.wallets.get_total_stake_amount()
        except Exception:
            return None
        if not total or total <= 0:
            return None
        stake = total / max(1, int(self.top_n) * 2)
        if max_stake and stake > max_stake:
            stake = max_stake
        return stake

    def adjust_trade_position(
        self, trade, current_time, current_rate: float,
        current_profit: float, min_stake, max_stake: float,
        current_entry_rate: float, current_exit_rate: float,
        current_entry_profit: float, current_exit_profit: float,
        min_limit: float, max_limit: float, **kwargs,
    ) -> Optional[float]:
        # nr_of_successful_entries counts the base tranche too.
        if trade.nr_of_successful_entries > self.max_adds:
            return None
        if current_profit <= 0:
            return None
        try:
            df, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
        except Exception:
            return None
        if df is None or df.empty or len(df) < self.add_window + 1:
            return None
        last = df.iloc[-1]  # previous closed bar (today's bar is current_rate)
        if pd.isna(last.get("ma20")) or last["close"] <= last["ma20"]:
            return None
        if not self._index_ok():
            return None
        prior_high = df["close"].iloc[-self.add_window:].max()
        if current_rate <= prior_high:
            return None
        try:
            total = self.wallets.get_total_stake_amount()
        except Exception:
            return None
        if not total or total <= 0:
            return None
        stake = total / max(1, int(self.top_n) * 2)
        if max_stake and stake > max_stake:
            stake = max_stake
        return stake

    def _index_ok(self) -> bool:
        try:
            idx, _ = self.dp.get_analyzed_dataframe("000300.SH", self.timeframe)
        except Exception:
            return True
        if idx is None or idx.empty or "ma60" not in idx:
            return True
        last = idx.iloc[-1]
        if pd.isna(last["ma60"]):
            return True
        return bool(last["close"] >= last["ma60"])
