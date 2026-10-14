"""
SupermarketBB - 超市战法+布林进场版.

进场改为布林下轨: close 跌破 BB(20,2) 下轨当天买一手 (低吸的形式化),
出场: +15%落袋, -8%止损, 不补仓.
对照原始"下探5%买"的进场质量差异.
"""
from typing import Optional

from pandas import DataFrame

try:
    from strategies.Supermarket import Supermarket
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.Supermarket import Supermarket


class SupermarketBB(Supermarket):
    INTERFACE_VERSION = 3

    stoploss: float = -0.08
    bb_period: int = 20
    bb_std: float = 2.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        mid = dataframe["close"].rolling(self.bb_period).mean()
        std = dataframe["close"].rolling(self.bb_period).std()
        dataframe["bb_mid"] = mid
        dataframe["bb_lower"] = mid - self.bb_std * std
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        below = (dataframe["close"] < dataframe["bb_lower"]).fillna(False)
        fresh = below & (~below.shift(1).fillna(False))
        dataframe.loc[
            (fresh & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "sm_bb_lower")
        return dataframe

    def adjust_trade_position(
        self, trade, current_time, current_rate: float,
        current_profit: float, min_stake, max_stake: float,
        current_entry_rate: float, current_exit_rate: float,
        current_entry_profit: float, current_exit_profit: float,
        min_limit: float, max_limit: float, **kwargs,
    ) -> Optional[float]:
        return None
