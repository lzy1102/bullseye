"""
SupermarketStop - 超市战法+止损版.

与 Supermarket 相同: 下探5%买一手, +15%落袋.
区别: 不再死扛 —— 浮亏触及 stoploss 就砍 (引擎level止损),
      也不再有-50%补仓 (止损先触发, 补仓失去意义).
测试 止损 -10% / -15% 与原版死扛对比.
"""
from typing import Optional

try:
    from strategies.Supermarket import Supermarket
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.Supermarket import Supermarket


class SupermarketStop(Supermarket):
    INTERFACE_VERSION = 3

    stoploss: float = -0.10

    def adjust_trade_position(
        self, trade, current_time, current_rate: float,
        current_profit: float, min_stake, max_stake: float,
        current_entry_rate: float, current_exit_rate: float,
        current_entry_profit: float, current_exit_profit: float,
        min_limit: float, max_limit: float, **kwargs,
    ) -> Optional[float]:
        # 有止损就不补仓了.
        return None
