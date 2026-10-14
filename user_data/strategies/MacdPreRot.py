"""
MacdPreRot - 轮动专用 (先测四大行, 再扩AI/龙头), 1d.

目标导向: 在多只股票之间轮换, 单笔持仓不超过30天, 只吃一段就走, 做错-5%砍掉
做下一只, 靠频率 (一年几十上百笔) 而不是单笔拿一年来赚钱.
思路: 黑线DIF拐头提前进 (early|cross) + 站上MA20轻过滤 (不要慢门禁, 慢门禁把
轮动拖成抱股); 出场三选一: ① hist零下连缩3天 (一段走完) ② 30天时间到
(time_30d, 不格局) ③ 浮亏-5%认错 (wrong_cut). 单仓无加仓, 资金靠快进快出转起来.
"""
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy


class MacdPreRot(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False
    max_holding_days: int = 30
    wrong_cut: float = -0.05

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
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        h = dataframe["hist"]
        dif_up = (dataframe["macd"] > dataframe["macd"].shift(1)).fillna(False)
        rising2 = ((h > h.shift(1)) & (h.shift(1) > h.shift(2))).fillna(False)
        early = ((h < 0) & rising2 & dif_up).fillna(False)
        cross = (
            (dataframe["macd"] > dataframe["macd_sig"])
            & (dataframe["macd"].shift(1) <= dataframe["macd_sig"].shift(1))
        ).fillna(False)
        dataframe.loc[
            ((early | cross)
             & (dataframe["close"] > dataframe["ma20"])
             & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "rot_pre")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["fade3"] & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "rot_fade")
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
