"""Leader + 跌少涨多 screen, then a Wyckoff-style accumulation zone.

User's thesis: (1) leaders only - large, liquid, watched; (2) long-run they fall
less than they rise, otherwise skip; (3) at a bottom they print a volume climax,
then consolidate in a structural zone, then mark up. Buy the zone.

Two questions this answers:
  * does the three-segment structure (climax -> dry-up box -> expansion) beat
    the cost line on a *screened* pool, and
  * how should the zone be defined: A) volume profile (POC band), B) swing
    pivots, C) plain Donchian box.

Entry variants are tested separately because they have opposite payoff shapes:
breakout (upper edge + volume) vs dip-buy (lower third + bullish + dry volume).

Event study first - no strategy until a signal clears 0.2% round trip.

    python3 scripts/research/leader_zone.py --data user_data/data \
        --start 2018-01-01 --end 2026-10-10
"""
import argparse
import glob
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HORIZONS = (5, 10, 20, 40)
ROUND_TRIP = 0.002
ZONE_MAX_WIDTH = 0.25
ZONE_MIN_BARS = 15
ZONE_MAX_BARS = 40
CLIMAX_VOL_MULT = 2.5
CLIMAX_NEAR_LOW = 0.25
BREAK_VOL_MULT = 1.3
DRY_MULT = 0.60


def load(data_dir, start, end):
    out = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "*-1d.parquet"))):
        sym = os.path.basename(path)[:-len("-1d.parquet")]
        if not (sym.endswith(".SH") or sym.endswith(".SZ")) or sym == "000300.SH":
            continue
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        need = {"date", "open", "high", "low", "close", "volume", "turn"}
        if not need <= set(df.columns):
            continue
        df["date"] = pd.to_datetime(df["date"])
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        df = df[df["volume"] > 0]
        if "isST" in df:
            df = df[df["isST"].fillna(0) == 0]
        if len(df) < 600:
            continue
        out[sym] = df.reset_index(drop=True)
    return out


def screens(frames, liq_rank=0.50, min_turn=0.30, min_ratio=1.0, max_dd=0.50,
            min_bars=250):
    """Point-in-time mask: liquid enough + rises more than it falls."""
    amt = {}
    turn = {}
    for s, d in frames.items():
        amt[s] = pd.Series(d["close"].to_numpy() * d["volume"].to_numpy() * 100,
                           index=pd.DatetimeIndex(d["date"]), name=s)
        turn[s] = pd.Series(d["turn"].to_numpy(),
                            index=pd.DatetimeIndex(d["date"]), name=s)
    amount = pd.DataFrame(amt).sort_index().rolling(20).median()
    turnover = pd.DataFrame(turn).sort_index().rolling(20).mean()
    liq = amount.rank(axis=1, pct=True) >= liq_rank
    liq &= turnover >= min_turn

    masks = {}
    for s, d in frames.items():
        lr = np.log(d["close"]).diff()
        pos = lr.clip(lower=0).rolling(250).sum()
        neg = (-lr.clip(upper=0)).rolling(250).sum()
        ratio = pos / neg.replace(0, np.nan)
        roll_max = d["close"].rolling(500, min_periods=min_bars).max()
        mdd = (d["close"] / roll_max - 1).rolling(500, min_periods=min_bars).min()
        ok = (ratio >= min_ratio) & (mdd >= -max_dd)
        m = liq[s].reindex(pd.DatetimeIndex(d["date"])).fillna(False).to_numpy()
        masks[s] = m & ok.fillna(False).to_numpy() & (np.arange(len(d)) >= min_bars)
    return masks


def volume_profile_zone(low, high, close, vol, bins=20, coverage=0.70):
    """A) Widest-density price band holding `coverage` of the window's volume."""
    lo, hi = float(np.min(low)), float(np.max(high))
    if hi <= lo:
        return lo, hi
    edges = np.linspace(lo, hi, bins + 1)
    tp = (low + high + close) / 3.0
    idx = np.clip(np.digitize(tp, edges) - 1, 0, bins - 1)
    hist = np.bincount(idx, weights=vol, minlength=bins)
    total = hist.sum()
    if total <= 0:
        return lo, hi
    # greedily add the heaviest bin, then its neighbours, until coverage met
    order = np.argsort(hist)[::-1]
    chosen = np.zeros(bins, dtype=bool)
    acc = 0.0
    for b in order:
        if acc / total >= coverage:
            break
        chosen[b] = True
        acc += hist[b]
    sel = np.flatnonzero(chosen)
    return float(edges[sel.min()]), float(edges[sel.max() + 1])


def pivot_zone(high, low, k=3, tol=0.02):
    """B) Cluster swing highs/lows; need two touches on each side."""
    n = len(high)
    ph, pl = [], []
    for i in range(k, n - k):
        if high[i] == np.max(high[i - k:i + k + 1]):
            ph.append(high[i])
        if low[i] == np.min(low[i - k:i + k + 1]):
            pl.append(low[i])
    if len(ph) < 2 or len(pl) < 2:
        return None
    up = float(np.median([h for h in ph if h >= np.median(ph)]))
    dn = float(np.median([l for l in pl if l <= np.median(pl)]))
    if up <= dn:
        return None
    touched_up = sum(1 for h in ph if abs(h - up) / up <= tol)
    touched_dn = sum(1 for l in pl if abs(l - dn) / up <= tol)
    if touched_up < 2 or touched_dn < 2:
        return None
    return dn, up


def find_events(d, mask, width=ZONE_MAX_WIDTH, dry=DRY_MULT,
                vol_mult=CLIMAX_VOL_MULT, near_low=CLIMAX_NEAR_LOW,
                min_bars=ZONE_MIN_BARS, atr_mult=4.0, spring_atr=1.5):
    """Climax -> dry-up box -> zone. Yields zone/event records."""
    h, l, c, o, v = (d[k].to_numpy(float) for k in ("high", "low", "close", "open", "volume"))
    n = len(c)
    vmed60 = pd.Series(v).shift(1).rolling(60).median().to_numpy()
    low120 = pd.Series(l).rolling(120).min().to_numpy()
    rows = []
    next_free = 0
    for i in range(130, n - ZONE_MAX_BARS - 40 - max(HORIZONS) - 2):
        if i < next_free or not mask[i]:
            continue
        if not (vmed60[i] > 0 and v[i] >= vol_mult * vmed60[i]):
            continue
        if c[i] >= o[i]:                      # climax must be a down day
            continue
        if c[i] > low120[i] * (1 + near_low):
            continue
        box_vol = float(v[i])                    # the climax bar itself
        atr20 = float(np.mean(h[max(0, i - 20):i + 1] - l[max(0, i - 20):i + 1]))
        width_limit = max(width, atr_mult * atr20 / c[i])
        # expand the box from i+1 until it gets too wide or too long
        hi = -np.inf
        lo = np.inf
        end = None
        for j in range(i + 1, min(n, i + 1 + ZONE_MAX_BARS)):
            hi = max(hi, h[j])
            lo = min(lo, l[j])
            # a spring may undercut the climax low a little; a real breakdown
            # (more than `spring_atr` ATR) invalidates the base
            if lo < l[i] - spring_atr * atr20:
                break
            span = (hi - lo) / ((hi + lo) / 2)
            if span > width_limit:
                break
            if j - i >= min_bars:
                end = j
        if end is None:
            continue
        sl = slice(i + 1, end + 1)
        zh, zl = h[sl], l[sl]
        zc, zv = c[sl], v[sl]
        if np.median(zv) > dry * box_vol:        # dry-up, not distribution
            continue
        zone = {}
        zone["C"] = (float(zl.min()), float(zh.max()))
        zone["A"] = volume_profile_zone(zl, zh, zc, zv)
        b = pivot_zone(zh, zl)
        if b is not None:
            zone["B"] = b
        zone_vol_med = float(np.median(zv))
        rec = {"climax_i": i, "zone_end": end, "zone_vol": zone_vol_med}
        for name, (dn, up) in zone.items():
            if up <= dn:
                continue
            # breakout: first close above the upper edge with expansion volume
            for j in range(end + 1, min(n, end + 1 + 40)):
                if c[j] > up and v[j] >= BREAK_VOL_MULT * zone_vol_med:
                    rec[f"{name}_break"] = j
                    break
            # dip-buy: first bullish bar in the lower third *inside* the zone
            for j in range(i + 1, end + 1):
                if c[j] <= dn + 0.33 * (up - dn) and c[j] > o[j] and v[j] <= zone_vol_med:
                    rec[f"{name}_dip"] = j
                    break
        rows.append(rec)
        next_free = end + 1
    return rows


def fwd(c, i, h):
    if i + h >= len(c):
        return np.nan
    return c[i + h] / c[i] - 1


def dedup(events, key, h):
    events = sorted(events, key=lambda e: e[key])
    keep, last = [], None
    for e in events:
        if last is None or e[key] - last >= h * 1.4:
            keep.append(e)
            last = e[key]
    return events if h == 0 else keep


def stat(vals):
    x = np.asarray([v for v in vals if np.isfinite(v)])
    if len(x) < 5:
        return None
    sd = np.std(x, ddof=1)
    return dict(n=len(x), mean=float(np.mean(x)), median=float(np.median(x)),
                win=float(np.mean(x > 0)),
                t=float(np.mean(x) / (sd / np.sqrt(len(x)))) if sd > 0 else 0.0,
                net=float(np.mean(x)) - ROUND_TRIP)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="user_data/data")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default="2026-10-10")
    ap.add_argument("--diag", action="store_true")
    ap.add_argument("--zone-width", type=float, dest="zone_width", default=ZONE_MAX_WIDTH)
    ap.add_argument("--zone-min", type=int, dest="zone_min", default=ZONE_MIN_BARS)
    ap.add_argument("--dry-mult", type=float, dest="dry_mult", default=DRY_MULT)
    ap.add_argument("--vol-mult", type=float, dest="vol_mult", default=CLIMAX_VOL_MULT)
    ap.add_argument("--near-low", type=float, dest="near_low", default=CLIMAX_NEAR_LOW)
    args = ap.parse_args()

    frames = load(args.data, pd.Timestamp(args.start), pd.Timestamp(args.end))
    masks = screens(frames)
    avg_pool = np.mean([m.sum() for m in masks.values()])
    print(f"universe {len(frames)} symbols, avg screened pool {avg_pool:.0f}/day\n")

    # screened-pool baseline
    base = {h: [] for h in HORIZONS}
    for s, d in frames.items():
        c = d["close"].to_numpy(float)
        m = masks[s]
        for h in HORIZONS:
            for i in np.flatnonzero(m[:-h]):
                base[h].append(fwd(c, i, h))
    print("baseline (screened pool, all bars)")
    print(f"{'h':>3} {'n':>7} {'mean%':>7} {'med%':>7} {'win%':>6}")
    for h in HORIZONS:
        b = np.asarray(base[h])
        print(f"{h:>3} {len(b):>7} {100*b.mean():>7.2f} {100*np.median(b):>7.2f} "
              f"{100*np.mean(b>0):>6.1f}")

    climax = zones = 0
    events = []
    for s, d in frames.items():
        c = d["close"].to_numpy(float)
        for rec in find_events(d, masks[s], width=args.zone_width,
                               dry=args.dry_mult, vol_mult=args.vol_mult,
                               near_low=args.near_low, min_bars=args.zone_min):
            climax += 1
            zones += 1
            for h in HORIZONS:
                for kind in ("C", "A", "B"):
                    for entry in ("break", "dip"):
                        j = rec.get(f"{kind}_{entry}")
                        if j is None:
                            continue
                        events.append(dict(symbol=s, kind=kind, entry=entry, h=h, idx=j,
                                           ret=fwd(c, j, h)))
    print(f"\nclimax events {climax}, valid zones {zones}, "
          f"signals {len(events)//len(HORIZONS)}")

    ev = pd.DataFrame(events)
    if ev.empty:
        print("no signals at all")
        return 0
    for kind_name, label in (("C", "C 箱体(Donchian)"), ("A", "A 成交密集区(POC)"),
                             ("B", "B 摆动结构(pivot)")):
        for entry in ("break", "dip"):
            sub = ev[(ev["kind"] == kind_name) & (ev["entry"] == entry)]
            # one signal per symbol per h bars: overlapping windows are not
            # independent samples and would inflate the t-stat
            kept = []
            for (_sym, _h), grp in sub.groupby(["symbol", "h"]):
                last = None
                for _, r in grp.sort_values("idx").iterrows():
                    if last is None or r["idx"] - last >= 1.4 * r["h"]:
                        kept.append(r)
                        last = r["idx"]
            sub = pd.DataFrame(kept)
            if sub.empty:
                print(f"\n{label} / {entry}: no signals")
                continue
            print(f"\n{label} / {'突破' if entry == 'break' else '低吸'}")
            print(f"{'h':>3} {'n':>4} {'mean%':>7} {'med%':>7} {'win%':>6} "
                  f"{'t':>6} {'net%':>7}")
            for h in HORIZONS:
                vals = sub[sub["h"] == h]["ret"].tolist()
                st = stat(vals)
                if st is None:
                    print(f"{h:>3} {len(vals):>4}   (too few)")
                    continue
                print(f"{h:>3} {st['n']:>4} {100*st['mean']:>7.2f} "
                      f"{100*st['median']:>7.2f} {100*st['win']:>6.1f} "
                      f"{st['t']:>6.2f} {100*st['net']:>7.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
