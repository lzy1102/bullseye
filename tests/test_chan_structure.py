"""Tests for chan_structure.py: geometry correctness + no-lookahead locks."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from chan_structure import (chan_states, get_bis, get_fractals,  # noqa: E402
                            get_pivots, structure_stats)


def zigzag(n=400, seed=3):
    """Deterministic zigzag: alternating up/down legs with clear pivots."""
    rng = np.random.default_rng(seed)
    close = [100.0]
    leg = 12
    up = True
    while len(close) < n:
        step = leg * (1 + rng.random() * 0.2)
        for _ in range(int(step)):
            prev = close[-1]
            close.append(prev * (1 + 0.01) if up else prev * (1 - 0.01))
        up = not up
    close = np.array(close[:n])
    high = close * 1.008
    low = close * 0.992
    df = pd.DataFrame({
        "date": pd.date_range("2023-01-02", periods=n, freq="B"),
        "open": close, "high": high, "low": low, "close": close,
        "volume": np.full(n, 1e6),
    })
    return df


def test_fractals_on_clean_peak():
    high = [1, 2, 3, 2, 1]
    low = [5, 4, 3, 4, 5]
    tops, bottoms = get_fractals(np.array(high, dtype=float), np.array(low, dtype=float))
    assert tops == [2]
    assert bottoms == [2]


def test_bis_need_min_gap():
    df = zigzag(200)
    for gap in (3, 4, 5, 6):
        bis = get_bis(df, min_gap=gap)
        assert bis, f"no strokes at min_gap={gap}"
        for b in bis:
            assert b.idx_b - b.idx_a >= gap
            assert b.conf_idx == b.idx_b + 1
        # stricter gap -> fewer strokes
        if gap > 3:
            assert len(bis) <= len(get_bis(df, min_gap=gap - 1))


def test_strokes_alternate_and_extend():
    df = zigzag(300)
    bis = get_bis(df, min_gap=4)
    for a, b in zip(bis, bis[1:]):
        assert b.direction == -a.direction      # 顶底交替
        assert b.idx_a == a.idx_b               # 笔首尾相连


def test_pivot_bounds_are_consistent():
    df = zigzag(300)
    bis = get_bis(df, min_gap=4)
    pivots = get_pivots(df, bis)
    assert pivots
    for pv in pivots:
        assert pv.zd < pv.zg
        assert pv.idx_start <= pv.idx_end


def test_no_lookahead_truncation():
    """Signals from a truncated series must match the prefix of the full run."""
    full = zigzag(500)
    for cut in (200, 350):
        trunc = full.iloc[:cut].copy()
        f = chan_states(full, min_gap=5)
        t = chan_states(trunc, min_gap=5)
        for name in ("bi_up", "in_pivot", "third_buy", "third_sell",
                     "div_bottom", "div_top", "above_pivot"):
            a = f[name].iloc[:cut].reset_index(drop=True)
            b = t[name].reset_index(drop=True)
            assert a.equals(b), f"{name} changed when future bars were removed (cut={cut})"


def test_structure_stats_runs():
    st = structure_stats(zigzag(400))
    assert st["bars"] == 400
    assert st["bis"] > 0
    assert 0 <= st["in_pivot_pct"] <= 100


def test_empty_and_short_series():
    tiny = pd.DataFrame({
        "date": pd.date_range("2023-01-02", periods=3, freq="B"),
        "open": [1.0, 1.0, 1.0], "high": [1.0, 1.0, 1.0],
        "low": [1.0, 1.0, 1.0], "close": [1.0, 1.0, 1.0],
        "volume": [0.0, 0.0, 0.0],
    })
    assert get_bis(tiny) == []
    assert get_pivots(tiny, []) == []
    st = chan_states(tiny)
    assert len(st["bi_up"]) == 3
    assert not st["third_buy"].any()