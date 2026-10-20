"""
chan_structure - 缠论结构库 (分型/笔/线段/中枢/背驰/三类买卖点), 纯向量+确定性.

设计原则:
  1. 只用"已确认"的结构: 分型在 i+1 根才确认, 中枢在构成它的第3笔完成时才成立,
     背驰在笔的终点确认 —— 所有信号都无未来函数 (tests/test_chan_structure.py 锁定).
  2. 流派差异做成参数: 笔的严格程度 (min_gap)、中枢构造 (三笔重叠),
     背驰口径 (MACD面积/幅度), 便于做敏感性分析.
  3. 与缠论原文的常见实现保持一致但简化: 线段用"至少3笔 + 方向反转确认"近似,
     不做特征序列的完整分解 (日线级别足够).

术语: 分型=fx, 笔=bi, 线段=duan, 中枢=zd/pivot, 背驰=divergence.
"""
from typing import Dict, List, NamedTuple, Optional

import numpy as np
import pandas as pd


class Bi(NamedTuple):
    """一笔: 从 fx_a 到 fx_b, high/low 为该笔区间."""
    idx_a: int          # 起点分型所在的K线索引
    idx_b: int          # 终点分型所在的K线索引
    conf_idx: int       # 该笔被确认的K线索引 (终点分型的确认点)
    direction: int      # +1 向上, -1 向下
    high: float
    low: float


class Pivot(NamedTuple):
    """中枢: 至少3笔重叠区间."""
    idx_start: int      # 构成中枢的第1笔起点
    idx_end: int        # 中枢最后一次延伸的终点
    conf_idx: int       # 中枢成立(第3笔完成)的索引
    zg: float           # 中枢上沿
    zd: float           # 中枢下沿
    bi_start: int       # 构成中枢的第一笔序号
    bi_end: int         # 中枢最后一笔序号


def get_fractals(high: np.ndarray, low: np.ndarray, strict: bool = True):
    """分型: 中间K线的高点最高(顶)/最低(底). strict=True 用严格不等号."""
    n = len(high)
    tops: List[int] = []
    bottoms: List[int] = []
    for i in range(1, n - 1):
        if strict:
            if high[i] > high[i - 1] and high[i] > high[i + 1]:
                tops.append(i)
            if low[i] < low[i - 1] and low[i] < low[i + 1]:
                bottoms.append(i)
        else:
            if high[i] >= high[i - 1] and high[i] >= high[i + 1] \
                    and (high[i] > high[i - 1] or high[i] > high[i + 1]):
                tops.append(i)
            if low[i] <= low[i - 1] and low[i] <= low[i + 1] \
                    and (low[i] < low[i - 1] or low[i] < low[i + 1]):
                bottoms.append(i)
    return tops, bottoms


def get_bis(df: pd.DataFrame, min_gap: int = 4, strict_fx: bool = True) -> List[Bi]:
    """笔: 连接交替的顶/底分型, 相邻端点至少相隔 min_gap 根K线."""
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    tops, bottoms = get_fractals(high, low, strict=strict_fx)
    # 合并成一条按时间排序的交替序列 (同类型保留更极端的那个)
    events = [(i, 1) for i in tops] + [(i, -1) for i in bottoms]
    events.sort(key=lambda x: (x[0], -x[1]))
    seq: List[tuple] = []
    for idx, typ in events:
        if not seq:
            seq.append((idx, typ))
            continue
        last_idx, last_typ = seq[-1]
        if typ == last_typ:
            # 同类型分型: 取更极端的
            better = (high[idx] > high[last_idx]) if typ == 1 else (low[idx] < low[last_idx])
            if better:
                seq[-1] = (idx, typ)
        else:
            seq.append((idx, typ))
    # 成笔: 端点距离 >= min_gap 且价格方向正确; 不满足则用更极端的同类型端点替换
    bis: List[Bi] = []
    if len(seq) < 2:
        return bis
    anchor = seq[0]
    for cand in seq[1:]:
        if cand[0] - anchor[0] < min_gap:
            # 距离不够: 若同方向更极端, 替换锚点 (同类型时)
            if cand[1] == anchor[1]:
                anchor = cand
            continue
        a_i, a_t = anchor
        b_i, b_t = cand
        direction = 1 if b_t == 1 else -1
        ok = high[b_i] > high[a_i] if direction == 1 else low[b_i] < low[a_i]
        if not ok:
            # 价格未创新极值: 保持锚点
            continue
        bis.append(Bi(idx_a=a_i, idx_b=b_i, conf_idx=b_i + 1, direction=direction,
                      high=float(max(high[a_i:b_i + 1])),
                      low=float(min(low[a_i:b_i + 1]))))
        anchor = cand
    return bis


def get_pivots(df: pd.DataFrame, bis: List[Bi]) -> List[Pivot]:
    """中枢: 连续3笔区间有重叠即成立 (边界冻结, 不做延伸).

    刻意不做"延伸": 延伸与否取决于后续笔, 会让中枢的 ZG/ZD 随未来数据变化
    (无前视测试抓到过这个坑). 冻结后中枢在第3笔完成那根K线即完全确定.
    """
    pivots: List[Pivot] = []
    m = len(bis)
    i = 0
    while i + 2 < m:
        a, b, c = bis[i], bis[i + 1], bis[i + 2]
        zg = min(a.high, b.high, c.high)
        zd = max(a.low, b.low, c.low)
        if zd >= zg:
            i += 1
            continue
        pivots.append(Pivot(idx_start=bis[i].idx_a, idx_end=bis[i + 2].idx_b,
                            conf_idx=bis[i + 2].conf_idx, zg=float(zg), zd=float(zd),
                            bi_start=i, bi_end=i + 2))
        i += 3
    return pivots


def get_segments(bis: List[Bi], min_bis: int = 3) -> List[tuple]:
    """线段(简化): 至少 min_bis 笔同向累积, 遇反向笔且创新极值时切断. 返回 (起点笔序号, 终点笔序号)."""
    segs: List[tuple] = []
    i = 0
    m = len(bis)
    while i < m - 1:
        d = bis[i + 1].direction
        j = i + 1
        while j < m - 1 and bis[j + 1].direction == d and (j - i) < 9:
            j += 1
        if j - i + 1 >= min_bis:
            segs.append((i, j))
            i = j
        else:
            i += 1
    return segs


def macd_area(df: pd.DataFrame) -> pd.Series:
    close = df["close"]
    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    hist = dif - dif.ewm(span=9, adjust=False).mean()
    return hist


def chan_states(dataframe: pd.DataFrame, min_gap: int = 4,
                divergence: str = "area") -> Dict[str, pd.Series]:
    """返回可交易的结构状态序列 (全部在信号确认当日之后才生效)."""
    df = dataframe
    n = len(df)
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    idx = df.index
    empty = pd.Series(False, index=idx)

    bis = get_bis(df, min_gap=min_gap)
    pivots = get_pivots(df, bis)
    hist = macd_area(df)
    hist_v = hist.to_numpy()

    # ---- 中枢状态 (按中枢成立后的每根K线展开) ----
    in_pivot = np.zeros(n, dtype=bool)
    above_pivot = np.zeros(n, dtype=bool)
    below_pivot = np.zeros(n, dtype=bool)
    pivot_width = np.zeros(n)
    pivot_age = np.zeros(n, dtype=int)
    for pv in pivots:
        s, e = pv.conf_idx, n - 1     # 从第3笔确认那根开始, 一直延伸到最后一根
        if s >= n:
            continue
        seg_close = close[s:e + 1]
        in_pivot[s:e + 1] = ((seg_close <= pv.zg) & (seg_close >= pv.zd))
        above_pivot[s:e + 1] = seg_close > pv.zg
        below_pivot[s:e + 1] = seg_close < pv.zd
        pivot_width[s:e + 1] = (pv.zg - pv.zd) / max(pv.zd, 1e-9)
        pivot_age[s:e + 1] = np.arange(e + 1 - s)
    # 三买: 上破中枢后回抽不破上沿 (至少1根确认回抽)
    third_buy = np.zeros(n, dtype=bool)
    third_sell = np.zeros(n, dtype=bool)
    for pv in pivots:
        s = pv.conf_idx
        if s >= n:
            continue
        broke_up = np.where(above_pivot[s:s + 60])[0]
        if len(broke_up):
            b = s + int(broke_up[0])
            back = np.where((np.arange(b + 1, min(n, b + 21)) >= b + 1)
                            & (close[b + 1:min(n, b + 21)] >= pv.zg))[0]
            if len(back):
                third_buy[b + 1 + int(back[0])] = True
        broke_dn = np.where(below_pivot[s:s + 60])[0]
        if len(broke_dn):
            b = s + int(broke_dn[0])
            back = np.where((np.arange(b + 1, min(n, b + 21)) >= b + 1)
                            & (close[b + 1:min(n, b + 21)] <= pv.zd))[0]
            if len(back):
                third_sell[b + 1 + int(back[0])] = True

    # ---- 背驰: 同向两笔比较 (创新极值但MACD面积/幅度更小) ----
    div_bottom = np.zeros(n, dtype=bool)
    div_top = np.zeros(n, dtype=bool)
    for i in range(1, len(bis)):
        cur, prev = bis[i], bis[i - 1]
        if cur.direction != prev.direction:
            continue
        area_cur = float(np.nansum(hist_v[prev.idx_b:cur.idx_b + 1]))
        area_prev = float(np.nansum(hist_v[prev.idx_a:prev.idx_b + 1]))
        amp_cur = abs(cur.high - cur.low)
        amp_prev = abs(prev.high - prev.low)
        if cur.direction == 1:      # 向上笔: 顶背驰
            weaker = (area_cur < area_prev * 0.9) if divergence == "area" else (amp_cur < amp_prev * 0.9)
            if cur.high > prev.high and weaker:
                div_top[cur.conf_idx] = True
        else:                       # 向下笔: 底背驰
            weaker = (area_cur < area_prev * 0.9) if divergence == "area" else (amp_cur < amp_prev * 0.9)
            if cur.low < prev.low and weaker:
                div_bottom[cur.conf_idx] = True

    # ---- 笔方向状态 (只用已确认的笔: 从确认那根开始生效, 下一笔确认后切换) ----
    # 注意: 不能把笔的内部K线都标成该笔方向 —— 笔要等终点分型在 idx_b+1 才确认,
    # 提前标注等于未来函数 (无前视测试抓到过). 正确做法是"最近一笔已确认笔的方向".
    bi_up = np.zeros(n, dtype=bool)
    bi_dn = np.zeros(n, dtype=bool)
    for k, b in enumerate(bis):
        start = b.conf_idx
        end = bis[k + 1].conf_idx if k + 1 < len(bis) else n
        end = min(max(end, start), n)
        if start >= n:
            continue
        if b.direction == 1:
            bi_up[start:end] = True
        else:
            bi_dn[start:end] = True

    return {
        "in_pivot": pd.Series(in_pivot, index=idx),
        "above_pivot": pd.Series(above_pivot, index=idx),
        "below_pivot": pd.Series(below_pivot, index=idx),
        "pivot_width": pd.Series(pivot_width, index=idx),
        "third_buy": pd.Series(third_buy, index=idx),
        "third_sell": pd.Series(third_sell, index=idx),
        "div_bottom": pd.Series(div_bottom, index=idx),
        "div_top": pd.Series(div_top, index=idx),
        "bi_up": pd.Series(bi_up, index=idx),
        "bi_dn": pd.Series(bi_dn, index=idx),
        "n_bis": pd.Series(float(len(bis)), index=idx),
        "n_pivots": pd.Series(float(len(pivots)), index=idx),
    }


def structure_stats(dataframe: pd.DataFrame, min_gap: int = 4) -> dict:
    """诊断: 笔/中枢数量与覆盖率 (用于核对实现是否合理)."""
    df = dataframe
    bis = get_bis(df, min_gap=min_gap)
    pivots = get_pivots(df, bis)
    st = chan_states(df, min_gap=min_gap)
    n = len(df)
    return {
        "bars": n,
        "bis": len(bis),
        "pivots": len(pivots),
        "in_pivot_pct": float(st["in_pivot"].sum() / n * 100),
        "third_buy": int(st["third_buy"].sum()),
        "third_sell": int(st["third_sell"].sum()),
        "div_bottom": int(st["div_bottom"].sum()),
        "div_top": int(st["div_top"].sum()),
    }