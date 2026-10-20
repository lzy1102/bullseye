"""TrendDayHold - 趋势日收盘买入, 次日卖出 (30m, 1 日持仓).

来源: scripts/research/intraday_signals.py 的前瞻扫描.
  条件: 上午收益 > +1% 且 下午至今 > +1% (15:00 收盘时).
  30m, 2023-2026, 25 只池:
    n=509, close -> 次日 11:30  +0.485% (x4 +0.427%, 胜率 50.3%, f8 +0.306%).
  同信号 15m/1h/5m 的 x4 在 +0.37~+0.57% 之间, 方向一致.
  本质是趋势日隔夜动量, 胜率只有 50%, 收益靠右尾.

执行口径: 15:00 bar 收盘买入, 次日 11:30 收盘卖出.
  am_ret / pm_ret 只在 15:00 bar 赋值, 避免早盘误用未来数据.
"""
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import CategoricalParameter, DecimalParameter, IStrategy


def _val(value):
    return getattr(value, "value", value)


class TrendDayHold(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "30m"
    startup_candle_count = 2
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = -0.10
    trailing_stop = False
    position_adjustment_enable = False

    am_thr = DecimalParameter(0.002, 0.03, default=0.01, space="buy",
                              optimize=True)
    pm_thr = DecimalParameter(0.002, 0.03, default=0.01, space="buy",
                              optimize=True)
    exit_tod = CategoricalParameter(["11:30", "15:00"], default="11:30",
                                    space="sell", optimize=True)
    am_tod: str = "11:30"
    entry_tod: str = "15:00"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dt = pd.to_datetime(dataframe["date"])
        dataframe["tod"] = dt.dt.strftime("%H:%M")
        dataframe["day"] = dt.dt.date
        dataframe["day_open"] = dataframe.groupby("day")["open"].transform("first")
        am_close = dataframe["close"].where(dataframe["tod"] == self.am_tod)
        am_close = am_close.groupby(dataframe["day"]).transform("max")
        is_entry = dataframe["tod"] == self.entry_tod
        am_ret = am_close / dataframe["day_open"] - 1
        pm_ret = dataframe["close"] / am_close - 1
        dataframe["am_ret"] = am_ret.where(is_entry)
        dataframe["pm_ret"] = pm_ret.where(is_entry)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        entry = (
            (dataframe["tod"] == self.entry_tod)
            & (dataframe["am_ret"] > _val(self.am_thr))
            & (dataframe["pm_ret"] > _val(self.pm_thr))
            & (dataframe["volume"] > 0)
        ).fillna(False)
        dataframe.loc[entry, ["enter_long", "enter_tag"]] = (1, "trend_day")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = (
            (dataframe["tod"] == _val(self.exit_tod))
            & (dataframe["volume"] > 0)
        ).astype(int)
        return dataframe
