"""
SupermarketTrend - 超市战法+长期趋势过滤版.

进场: 原版下探5%买一手 + 长期趋势过滤 (年线之上且年线向上, 下行的票不做),
出场: +15%落袋, -8%止损, 不补仓.
对照"进场没选趋势"的差距 —— 同一出场只换进场质量.
"""
from typing import Optional

from pandas import DataFrame

try:
    from strategies.Supermarket import Supermarket
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.Supermarket import Supermarket


class SupermarketTrend(Supermarket):
    INTERFACE_VERSION = 3

    stoploss: float = -0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["ma250"] = dataframe["close"].rolling(250).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_up = (
            (dataframe["close"] > dataframe["ma250"])
            & (dataframe["ma250"] > dataframe["ma250"].shift(20))
        ).fillna(False)
        dip = (
            (dataframe["close"] <= dataframe["hh20"] * (1 - self.dip_pct))
            & (dataframe["volume"] > 0)
        ).fillna(False)
        dataframe.loc[
            (dip & long_up),
            ["enter_long", "enter_tag"],
        ] = (1, "sm_trend_dip")
        return dataframe

    def adjust_trade_position(
        self, trade, current_time, current_rate: float,
        current_profit: float, min_stake, max_stake: float,
        current_entry_rate: float, current_exit_rate: float,
        current_entry_profit: float, current_exit_profit: float,
        min_limit: float, max_limit: float, **kwargs,
    ) -> Optional[float]:
        return None
