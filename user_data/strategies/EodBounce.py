"""EodBounce - 尾盘走弱 -> 收盘买入, 次日卖出 (30m, 1 日持仓).

来源: scripts/research/intraday_signals.py 的前瞻扫描.
  30m 最后一根 bar 跌 >0.5% (n=1043, 2023-2026, 25 只池):
    close -> 次日 11:30  +0.290% (x4 +0.231%, 胜率 53.9%, f8 +0.309%).
  同一信号在 15m/1h 同向 (+0.19%/+0.25%), 对"最后一根 bar"的定义不敏感,
  因此更像隔夜反转, 而不是某个周期的伪影.

执行口径: 15:00 bar 收盘买入 (收尾集合竞价), 次日 11:30 收盘卖出.
  同日 close 成交是项目惯例; 实盘需在 14:57 前预判尾盘方向, 会有额外滑点.
T+1: 次日 11:30 已过结算日, 可卖.
"""
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import CategoricalParameter, DecimalParameter, IStrategy


def _val(value):
    return getattr(value, "value", value)


class EodBounce(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "30m"
    startup_candle_count = 2
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = -0.10
    trailing_stop = False
    position_adjustment_enable = False

    drop = DecimalParameter(0.001, 0.02, default=0.005, space="buy",
                            optimize=True)
    exit_tod = CategoricalParameter(["11:30", "15:00"], default="11:30",
                                    space="sell", optimize=True)
    entry_tod: str = "15:00"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["tod"] = pd.to_datetime(dataframe["date"]).dt.strftime("%H:%M")
        dataframe["ret1"] = dataframe["close"] / dataframe["close"].shift(1) - 1
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        entry = (
            (dataframe["tod"] == self.entry_tod)
            & (dataframe["ret1"] < -_val(self.drop))
            & (dataframe["volume"] > 0)
        ).fillna(False)
        dataframe.loc[entry, ["enter_long", "enter_tag"]] = (1, "eod_drop")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = (
            (dataframe["tod"] == _val(self.exit_tod))
            & (dataframe["volume"] > 0)
        ).astype(int)
        return dataframe
