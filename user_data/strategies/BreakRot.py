"""
BreakRot - 突破轮动 (AI/高波动池), 1d.

思路: AI池大利润来自突破段 (富联30天+70%). 不做回调不做震荡, 只在
创20日新高当天进 (突破动量), 跌破MA10确认即走 (趋势结束), -8%认错,
30天轮动上限. 目标: 高暴露+只吃最强段.
"""
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy


class BreakRot(IStrategy):
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
    breakout_window: int = 20
    mom_threshold: float = 0.15

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        dataframe["ma10"] = close.rolling(10).mean()
        dataframe["ma20"] = close.rolling(20).mean()
        dataframe["ma60"] = close.rolling(60).mean()
        dataframe["hh20"] = (
            dataframe["high"].rolling(self.breakout_window).max().shift(1)
        )
        dataframe["mom20"] = close / close.shift(20) - 1
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        stack = (
            (dataframe["close"] > dataframe["ma20"])
            & (dataframe["ma20"] > dataframe["ma60"])
        ).fillna(False)
        breakout = (
            (dataframe["close"] > dataframe["hh20"])
            & (dataframe["close"] > dataframe["close"].shift(1))
        ).fillna(False)
        strong = (dataframe["mom20"] > self.mom_threshold).fillna(False)
        dataframe.loc[
            (stack & breakout & strong & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "break_rot")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        below10 = (dataframe["close"] < dataframe["ma10"]).fillna(False)
        break10 = below10 & below10.shift(1).fillna(False)
        dataframe.loc[
            (break10 & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "ma10_break")
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
