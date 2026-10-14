"""
SupermarketTrail - 超市战法+移动止损版 (无固定止盈).

与 SupermarketStop 相同: 下探5%买一手, -8%硬止损.
区别: 不设 +15% 固定止盈 —— 盈利后交给移动止损 (激活+10%, 回撤5%锁利),
让赢家多跑一段, 测试"死扛 vs 止损 vs 移动止损"的出场进化.
"""
from typing import Optional

try:
    from strategies.Supermarket import Supermarket
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.Supermarket import Supermarket


class SupermarketTrail(Supermarket):
    INTERFACE_VERSION = 3

    stoploss: float = -0.08
    trailing_stop = True
    trailing_stop_positive: float = 0.05
    trailing_stop_positive_offset: float = 0.10
    trailing_only_offset_is_reached = True

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        return None

    def adjust_trade_position(
        self, trade, current_time, current_rate: float,
        current_profit: float, min_stake, max_stake: float,
        current_entry_rate: float, current_exit_rate: float,
        current_entry_profit: float, current_exit_profit: float,
        min_limit: float, max_limit: float, **kwargs,
    ) -> Optional[float]:
        return None
