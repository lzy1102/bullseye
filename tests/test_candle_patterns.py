"""
Tests for the candlestick pattern library (user_data/strategies/candle_patterns.py).

Focus: correctness of a handful of hand-built candles, and a hard no-lookahead
guarantee (signals computed on a truncated series must equal the signals computed
on the full series for the same prefix).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from candle_patterns import detect, geometry, indicator_states, macd_state, setup_signal  # noqa: E402


def make_candles(rows):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    df["date"] = pd.date_range("2023-01-02", periods=len(df), freq="B")
    return df


def series(n=400, seed=7):
    rng = np.random.default_rng(seed)
    close = 20 + np.cumsum(rng.normal(0, 0.5, n))
    close = np.maximum(close, 5.0)
    open_ = close + rng.normal(0, 0.15, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.25, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.25, n))
    return make_candles(np.column_stack([open_, high, low, close,
                                         rng.integers(1e6, 5e6, n)]))


# --------------------------------------------------------------------------
# single-candle pattern geometry
# --------------------------------------------------------------------------

def test_hammer_detected():
    # open=close=10 (small body), low=9 (long lower shadow), high=10.2
    df = make_candles([[10.0, 10.2, 9.0, 10.1, 1000.0]])
    pats = detect(df)
    assert bool(pats["hammer"].iloc[0]) is True
    assert bool(pats["bear_engulfing"].iloc[0]) is False


def test_bull_engulfing_detected():
    # day1 bearish, day2 bullish and engulfs day1 body
    df = make_candles([
        [10.5, 10.6, 9.8, 10.0, 1000.0],
        [9.9, 10.8, 9.7, 10.6, 2000.0],
    ])
    pats = detect(df)
    assert bool(pats["bull_engulfing"].iloc[1]) is True
    assert bool(pats["bear_engulfing"].iloc[1]) is False


def test_bear_engulfing_detected():
    df = make_candles([
        [10.0, 10.4, 9.9, 10.3, 1000.0],
        [10.4, 10.5, 9.6, 9.7, 2000.0],
    ])
    pats = detect(df)
    assert bool(pats["bear_engulfing"].iloc[1]) is True


def test_morning_star_detected():
    df = make_candles([
        [11.0, 11.1, 9.9, 10.0, 3000.0],   # long bearish
        [10.0, 10.1, 9.85, 10.02, 500.0],  # tiny body doji
        [10.0, 11.5, 9.95, 11.4, 3000.0],  # long bullish
    ])
    pats = detect(df)
    assert bool(pats["morning_star"].iloc[2]) is True
    assert bool(pats["evening_star"].iloc[2]) is False


def test_hanging_man_is_bearish_hammer():
    # same shape as hammer but bearish -> hanging_man, not hammer
    df = make_candles([[10.1, 10.2, 9.0, 10.0, 1000.0]])
    pats = detect(df)
    assert bool(pats["hanging_man"].iloc[0]) is True
    assert bool(pats["hammer"].iloc[0]) is False


def test_shooting_star_detected():
    df = make_candles([[10.0, 11.0, 9.8, 9.9, 1000.0]])
    pats = detect(df)
    assert bool(pats["shooting_star"].iloc[0]) is True


def test_zero_range_candle_does_not_raise():
    df = make_candles([[10.0, 10.0, 10.0, 10.0, 0.0]])
    pats = detect(df)
    assert not bool(pats["hammer"].iloc[0])


# --------------------------------------------------------------------------
# MACD states
# --------------------------------------------------------------------------

def test_macd_bottom_requires_both_lines_negative():
    df = series(300)
    st = macd_state(df)
    bot = st["macd_bottom"]
    assert not (bot & (df["close"] < 0)).any()
    # every macd_bottom bar must have dif<0 and dea<0
    assert (st["dif"][bot] < 0).all()
    assert (st["dea"][bot] < 0).all()
    top = st["macd_top"]
    assert (st["dif"][top] > 0).all()
    assert (st["dea"][top] > 0).all()


# --------------------------------------------------------------------------
# no-lookahead: truncated series must reproduce the prefix signals exactly
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cut", [120, 220, 320])
def test_detect_has_no_lookahead(cut):
    full = series(400)
    truncated = full.iloc[:cut].copy()
    full_pats = detect(full)
    trunc_pats = detect(truncated)
    for name in full_pats:
        a = full_pats[name].iloc[:cut].reset_index(drop=True)
        b = trunc_pats[name].reset_index(drop=True)
        assert a.equals(b), f"pattern {name} changed when future bars were removed"


@pytest.mark.parametrize("cut", [150, 260])
def test_indicator_states_have_no_lookahead(cut):
    full = series(400)
    truncated = full.iloc[:cut].copy()
    fa, ta = indicator_states(full), indicator_states(truncated)
    for name in fa:
        if not isinstance(fa[name], pd.Series) or fa[name].dtype != bool:
            continue
        a = fa[name].iloc[:cut].reset_index(drop=True)
        b = ta[name].reset_index(drop=True)
        assert a.equals(b), f"indicator {name} changed when future bars were removed"


def test_setup_signal_is_conjunction():
    df = series(300)
    pat = detect(df)["hammer"]
    ind = indicator_states(df)["vol_dry"]
    combined = setup_signal(df, "hammer", "vol_dry")
    assert bool((combined & ~(pat & ind)).sum()) == 0
    assert bool((combined & ~pat).sum()) == 0
    assert bool((combined & ~ind).sum()) == 0


def test_setup_signal_rejects_unknown_indicator():
    df = series(60)
    with pytest.raises(KeyError):
        setup_signal(df, "hammer", "not_a_real_state")


def test_macd_state_no_lookahead():
    full = series(300)
    truncated = full.iloc[:200].copy()
    fs, ts = macd_state(full), macd_state(truncated)
    for name in ("dif", "dea", "hist", "macd_bottom", "macd_top"):
        a = fs[name].iloc[:200].reset_index(drop=True)
        b = ts[name].reset_index(drop=True)
        assert a.equals(b), f"macd field {name} changed when future bars were removed"