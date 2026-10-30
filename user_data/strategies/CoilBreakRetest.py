"""
CoilBreakRetest - 缩量收敛箱体突破 + 首次回踩不破（因果）, 1d, 只做多.

来源: docs/龙头结构区域_实验归档.md 第七节.
  事件研究 (因果, 2018-2026, 费 0.2%):
    coil50 回踩: h20 +3.00% (t=3.92, n=353), h40 +3.75%
    分段: 2018-22 h20 +4.18%；2023-26 h20 +2.92%
    直接追突破(不等回踩): h20 +2.16% / +2.39% —— 回踩只多贡献 ~0.5~2pp
    短周期(h3~5)在 2023-26 是负的 → 必须拿够 20 根
  结论: 有效但主要来自突破动量本身, 回踩是小增量; 中位数不稳, 靠少数大单.

规则 (全部因果, 箱体=过去20根, 不含当根):
  1. 选股: 20日均成交额>=2亿, 换手>=0.3%, 250日涨跌比>=1.0, 500日回撤>=-50%
  2. 收敛: 箱体宽度在过去100日分位 <= 50%
  3. 突破: 收盘 > 箱体上沿, 量 >= 1.2x 20日中位
  4. 回踩: 突破后 10 根内, 最低价 <= 上沿 x 1.01 且收盘 > 上沿（不跌回箱体）
  5. 出场: 时间止损 20 根 + 硬止损 8%
"""
import numpy as np
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy


class CoilBreakRetest(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 400
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = -0.08
    trailing_stop = False
    position_adjustment_enable = False

    # 选股
    min_amount: float = 2.0e8
    min_turn: float = 0.3
    min_ratio: float = 1.0
    max_dd: float = 0.50
    # 箱体
    box: int = 20
    width_pct: float = 0.50
    # 突破/回踩
    brk_vol: float = 1.2
    touch_tol: float = 0.01
    retest_win: int = 10
    # 出场/组合
    time_stop: int = 20
    max_slots: int = 3
    index_pair: str = "000300.SH"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = dataframe.reset_index(drop=True)
        c = dataframe["close"].to_numpy(float)
        h = dataframe["high"].to_numpy(float)
        l = dataframe["low"].to_numpy(float)
        v = dataframe["volume"].to_numpy(float)
        turn = (dataframe["turn"].to_numpy(float) if "turn" in dataframe
                else np.full(len(c), np.nan))
        n = len(c)

        dataframe["ma20"] = dataframe["close"].rolling(20).mean()
        lvl = pd.Series(h).shift(1).rolling(self.box).max().to_numpy()
        lo = pd.Series(l).shift(1).rolling(self.box).min().to_numpy()
        width = (lvl - lo) / ((lvl + lo) / 2)
        wrank = pd.Series(width).rolling(100).rank(pct=True).to_numpy()
        vmed = pd.Series(v).shift(1).rolling(20).median().to_numpy()
        amt = c * v * 100
        amt20 = pd.Series(amt).rolling(20).median().to_numpy()
        turn20 = pd.Series(turn).rolling(20).mean().to_numpy()
        lr = np.log(pd.Series(c)).diff()
        pos = lr.clip(lower=0).rolling(250).sum().to_numpy()
        neg = (-lr.clip(upper=0)).rolling(250).sum().to_numpy()
        ratio = np.divide(pos, neg, out=np.full(n, np.nan), where=(neg > 0))
        roll_max = pd.Series(c).rolling(500, min_periods=250).max().to_numpy()
        mdd = pd.Series(c / roll_max - 1).rolling(500, min_periods=250).min().to_numpy()
        screened = ((np.arange(n) >= 500) & (amt20 >= self.min_amount)
                    & (turn20 >= self.min_turn) & (ratio >= self.min_ratio)
                    & (mdd >= -self.max_dd))

        entry = np.zeros(n, dtype=bool)
        pending_level = np.nan
        pending_until = -1
        for j in range(n):
            if np.isfinite(pending_level):
                if j > pending_until or c[j] < pending_level * 0.98:
                    pending_level = np.nan
                elif l[j] <= pending_level * (1 + self.touch_tol) and c[j] > pending_level:
                    entry[j] = True
                    pending_level = np.nan
            if (not np.isfinite(pending_level) and screened[j]
                    and np.isfinite(wrank[j]) and wrank[j] <= self.width_pct
                    and np.isfinite(lvl[j]) and c[j] > lvl[j]
                    and vmed[j] > 0 and v[j] >= self.brk_vol * vmed[j]):
                pending_level = lvl[j]
                pending_until = j + self.retest_win

        dataframe["st_entry"] = entry
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        sig = dataframe["st_entry"].fillna(False) & (dataframe["volume"] > 0)
        dataframe.loc[sig, ["enter_long", "enter_tag"]] = (1, "retest_hold")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe

    def confirm_trade_entry(
        self, pair: str, order_type: str, amount: float, rate: float,
        time_in_force: str, current_time, entry_tag, side: str, **kwargs,
    ) -> bool:
        if pair == self.index_pair:
            return False
        return True

    def custom_stake_amount(
        self, pair: str, current_time, current_rate: float,
        proposed_stake: float, min_stake, max_stake: float,
        leverage: float, entry_tag, side: str, **kwargs,
    ):
        try:
            total = self.wallets.get_total_stake_amount()
        except Exception:
            return None
        if not total or total <= 0:
            return None
        stake = total / max(1, int(self.max_slots))
        if max_stake and stake > max_stake:
            stake = max_stake
        return stake

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        except Exception:
            return None
        if df is None or df.empty or "date" not in df:
            return None
        held = df[pd.to_datetime(df["date"]) >= pd.to_datetime(trade.open_date)]
        if held.empty:
            return None
        if len(held) >= self.time_stop:
            return "time_stop"
        return None
