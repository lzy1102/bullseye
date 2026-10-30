"""
ComboCoil - MacdCandle(70%) + CoilBreakRetest(30%) 单账户组合, 1d.

⛔ 不推荐用于实盘（2026-10-29 实测）：本引擎"一个票同时只能持一单"，
   两条腿会互相抢位。2018-2022 单进程组合 +7.65%，而两个独立钱包是 +37.2%。
   正确做法是跑两个进程、两个钱包：user_data/combo_coil_a.yaml (70%)
   + user_data/combo_coil_b.yaml (30%)。本文件保留作为反例与对照。

依据 docs/龙头结构区域_实验归档.md 第八节：
  两条腿日收益相关只有 0.23（月 0.11），交易重叠 2%；
  按 Coil 30% 配比，Sharpe 1.11 -> 1.14，回撤 -13.8% -> -9.3%，CAGR 15.2% -> 13.2%。
  （TopRot 与 MacdCandle 相关 0.35，也可换成 TopRot 70%，但 TopRot 与 ComboSteady 相关 0.85。）

实现方式：同一个策略内跑两套信号，按 entry_tag 分流仓位与出场。
  * macd 腿：3 个槽，单笔 70%/3；沿用 MacdCandle 的顶部形态卖出 + 吊灯 + 60 根时间止损 + -6% 止损
  * coil 腿：2 个槽，单笔 30%/2；20 根时间止损 + -8% 止损
  * 全局 max_open_trades = 5（引擎按 pair 去重，同一票同时只会有一条腿）
  * macd 腿受 300 指数 MA60 闸门约束；coil 腿不受

⚠️ 与"日频再平衡组合"的差异：这里共享一个钱包、按入场时的总权益分配 stake，
   不是每天把两条曲线重新平衡到 70/30。回测数字会略低于理论混合，但可实盘执行。
"""
import numpy as np
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy

try:
    from strategies.MacdCandle import MacdCandle
    from strategies.CoilBreakRetest import CoilBreakRetest
except ImportError:  # pragma: no cover
    from user_data.strategies.MacdCandle import MacdCandle
    from user_data.strategies.CoilBreakRetest import CoilBreakRetest


class ComboCoil(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 520
    can_short = False

    minimal_roi: dict = {}
    trailing_stop = False
    position_adjustment_enable = False

    # 组合权重与槽位
    coil_weight: float = 0.30
    macd_slots: int = 3
    coil_slots: int = 2
    total_slots: int = 5

    # 每条腿的硬止损（stoploss 全局关闭，改在 custom_exit 里按 tag 判断）
    stoploss: float = -0.99
    macd_stop: float = -0.06
    coil_stop: float = -0.08

    def __init__(self):
        self._macd = MacdCandle()
        self._coil = CoilBreakRetest()

    # ---------------------------------------------------------------- plumbing
    def _sync(self) -> None:
        for s in (self._macd, self._coil):
            s.dp = self.dp
            s.wallets = self.wallets
            s.config = self.config

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        self._sync()
        dataframe = self._macd.populate_indicators(dataframe.copy(), metadata)
        dataframe = self._coil.populate_indicators(dataframe, metadata)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        self._sync()
        m = self._macd.populate_entry_trend(dataframe.copy(), metadata)["enter_long"]
        c = self._coil.populate_entry_trend(dataframe.copy(), metadata)["enter_long"]
        m = m.fillna(0).astype(bool)
        c = c.fillna(0).astype(bool)
        dataframe["enter_long"] = (m | c).astype(int)
        dataframe["enter_tag"] = ""
        dataframe.loc[m, "enter_tag"] = "macd"
        dataframe.loc[c & ~m, "enter_tag"] = "coil"
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        self._sync()
        # 顶部形态卖出只对 macd 腿生效；由 confirm_trade_exit 拦截 coil
        return self._macd.populate_exit_trend(dataframe, metadata)

    # ---------------------------------------------------------------- hooks
    def confirm_trade_entry(
        self, pair: str, order_type: str, amount: float, rate: float,
        time_in_force: str, current_time, entry_tag, side: str, **kwargs,
    ) -> bool:
        self._sync()
        if pair == self._macd.index_pair:
            return False
        if entry_tag == "macd":
            return self._macd.confirm_trade_entry(
                pair, order_type, amount, rate, time_in_force, current_time,
                entry_tag, side, **kwargs)
        return True

    def confirm_trade_exit(
        self, pair: str, trade, order_type: str, amount: float, rate: float,
        time_in_force: str, exit_reason: str, current_time, **kwargs,
    ) -> bool:
        tag = getattr(trade, "enter_tag", "") or ""
        # coil 腿不认 macd 的顶部形态卖出：只允许硬止损/强制平仓
        if tag == "coil" and exit_reason not in ("stop_loss", "force_exit"):
            return False
        return True

    def custom_stake_amount(
        self, pair: str, current_time, current_rate: float,
        proposed_stake: float, min_stake, max_stake: float,
        leverage: float, entry_tag, side: str, **kwargs,
    ):
        self._sync()
        try:
            total = self.wallets.get_total_stake_amount()
        except Exception:
            return None
        if not total or total <= 0:
            return None
        if entry_tag == "coil":
            stake = total * self.coil_weight / max(1, self.coil_slots)
        else:
            stake = total * (1 - self.coil_weight) / max(1, self.macd_slots)
        if max_stake and stake > max_stake:
            stake = max_stake
        return stake

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        self._sync()
        tag = getattr(trade, "enter_tag", "") or ""
        if tag == "coil":
            if current_profit <= self.coil_stop:
                return "stop_loss_coil"
            return self._coil.custom_exit(pair, trade, current_time,
                                          current_rate, current_profit, **kwargs)
        if current_profit <= self.macd_stop:
            return "stop_loss_macd"
        return self._macd.custom_exit(pair, trade, current_time,
                                      current_rate, current_profit, **kwargs)
