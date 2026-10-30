"""Breakout -> first holding pullback, on a generic contraction box (causal).

The climax+box version had only 5-24 events in 8 years, too few to read. This
drops the volume-climax precondition and defines the box as the last 20 bars,
optionally filtered to a volatility contraction (the "coiled" case). Still
causal: the level is the high of the 20 bars before the breakout bar.

    python3 scripts/research/breakout_retest_simple.py --data user_data/data \
        --start 2018-01-01 --end 2026-10-10
"""
import argparse
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from leader_zone import load, screens

HORIZONS = (3, 5, 10, 20, 40)
BOX = 20


def fwd(c, i, h):
    return np.nan if i + h >= len(c) else c[i + h] / c[i] - 1


def events(d, mask, contraction=True, width_pct=0.50, touch_tol=0.01,
           retest_win=10, brk_vol=1.2, retest=True):
    h, l, c, o, v = (d[k].to_numpy(float) for k in
                     ("high", "low", "close", "open", "volume"))
    n = len(c)
    lvl = pd.Series(h).shift(1).rolling(BOX).max().to_numpy()
    lo = pd.Series(l).shift(1).rolling(BOX).min().to_numpy()
    width = (lvl - lo) / ((lvl + lo) / 2)
    wrank = pd.Series(width).rolling(100).rank(pct=True).to_numpy()
    vmed = pd.Series(v).shift(1).rolling(20).median().to_numpy()
    out = []
    last = -99
    for b in range(BOX + 100, n - max(HORIZONS) - 2):
        if not mask[b] or not np.isfinite(lvl[b]) or not np.isfinite(width[b]):
            continue
        if contraction and not (wrank[b] <= width_pct):
            continue
        if c[b] <= lvl[b] or vmed[b] <= 0 or v[b] < brk_vol * vmed[b]:
            continue
        if b - last < 1.4 * 10:
            continue
        level = lvl[b]
        if not retest:
            out.append(dict(breakout=b, entry=b))
            last = b
            continue
        for k in range(b + 1, min(n, b + 1 + retest_win)):
            if c[k] < level * 0.98:               # fell back into the box
                break
            if l[k] <= level * (1 + touch_tol) and c[k] > level:
                out.append(dict(breakout=b, entry=k))
                last = k
                break
    return out


def run(frames, masks, **kw):
    ev = []
    for s, d in frames.items():
        for e in events(d, masks[s], **kw):
            ev.append({**e, "sym": s})
    return ev


def show(ev, frames, label):
    print(f"\n=== {label} (events={len(ev)}) ===")
    print(f"{'h':>3} {'n':>5} {'mean%':>7} {'med%':>7} {'win%':>6} {'t':>6}")
    for h in HORIZONS:
        vals = [fwd(frames[e["sym"]]["close"].to_numpy(float), e["entry"], h)
                for e in ev]
        x = np.asarray([v for v in vals if np.isfinite(v)])
        if len(x) < 5:
            print(f"{h:>3} {len(x):>5}   (too few)")
            continue
        t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if x.std(ddof=1) > 0 else 0
        print(f"{h:>3} {len(x):>5} {100*x.mean():>7.2f} {100*np.median(x):>7.2f} "
              f"{100*np.mean(x>0):>6.1f} {t:>6.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="user_data/data")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default="2026-10-10")
    args = ap.parse_args()
    frames = load(args.data, pd.Timestamp(args.start), pd.Timestamp(args.end))
    masks = screens(frames)
    print(f"universe {len(frames)} symbols")

    base = {h: [] for h in HORIZONS}
    for s, d in frames.items():
        c = d["close"].to_numpy(float)
        m = masks[s]
        for h in HORIZONS:
            for i in np.flatnonzero(m[:-h]):
                base[h].append(fwd(c, i, h))
    print("\nbaseline (screened pool)")
    print(f"{'h':>3} {'n':>7} {'mean%':>7} {'med%':>7} {'win%':>6}")
    for h in HORIZONS:
        b = np.asarray(base[h])
        print(f"{h:>3} {len(b):>7} {100*b.mean():>7.2f} "
              f"{100*np.median(b):>7.2f} {100*np.mean(b>0):>6.1f}")

    for name, kw in [
        ("coil50_tol1", dict(contraction=True, width_pct=0.50, touch_tol=0.01)),
        ("coil30_tol1", dict(contraction=True, width_pct=0.30, touch_tol=0.01)),
        ("coil50_tol2", dict(contraction=True, width_pct=0.50, touch_tol=0.02)),
        ("coil50_tol0", dict(contraction=True, width_pct=0.50, touch_tol=0.00)),
        ("nocoil_tol1", dict(contraction=False, touch_tol=0.01)),
        ("brk_only_coil", dict(contraction=True, width_pct=0.50, retest=False)),
        ("brk_only_nocoil", dict(contraction=False, retest=False)),
        ("coil50_win5", dict(contraction=True, width_pct=0.50, touch_tol=0.01,
                             retest_win=5)),
        ("coil50_win20", dict(contraction=True, width_pct=0.50, touch_tol=0.01,
                              retest_win=20)),
    ]:
        show(run(frames, masks, **kw), frames, name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
