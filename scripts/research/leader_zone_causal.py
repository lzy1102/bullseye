"""Causal re-run of the leader-zone dip study.

The first pass (leader_zone.py) used the *whole* box to place the zone edges,
which is lookahead: the box end and its extremes are only known afterwards.
Here every bar only sees the bars since the climax, exactly as a live strategy
would. Same screens, same structure, same 0.2% round trip.

    python3 scripts/research/leader_zone_causal.py --data user_data/data \
        --start 2018-01-01 --end 2026-10-10
"""
import argparse
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from leader_zone import (CLIMAX_NEAR_LOW, CLIMAX_VOL_MULT, DRY_MULT,
                         HORIZONS, ROUND_TRIP, ZONE_MAX_BARS, ZONE_MAX_WIDTH,
                         ZONE_MIN_BARS, load, pivot_zone, screens,
                         volume_profile_zone)


def fwd(c, i, h):
    return np.nan if i + h >= len(c) else c[i + h] / c[i] - 1


def causal_events(d, mask, width=ZONE_MAX_WIDTH, dry=DRY_MULT,
                  vol_mult=CLIMAX_VOL_MULT, near_low=CLIMAX_NEAR_LOW,
                  min_bars=ZONE_MIN_BARS, atr_mult=4.0, spring_atr=1.5,
                  dip_frac=0.33):
    h, l, c, o, v = (d[k].to_numpy(float) for k in
                     ("high", "low", "close", "open", "volume"))
    n = len(c)
    vmed = pd.Series(v).shift(1).rolling(60).median().to_numpy()
    low120 = pd.Series(l).rolling(120).min().to_numpy()
    out = []
    for i in range(130, n - max(HORIZONS) - 2):
        if not mask[i] or vmed[i] <= 0 or v[i] < vol_mult * vmed[i]:
            continue
        if c[i] >= o[i] or c[i] > low120[i] * (1 + near_low):
            continue
        atr = float(np.mean(h[max(0, i - 20):i + 1] - l[max(0, i - 20):i + 1]))
        hi, lo = -np.inf, np.inf
        for j in range(i + 1, min(n, i + 1 + ZONE_MAX_BARS)):
            hi, lo = max(hi, h[j]), min(lo, l[j])
            if lo < l[i] - spring_atr * atr:
                break
            if (hi - lo) / ((hi + lo) / 2) > max(width, atr_mult * atr / c[j]):
                break
            length = j - i
            if length < min_bars:
                continue
            zv = v[i + 1:j + 1]
            if np.median(zv) > dry * v[i]:
                continue
            zones = {"C": (lo, hi)}
            zones["A"] = volume_profile_zone(l[i + 1:j + 1], h[i + 1:j + 1],
                                             c[i + 1:j + 1], zv)
            b = pivot_zone(h[i + 1:j + 1], l[i + 1:j + 1])
            if b is not None:
                zones["B"] = b
            hit = False
            for k, (dn, up) in zones.items():
                if up <= dn or c[j] > dn + dip_frac * (up - dn):
                    continue
                if c[j] <= o[j] and False:
                    continue
                if c[j] > o[j] and v[j] <= dry * v[i]:
                    out.append(dict(kind=k, idx=j))
                    hit = True
            if hit:
                break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="user_data/data")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default="2026-10-10")
    args = ap.parse_args()
    frames = load(args.data, pd.Timestamp(args.start), pd.Timestamp(args.end))
    masks = screens(frames)
    print(f"universe {len(frames)} symbols\n")

    base = {h: [] for h in HORIZONS}
    ev = []
    for s, d in frames.items():
        c = d["close"].to_numpy(float)
        m = masks[s]
        for h in HORIZONS:
            for i in np.flatnonzero(m[:-h]):
                base[h].append(fwd(c, i, h))
        for rec in causal_events(d, m):
            for h in HORIZONS:
                ev.append(dict(symbol=s, kind=rec["kind"], idx=rec["idx"], h=h,
                               ret=fwd(c, rec["idx"], h)))

    print("baseline (screened pool)")
    print(f"{'h':>3} {'n':>7} {'mean%':>7} {'med%':>7} {'win%':>6}")
    for h in HORIZONS:
        b = np.asarray(base[h])
        print(f"{h:>3} {len(b):>7} {100*b.mean():>7.2f} "
              f"{100*np.median(b):>7.2f} {100*np.mean(b>0):>6.1f}")

    df = pd.DataFrame(ev)
    if df.empty:
        print("no events")
        return 0
    for kind in ("A", "B", "C"):
        sub = df[df["kind"] == kind]
        print(f"\n{kind} 因果低吸   events={sub[sub['h']==5].shape[0]}")
        print(f"{'h':>3} {'n':>4} {'mean%':>7} {'med%':>7} {'win%':>6} {'t':>6}")
        for h in HORIZONS:
            x = sub[sub["h"] == h]["ret"].to_numpy()
            x = x[np.isfinite(x)]
            if len(x) < 5:
                print(f"{h:>3} {len(x):>4}   (too few)")
                continue
            t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if x.std(ddof=1) > 0 else 0
            print(f"{h:>3} {len(x):>4} {100*x.mean():>7.2f} {100*np.median(x):>7.2f} "
                  f"{100*np.mean(x>0):>6.1f} {t:>6.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
