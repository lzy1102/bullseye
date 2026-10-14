"""
Supermarket - 超市战法还原版 (A股散户流行手法), 1d.

民间玩法: 买一大堆股票, 每只只买一手 (100股), 涨10~20%就卖, 亏了死扛,
跌50%再补一手. 逻辑是"东边不亮西边亮, 心理压力小".
本版参数化还原:
- 进: 股价从20日高点回落5%以上 (低吸) 且未持有, 每只买1手.
- 出: 净盈利>=15% 落袋 (经典10~20%卖).
- 补: 浮亏<=-50% 补1手, 最多补2次 (原版不限, 这里防无限).
- 无止损无门禁无大盘过滤: 死扛到底, 完全还原民间打法.
"""
from typing import Optional

import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy


class Supermarket(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = True

    take_profit: float = 0.15
    add_drop: float = -0.50
    max_adds: int = 2
    dip_pct: float = 0.05

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["hh20"] = (
            dataframe["high"].rolling(20).max().shift(1)
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dip = (
            (dataframe["close"] <= dataframe["hh20"] * (1 - self.dip_pct))
            & (dataframe["volume"] > 0)
        ).fillna(False)
        dataframe.loc[
            dip,
            ["enter_long", "enter_tag"],
        ] = (1, "sm_dip")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe

    def custom_stake_amount(
        self, pair: str, current_time, current_rate: float,
        proposed_stake: float, min_stake, max_stake: float,
        leverage: float, entry_tag, side: str, **kwargs,
    ) -> Optional[float]:
        # 一手 = 100股, 按当前价买1手; 钱不够一手由引擎整手检查拒绝.
        stake = current_rate * 100.0
        if max_stake and max_stake > 0:
            stake = min(stake, max_stake)
        return stake

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        if current_profit >= self.take_profit:
            return "sm_take15"
        return None

    def adjust_trade_position(
        self, trade, current_time, current_rate: float,
        current_profit: float, min_stake, max_stake: float,
        current_entry_rate: float, current_exit_rate: float,
        current_entry_profit: float, current_exit_profit: float,
        min_limit: float, max_limit: float, **kwargs,
    ) -> Optional[float]:
        if trade.nr_of_successful_entries > self.max_adds:
            return None
        if current_profit > self.add_drop:
            return None
        stake = current_rate * 100.0
        if max_stake and max_stake > 0:
            stake = min(stake, max_stake)
        return stake
