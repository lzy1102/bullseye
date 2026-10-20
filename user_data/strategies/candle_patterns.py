"""
candle_patterns - 经典 K 线形态识别库 (日线, 纯向量, 只用当日及以前数据, 无未来函数).

供 MacdCandle / MacdHammer2 等策略复用. 所有函数输入 dataframe (需含
open/high/low/close), 输出与 dataframe 同索引的 bool Series.

形态实测 (34只大中市值池, 2023-01~2026-10, 28210 根K线, 基准 f20 +2.17%/胜率52%):
    底部类 (需配 MACD底部+收盘<MA60 才有效):
        hammer       f20 +4.71% (胜率66%)  <- 最强
        morning_star f20 +4.17% (胜率57%)  <- 次强
        bull_engulf  f20 +2.78% (胜率56%)  <- 弱
        dragonfly    f20 +2.66% (胜率52%)  <- 弱
        bull_three   f20 +3.22% (胜率50%)  <- 胜率差
        inv_hammer    f20 +1.11% (胜率48%) <- 无效, 不用
        tweezer_bottom              太松(占7.7%K线), 不用
    顶部类 (需配 MACD顶部+收盘>MA60, f20 越低越有效):
        evening_star  f20 -1.93%  <- 最强但仅13次
        bear_engulf   f20 +1.14% (胜率51%)
        hanging_man   f20 +1.03% (胜率53%)
        long_bear     f20 +1.45% (胜率55%)
        bear_three    f20 +2.08% (胜率47%)
        shooting_star f20 +1.58% (胜率50%)
        dark_cloud    f20 +3.46%          <- 比基准还差, 不用
        gravestone    f20 +2.63%          <- 无效, 不用
        tweezer_top                   太松, 不用
"""
from typing import Dict

import pandas as pd


def geometry(dataframe: pd.DataFrame) -> Dict[str, pd.Series]:
    """K线基础几何量: 实体/全幅/上下影线/中点."""
    o, h, l, c = dataframe["open"], dataframe["high"], dataframe["low"], dataframe["close"]
    rng = (h - l).replace(0.0, pd.NA)
    rng_safe = rng.fillna(1.0)
    body = (c - o).abs()
    return {
        "open": o, "high": h, "low": l, "close": c,
        "rng": rng, "rng_safe": rng_safe,
        "body": body,
        "body_ratio": body / rng_safe,
        "upper_shadow": h - pd.concat([o, c], axis=1).max(axis=1),
        "lower_shadow": pd.concat([o, c], axis=1).min(axis=1) - l,
        "mid": (o + c) / 2,
        "bull": (c > o).fillna(False),
        "bear": (c < o).fillna(False),
    }


def detect(dataframe: pd.DataFrame) -> Dict[str, pd.Series]:
    """返回全部形态的 bool Series 字典 (只看当日及以前的K线)."""
    g = geometry(dataframe)
    o, c = g["open"], g["close"]
    body, rng = g["body"], g["rng"]
    rng_safe, bratio = g["rng_safe"], g["body_ratio"]
    us, ls = g["upper_shadow"], g["lower_shadow"]
    mid, bull, bear = g["mid"], g["bull"], g["bear"]

    o1, c1 = o.shift(1), c.shift(1)
    mid1, body1, bratio1 = mid.shift(1), body.shift(1), bratio.shift(1)
    bull1, bear1 = bull.shift(1).fillna(False), bear.shift(1).fillna(False)
    body2, bratio2 = body.shift(2), bratio.shift(2)

    out: Dict[str, pd.Series] = {}

    # ---- 底部/看涨反转 ----
    out["hammer"] = (
        (ls >= 2 * body) & (bratio <= 0.35) & (us <= body)
        & (ls / rng_safe >= 0.35) & bull & (rng > 0)
    )
    out["inverted_hammer"] = (
        (us >= 2 * body) & (bratio <= 0.35) & (ls <= body)
        & (us / rng_safe >= 0.35) & bull & (rng > 0)
    )
    out["bull_engulfing"] = (
        bear1 & bull & (c >= o1) & (o <= c1)
        & (bratio >= 0.5) & (body > body1) & (rng > 0)
    )
    out["piercing"] = (
        bear1 & bull & (o < c1) & (c > mid1) & (c < o1) & (rng > 0)
    )
    out["morning_star"] = (
        bear.shift(2).fillna(False) & (bratio.shift(2) >= 0.6)
        & (bratio.shift(1) <= 0.35)
        & bull & (c > mid.shift(2)) & (rng > 0)
    )
    out["dragonfly"] = (
        (bratio <= 0.12) & (ls / rng_safe >= 0.6) & (ls >= 5 * body) & (rng > 0)
    )
    out["tweezer_bottom"] = (
        ((g["low"] - g["low"].shift(1)).abs() / g["low"].shift(1) <= 0.01) & bull
    )
    out["bull_three_soldiers"] = (
        bull & bull.shift(1).fillna(False) & bull.shift(2).fillna(False)
        & (c > c.shift(1)) & (c.shift(1) > c.shift(2))
        & (bratio >= 0.5) & (g["low"] > g["low"].shift(1))
    )

    # ---- 顶部/看跌反转 ----
    out["hanging_man"] = (
        (ls >= 2 * body) & (bratio <= 0.35) & (us <= body)
        & (ls / rng_safe >= 0.35) & bear & (rng > 0)
    )
    out["shooting_star"] = (
        (us >= 2 * body) & (bratio <= 0.35) & (ls <= body)
        & (us / rng_safe >= 0.35) & bear & (rng > 0)
    )
    out["bear_engulfing"] = (
        bull1 & bear & (c <= o1) & (o >= c1)
        & (bratio >= 0.5) & (body > body1) & (rng > 0)
    )
    out["dark_cloud"] = (
        bull1 & bear & (o > c1) & (c < c1) & (c > mid1) & (rng > 0)
    )
    out["evening_star"] = (
        bull.shift(2).fillna(False) & (bratio.shift(2) >= 0.6)
        & (bratio.shift(1) <= 0.35)
        & bear & (c < mid.shift(2)) & (rng > 0)
    )
    out["gravestone"] = (
        (bratio <= 0.12) & (us / rng_safe >= 0.6) & (us >= 5 * body) & (rng > 0)
    )
    out["tweezer_top"] = (
        ((g["high"] - g["high"].shift(1)).abs() / g["high"].shift(1) <= 0.01) & bear
    )
    out["bear_three_crows"] = (
        bear & bear.shift(1).fillna(False) & bear.shift(2).fillna(False)
        & (c < c.shift(1)) & (c.shift(1) < c.shift(2))
        & (bratio >= 0.5) & (g["low"] < g["low"].shift(1))
    )
    out["long_bear"] = bear & (bratio >= 0.7)

    return {k: v.fillna(False) for k, v in out.items()}


def macd_state(dataframe: pd.DataFrame) -> Dict[str, pd.Series]:
    """MACD 位置/状态: 底部(双负+绿柱收敛)、顶部(双正+红柱收敛)、金叉、死叉."""
    close = dataframe["close"]
    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(
        span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = dif - dea
    return {
        "dif": dif,
        "dea": dea,
        "hist": hist,
        "macd_bottom": ((dif < 0) & (dea < 0) & (hist > hist.shift(1))).fillna(False),
        "macd_top": ((dif > 0) & (dea > 0) & (hist < hist.shift(1))).fillna(False),
        "golden_cross": ((dif > dea) & (dif.shift(1) <= dea.shift(1))).fillna(False),
        "death_cross": ((dif < dea) & (dif.shift(1) >= dea.shift(1))).fillna(False),
    }


def indicator_states(dataframe: pd.DataFrame) -> Dict[str, pd.Series]:
    """均线/MACD/KDJ/BOLL/量 的位置状态, 供形态+指标组合策略使用.

    命名前缀即指标族: ma_ / macd_ / kdj_ / boll_ / vol_.
    背离用10日近似 (价格创新高/低而 DIF 不同步), 不是严格的摆点背离.
    """
    o, h, l, c = dataframe["open"], dataframe["high"], dataframe["low"], dataframe["close"]
    st: Dict[str, pd.Series] = {}

    ma5, ma10 = c.rolling(5).mean(), c.rolling(10).mean()
    ma20, ma60, ma250 = c.rolling(20).mean(), c.rolling(60).mean(), c.rolling(250).mean()
    st["ma_bull_align"] = (ma5 > ma10) & (ma10 > ma20) & (ma20 > ma60)
    st["ma_bear_align"] = (ma5 < ma10) & (ma10 < ma20) & (ma20 < ma60)
    st["ma_below_ma20"] = c < ma20
    st["ma_below_ma60"] = c < ma60
    st["ma_below_ma250"] = c < ma250
    st["ma20_rising"] = ma20 > ma20.shift(5)
    st["ma20_falling"] = ma20 < ma20.shift(5)
    st["ma_pullback"] = (c < ma20) & (c > ma20.shift(10) * 0.97)
    st["ma250_up"] = ma250 > ma250.shift(20)

    dif = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = dif - dea
    st["macd_bottom"] = (dif < 0) & (dea < 0) & (hist > hist.shift(1))
    st["macd_top"] = (dif > 0) & (dea > 0) & (hist < hist.shift(1))
    st["macd_gold"] = (dif > dea) & (dif.shift(1) <= dea.shift(1))
    st["macd_death"] = (dif < dea) & (dif.shift(1) >= dea.shift(1))
    st["macd_hist_up"] = (hist > 0) & (hist.shift(1) <= 0)
    st["macd_hist_dn"] = (hist < 0) & (hist.shift(1) >= 0)
    st["macd_top_div"] = (c > c.shift(10)) & (dif < dif.shift(10))
    st["macd_bot_div"] = (c < c.shift(10)) & (dif > dif.shift(10))

    ll, hh = l.rolling(9).min(), h.rolling(9).max()
    rsv = (c - ll) / (hh - ll) * 100
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    j = 3 * k - 2 * d
    st["kdj_oversold"] = (k < 20) & (d < 20)
    st["kdj_overbought"] = (k > 80) & (d > 80)
    st["kdj_gold"] = (k > d) & (k.shift(1) <= d.shift(1))
    st["kdj_death"] = (k < d) & (k.shift(1) >= d.shift(1))
    st["kdj_gold_low"] = (k > d) & (k.shift(1) <= d.shift(1)) & (k < 20)
    st["kdj_j_below0"] = j < 0
    st["kdj_j_above100"] = j > 100

    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    bw = 4 * sd / mid
    bw_pct = bw.rolling(120, min_periods=40).rank(pct=True)
    st["boll_below_lower"] = c < (mid - 2 * sd)
    st["boll_touch_lower"] = l <= (mid - 2 * sd)
    st["boll_squeeze"] = bw_pct < 0.20
    st["boll_widen"] = bw > bw.shift(10)
    st["boll_cross_mid"] = (c > mid) & (c.shift(1) <= mid.shift(1))

    vol20 = dataframe["volume"].rolling(20).mean()
    st["vol_spike"] = dataframe["volume"] > 1.5 * vol20
    st["vol_dry"] = dataframe["volume"] < 0.7 * vol20

    return {k: v.fillna(False) for k, v in st.items()}


def setup_signal(dataframe: pd.DataFrame, pattern: str, indicator=None) -> pd.Series:
    """单个'形态(+指标)'套装信号: 形态 AND 指标(可空)."""
    sig = detect(dataframe)[pattern]
    if indicator:
        states = indicator_states(dataframe)
        if indicator not in states:
            raise KeyError(f"unknown indicator state: {indicator}")
        sig = sig & states[indicator]
    return sig.fillna(False)