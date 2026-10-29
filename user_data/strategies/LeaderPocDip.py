"""
LeaderPocDip - 龙头 + 放量下跌 + 缩量箱体 + 区域下沿低吸, 1d, 只做多.

⛔ 负面结果，不要用于实盘（2026-10-29）。
   2018-2026 组合回测 -26.8%（69 笔，PF 0.40，胜率 36%），全参数扫描均为负。
   根因见 docs/龙头结构区域_实验归档.md 第六节：早期事件研究用了"完整箱体"
   边界（未来函数）才显得有 edge；本文件是因果实现，它的负收益才是真实结果。
   保留此文件是为了给"区间形态"类研究留一个可复现的反面样本。

来源: docs/龙头结构区域_实验归档.md
  事件级尸检 (2018-2026, 同根收盘, 费 0.2%):
    A 成交密集区(POC) 低吸  h5 +0.90%  两窗口 +1.30% / +1.19%
    B 摆动结构   低吸  h5 +1.20%  但每窗口只有 11~12 笔
    C 箱体       低吸  h5 +0.32%  2018-22 失效
    三种区域的"放量突破"入场全部为负 (C h40 -3.90%, t=-2.32)
    对照: 同池任意 20 日区间下 1/3 阳线只有 +0.21%
  => 只做低吸，且用 A(POC) 定义区域 (最稳).

⚠️ 与尸检的差异 (重要): 尸检里的箱体边界是用整段箱体算的，事后才知道箱体
   在哪结束；本策略改为**逐根推进的因果版本**：每一根只用 climax 之后到当前
   为止的价格区间，箱体随时可能失效。所以本策略的回测数字才是可交易结果，
   尸检数字只用于筛信号。

三段结构 (全部因果):
  1. 放量下跌: 量 >= vol_mult × 60日中位, 阴线, 收盘距 120日低点 <= near_low
  2. 缩量箱体: 宽度 <= max(zone_width, atr_mult×ATR20), 不破 climax低 - spring_atr×ATR,
               已持续 >= min_bars 根, 箱内量中位 <= dry_mult × climax量
  3. 低吸: 收盘落在 POC 价格带下 1/3 + 阳线 + 缩量
出场: 时间止损 time_stop 根 (尸检 h5~10 最佳) + 硬止损 7%.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy


class LeaderPocDip(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 520
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = -0.07
    trailing_stop = False
    position_adjustment_enable = False

    # ---- 选股 (逐票绝对阈值, 近似尸检的横截面筛选) ----
    min_amount: float = 2.0e8     # 20日均成交额 >= 2亿
    min_turn: float = 0.3         # 20日均换手 >= 0.3%
    min_ratio: float = 1.0        # 250日 Σ涨/Σ跌 >= 1.0 (跌少涨多)
    max_dd: float = 0.50          # 500日最大回撤 >= -50%

    # ---- 三段结构 ----
    vol_mult: float = 2.5
    near_low: float = 0.25
    zone_width: float = 0.25
    atr_mult: float = 4.0
    spring_atr: float = 1.5
    dry_mult: float = 0.60
    min_bars: int = 15
    max_bars: int = 40
    poc_coverage: float = 0.70
    dip_frac: float = 0.33

    # ---- 出场/组合 ----
    time_stop: int = 10
    max_slots: int = 3
    index_pair: str = "000300.SH"
    market_gate: bool = False     # 尸检未用大盘闸门, 默认关

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = dataframe.reset_index(drop=True)
        c = dataframe["close"].to_numpy(float)
        h = dataframe["high"].to_numpy(float)
        l = dataframe["low"].to_numpy(float)
        o = dataframe["open"].to_numpy(float)
        v = dataframe["volume"].to_numpy(float)
        turn = dataframe["turn"].to_numpy(float) if "turn" in dataframe else np.full(len(c), np.nan)
        n = len(c)

        dataframe["ma20"] = dataframe["close"].rolling(20).mean()
        dataframe["ma250"] = dataframe["close"].rolling(250).mean()
        tr = pd.concat([
            dataframe["high"] - dataframe["low"],
            (dataframe["high"] - dataframe["close"].shift()).abs(),
            (dataframe["low"] - dataframe["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        dataframe["atr"] = tr.rolling(20).mean().fillna(0.0)
        atr = dataframe["atr"].to_numpy(float)
        vmed60 = pd.Series(v).shift(1).rolling(60).median().to_numpy()
        low120 = pd.Series(l).rolling(120).min().to_numpy()
        amt = c * v * 100
        amt20 = pd.Series(amt).rolling(20).median().to_numpy()
        turn20 = pd.Series(turn).rolling(20).mean().to_numpy()
        lr = np.log(pd.Series(c)).diff()
        pos = lr.clip(lower=0).rolling(250).sum().to_numpy()
        neg = (-lr.clip(upper=0)).rolling(250).sum().to_numpy()
        ratio = np.divide(pos, neg, out=np.full(n, np.nan), where=(neg > 0))
        roll_max = pd.Series(c).rolling(500, min_periods=250).max().to_numpy()
        mdd = pd.Series(c / roll_max - 1).rolling(500, min_periods=250).min().to_numpy()

        screened = (
            (np.arange(n) >= 500)
            & (amt20 >= self.min_amount)
            & (turn20 >= self.min_turn)
            & (ratio >= self.min_ratio)
            & (mdd >= -self.max_dd)
        )

        dip = np.zeros(n, dtype=bool)
        zone_lo = np.full(n, np.nan)
        state = None
        for j in range(n):
            if state is not None:
                state["hi"] = max(state["hi"], h[j])
                state["lo"] = min(state["lo"], l[j])
                span = (state["hi"] - state["lo"]) / ((state["hi"] + state["lo"]) / 2)
                broke = state["lo"] < state["climax_low"] - self.spring_atr * state["atr20"]
                too_wide = span > max(self.zone_width, self.atr_mult * state["atr20"] / c[j])
                length = j - state["start"] + 1
                if broke or too_wide or length > self.max_bars:
                    state = None
                else:
                    zv = v[state["start"]:j + 1]
                    dry = np.median(zv) <= self.dry_mult * state["climax_vol"]
                    dn, up = self._poc(state["lo"], state["hi"], zv,
                                       (l[state["start"]:j + 1], h[state["start"]:j + 1],
                                        c[state["start"]:j + 1]))
                    zone_lo[j] = dn
                    if (length >= self.min_bars and dry and up > dn
                            and c[j] <= dn + self.dip_frac * (up - dn)
                            and c[j] > o[j] and v[j] <= self.dry_mult * state["climax_vol"]):
                        dip[j] = True
                        state = None          # one entry per base
                        continue
            # new climax starts a base for the next bar
            if (state is None and screened[j] and vmed60[j] > 0
                    and v[j] >= self.vol_mult * vmed60[j] and c[j] < o[j]
                    and c[j] <= low120[j] * (1 + self.near_low)):
                state = dict(start=j + 1, hi=-np.inf, lo=np.inf,
                             climax_low=l[j], climax_vol=v[j],
                             atr20=max(atr[j], 1e-6))

        dataframe["zone_lo"] = zone_lo
        dataframe["st_dip"] = dip
        return dataframe

    def _poc(self, lo, hi, vol, prices):
        """70% volume area inside [lo, hi] (A definition)."""
        if hi <= lo:
            return lo, hi
        pl, ph, pc = prices
        tp = (pl + ph + pc) / 3.0
        bins = 20
        edges = np.linspace(lo, hi, bins + 1)
        idx = np.clip(np.digitize(tp, edges) - 1, 0, bins - 1)
        hist = np.bincount(idx, weights=vol, minlength=bins)
        total = hist.sum()
        if total <= 0:
            return lo, hi
        order = np.argsort(hist)[::-1]
        chosen = np.zeros(bins, dtype=bool)
        acc = 0.0
        for b in order:
            if acc / total >= self.poc_coverage:
                break
            chosen[b] = True
            acc += hist[b]
        sel = np.flatnonzero(chosen)
        return float(edges[sel.min()]), float(edges[sel.max() + 1])

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        entry = dataframe["st_dip"].fillna(False) & (dataframe["volume"] > 0)
        dataframe.loc[entry, ["enter_long", "enter_tag"]] = (1, "leader_dip")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe

    def _index_bull(self) -> bool:
        try:
            idx, _ = self.dp.get_analyzed_dataframe(self.index_pair, self.timeframe)
        except Exception:
            return True
        if idx is None or idx.empty or "ma20" not in idx:
            return True
        last = idx.iloc[-1]
        return bool(last["close"] >= last["ma20"])

    def confirm_trade_entry(
        self, pair: str, order_type: str, amount: float, rate: float,
        time_in_force: str, current_time, entry_tag, side: str, **kwargs,
    ) -> bool:
        if entry_tag != "leader_dip":
            return True
        if pair == self.index_pair:
            return False
        if self.market_gate:
            return self._index_bull()
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
