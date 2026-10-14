"""
MomRot - 动量轮动 (AI/高波动池专用), 1d.

目标导向: 年化40%+. AI池 (寒武纪+2489%/海光+425%/富联+558%) 是暴力动量,
抄底/慢门禁都吃不到, 只有动量突破+快砍才能跟.
思路:
- 进: 20日动量>8% (相对强度) + 多头排列 (close>MA20>MA60) + MACD柱
  上穿零轴 (动量翻正瞬间), 三个条件同天成立才进.
- 出: ① 跌破MA20 (趋势断) ② -5%认错 ③ 30天时间到 ④ fade3.
- 单仓无加仓, 资金全速轮转, 持仓基本<=30天.
"""
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy


class MomRot(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 80
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False
    max_holding_days: int = 30
    wrong_cut: float = -0.05
    mom_threshold: float = 0.08
    mom_window: int = 20

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(
            span=26, adjust=False).mean()
        sig = macd.ewm(span=9, adjust=False).mean()
        dataframe["macd"] = macd
        dataframe["macd_sig"] = sig
        h = macd - sig
        dataframe["hist"] = h
        dataframe["fade3"] = (
            (h < 0)
            & (h < h.shift(1)) & (h.shift(1) < h.shift(2))
            & (h.shift(2) < h.shift(3))
        ).fillna(False)
        dataframe["ma20"] = close.rolling(20).mean()
        dataframe["ma60"] = close.rolling(60).mean()
        dataframe["mom20"] = close / close.shift(self.mom_window) - 1
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        h = dataframe["hist"]
        flip = (
            (h > 0) & (h.shift(1) <= 0)
        ).fillna(False)
        stack = (
            (dataframe["close"] > dataframe["ma20"])
            & (dataframe["ma20"] > dataframe["ma60"])
        ).fillna(False)
        strong = (dataframe["mom20"] > self.mom_threshold).fillna(False)
        dataframe.loc[
            (flip & stack & strong & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "mom_rot")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        break20 = (
            (dataframe["close"] < dataframe["ma20"])
            & (dataframe["close"].shift(1) >= dataframe["ma20"].shift(1))
        ).fillna(False)
        dataframe.loc[
            ((break20 | dataframe["fade3"]) & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "mom_break")
        return dataframe

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        try:
            days = (
                pd.to_datetime(current_time) - pd.to_datetime(trade.open_date)
            ).days
        except (TypeError, ValueError, AttributeError):
            days = 0
        if days >= self.max_holding_days:
            return "time_30d"
        if current_profit <= self.wrong_cut:
            return "wrong_cut"
        return None
