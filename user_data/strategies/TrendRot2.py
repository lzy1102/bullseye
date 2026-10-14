"""
TrendRot2 - 趋势轮动 v2 (AI/高波动池), 1d.

v1 教训: ① -5%止损被高波动刮死 (寒武纪16笔-49.6), ② trend_break单日
跌破MA20即走易被影线洗. v2:
- 进: close>MA20>MA60 且 close>MA10 且 mom20>8% 且红盘.
- 出: ① MA20连续2日跌破 (确认) ② -8%认错 ③ 30天时间到 (轮动纪律).
"""
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy


class TrendRot2(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 80
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False
    max_holding_days: int = 30
    wrong_cut: float = -0.08
    mom_window: int = 20
    mom_threshold: float = 0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(
            span=26, adjust=False).mean()
        sig = macd.ewm(span=9, adjust=False).mean()
        h = macd - sig
        dataframe["hist"] = h
        dataframe["fade3"] = (
            (h < 0)
            & (h < h.shift(1)) & (h.shift(1) < h.shift(2))
            & (h.shift(2) < h.shift(3))
        ).fillna(False)
        dataframe["ma10"] = close.rolling(10).mean()
        dataframe["ma20"] = close.rolling(20).mean()
        dataframe["ma60"] = close.rolling(60).mean()
        dataframe["mom20"] = close / close.shift(self.mom_window) - 1
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        stack = (
            (dataframe["close"] > dataframe["ma20"])
            & (dataframe["ma20"] > dataframe["ma60"])
        ).fillna(False)
        strong = (
            (dataframe["close"] > dataframe["ma10"])
            & (dataframe["mom20"] > self.mom_threshold)
            & (dataframe["close"] > dataframe["close"].shift(1))
        ).fillna(False)
        dataframe.loc[
            (stack & strong & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "trend_rot2")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        below = (dataframe["close"] < dataframe["ma20"]).fillna(False)
        break20 = below & below.shift(1).fillna(False)
        dataframe.loc[
            ((break20 | dataframe["fade3"]) & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "trend_break")
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
