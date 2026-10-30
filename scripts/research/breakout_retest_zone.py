"""Box breakout -> first pullback that holds above the box top (causal).

The user's refinement of the accumulation idea: do not buy inside the box (that
lost once made causal), and do not chase the breakout (that lost too) - wait for
the breakout, then buy the first pullback that does not fall back into the box.

Everything here is causal: the box is grown bar by bar from the climax; at a
breakout bar the level is the high of the bars *before* it; the retest must be
a later bar that closes back above the level.

Variants: how far the pullback may undercut the level (touch tolerance),
whether the pullback must be on dry volume, and the retest window.

    python3 scripts/research/breakout_retest_zone.py --data user_data/data \
        --start 2018-01-01 --end 2026-10-10
"""
import argparse
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from leader_zone import HORIZONS, load, screens

CLIMAX_VOL = 2.5
NEAR_LOW = 0.25
ZONE_WIDTH = 0.25
ATR_MULT = 4.0
SPRING_ATR = 1.5
DRY_MULT = 0.60
MIN_BARS = 15
MAX_BARS = 40


def fwd(c, i, h):
    return np.nan if i + h >= len(c) else c[i + h] / c[i] - 1


def events(d, mask, touch_tol=0.01, retest_win=10, brk_vol=1.3,
           dry_pullback=False, allow_under=True):
    h, l, c, o, v = (d[k].to_numpy(float) for k in
                     ("high", "low", "close", "open", "volume"))
    n = len(c)
    vmed = pd.Series(v).shift(1).rolling(60).median().to_numpy()
    low120 = pd.Series(l).rolling(120).min().to_numpy()
    out = []
    for i in range(130, n - MAX_BARS - 40 - max(HORIZONS) - 2):
        if not mask[i] or vmed[i] <= 0 or v[i] < CLIMAX_VOL * vmed[i]:
            continue
        if c[i] >= o[i] or c[i] > low120[i] * (1 + NEAR_LOW):
            continue
        atr = float(np.mean(h[max(0, i - 20):i + 1] - l[max(0, i - 20):i + 1]))
        hi, lo = -np.inf, np.inf          # box of bars i+1..j-1
        start = i + 1
        ready = False                     # box has >=MIN_BARS bars and is dry
        for j in range(i + 1, min(n, i + 1 + MAX_BARS + 40)):
            length = j - start
            # 1) breakout of the box that existed before this bar
            if ready and length >= MIN_BARS and c[j] > hi:
                zv = v[start:j]
                zmed = float(np.median(zv))
                if v[j] >= brk_vol * zmed:
                    level = hi
                    # 2) first pullback that holds above the level
                    for k in range(j + 1, min(n, j + 1 + retest_win)):
                        if c[k] < level * (1 - 0.02):      # closed back inside
                            break
                        floor = level * (1 - touch_tol) if allow_under else level
                        touched = l[k] <= floor * 1.0001
                        holds = c[k] > level
                        dry = (not dry_pullback) or (v[k] <= zmed)
                        if touched and holds and dry:
                            out.append(dict(climax=i, breakout=j, entry=k,
                                            level=level))
                            break
                    break
            # 3) grow the box (this bar is inside it)
            hi = max(hi, h[j])
            lo = min(lo, l[j])
            if lo < l[i] - SPRING_ATR * atr:
                break
            if (hi - lo) / ((hi + lo) / 2) > max(ZONE_WIDTH, ATR_MULT * atr / c[j]):
                break
            if length >= MIN_BARS:
                zv = v[start:j + 1]
                if np.median(zv) <= DRY_MULT * v[i]:
                    ready = True
    return out


def report(ev, frames, masks, label):
    print(f"\n=== {label} ===")
    print(f"{'h':>3} {'n':>4} {'mean%':>7} {'med%':>7} {'win%':>6} {'t':>6} {'net%':>7}")
    for h in HORIZONS:
        vals = []
        for e in ev:
            c = frames[e["sym"]]["close"].to_numpy(float)
            v = fwd(c, e["entry"], h)
            if np.isfinite(v):
                vals.append(v)
        x = np.asarray(vals)
        if len(x) < 5:
            print(f"{h:>3} {len(x):>4}   (too few)")
            continue
        t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if x.std(ddof=1) > 0 else 0
        print(f"{h:>3} {len(x):>4} {100*x.mean():>7.2f} {100*np.median(x):>7.2f} "
              f"{100*np.mean(x>0):>6.1f} {t:>6.2f} {100*x.mean()-0.2:>7.2f}")


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

    configs = [
        ("touch1%", dict(touch_tol=0.01)),
        ("touch2%", dict(touch_tol=0.02)),
        ("touch3%", dict(touch_tol=0.03)),
        ("no_under", dict(touch_tol=0.0, allow_under=False)),
        ("dry_pull", dict(touch_tol=0.02, dry_pullback=True)),
        ("win5", dict(touch_tol=0.02, retest_win=5)),
        ("win20", dict(touch_tol=0.02, retest_win=20)),
    ]
    for name, kw in configs:
        ev = []
        for s, d in frames.items():
            for e in events(d, masks[s], **kw):
                ev.append({**e, "sym": s})
        report(ev, frames, masks, f"{name}  (events={len(ev)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
