"""Port the crypto (Freqtrade) findings to A-share daily bars: event study first.

The docs closed several crypto lines, but the *portable* findings were never
re-tested on A-shares:

  docs/SqueezeBreakout_实验归档.md      squeeze breakout, dead at 15m due to
                                        cost/magnitude - does daily survive?
  docs/趋势跟随与中长线策略实验归档.md   Donchian breakout + volume>=1.5x median
                                        was the only effective enhancement;
                                        break-retest showed adverse selection
  docs/趋势跟随与中长线策略实验归档.md   bottom compression: rare but catches
                                        historic bottoms on majors
  docs/FreqAI_MLpilot_结果.md           direction is unlearnable; volatility is
                                        highly learnable (IC 0.30)

A-shares are long-only and T+1, so only the long side of each setup is
actionable - the crypto studies also measured shorts, we cannot.

Method: exactly the autopsy the docs used before building a strategy - forward
close-to-close returns after each event, vs the A-share baseline. Round-trip
cost 0.2% (0.1%/side). No strategy is written until a signal clears the cost
line with a t-stat that is not noise.

Run (data lives on the 70 host):
    python3 scripts/research/freqtrade_port_events.py \
        --data user_data/data --start 2023-01-01 --end 2026-10-10
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

HORIZONS = (1, 3, 5, 10, 20)
ROUND_TRIP = 0.002


def load_universe(data_dir, start, end):
    frames = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "*-1d.parquet"))):
        sym = os.path.basename(path)[:-len("-1d.parquet")]
        if not (sym.endswith(".SH") or sym.endswith(".SZ")):
            continue
        try:
            df = pd.read_parquet(path, columns=["date", "open", "high", "low",
                                                "close", "volume", "turn", "isST"])
        except Exception:
            continue
        df["date"] = pd.to_datetime(df["date"])
        df = df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)
        if len(df) < 260:
            continue
        df = df[(df["volume"] > 0) & (df["isST"].fillna(0) == 0)]
        if len(df) < 260:
            continue
        frames[sym] = df.reset_index(drop=True)
    return frames


def features(df):
    c, h, v = df["close"], df["high"], df["volume"]
    out = df.copy()
    ma20 = c.rolling(20).mean()
    sd20 = c.rolling(20).std()
    out["bb_up"] = ma20 + 2 * sd20
    out["bw"] = (4 * sd20) / ma20
    out["bw_pct"] = out["bw"].rolling(100).rank(pct=True)
    out["don20"] = h.shift(1).rolling(20).max()
    out["vol_med"] = v.shift(1).rolling(96).median()
    out["vol_ratio"] = v / out["vol_med"]
    for n in (5, 10, 20):
        out[f"ma{n}"] = c.rolling(n).mean()
    out["ma_spread"] = ((out[["ma5", "ma10", "ma20"]].max(axis=1)
                         - out[["ma5", "ma10", "ma20"]].min(axis=1))
                        / out["ma20"])
    out["box_hi"] = h.shift(1).rolling(15).max()
    out["box_lo"] = df["low"].shift(1).rolling(15).min()
    out["ret60"] = c / c.shift(60) - 1
    out["atr"] = (h - df["low"]).rolling(14).mean() / c
    return out


def events_squeeze(df):
    """BB squeeze within the last 3 bars, close breaks the upper band, expanding."""
    sq = (df["bw_pct"] <= 0.20).rolling(3).max().fillna(0).astype(bool)
    brk = df["close"] > df["bb_up"]
    expand = df["bw"] > df["bw"].shift(1)
    return (sq & brk & expand).fillna(False)


def events_donchian(df, vol_mult=0.0):
    brk = df["close"] > df["don20"]
    if vol_mult > 0:
        brk = brk & (df["vol_ratio"] >= vol_mult)
    return brk.fillna(False)


def events_bottom_compression(df):
    """Long downtrend -> flat base with converged MAs -> break the box."""
    prior_down = df["ret60"] <= -0.08
    squash = df["ma_spread"] <= 0.03
    box = (df["box_hi"] - df["box_lo"]) / df["box_lo"] <= 0.15
    brk = df["close"] > df["box_hi"]
    return (prior_down & squash & box & brk).fillna(False)


def events_break_retest(df, window=10, tol=0.01):
    """Donchian break, then a pullback to the level within `window` bars."""
    lvl = df["don20"]
    broke = (df["close"] > lvl).fillna(False).to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    lv = lvl.to_numpy()
    out = np.zeros(len(df), dtype=bool)
    pending = -1
    for i in range(len(df)):
        if broke[i]:
            pending = i
            continue
        if pending >= 0:
            if i - pending > window:
                pending = -1
            elif low[i] <= lv[pending] * (1 + tol) and close[i] > lv[pending]:
                out[i] = True
                pending = -1
    return pd.Series(out, index=df.index)


EVENT_SETS = {
    "squeeze_break": events_squeeze,
    "don20_break": lambda d: events_donchian(d, 0.0),
    "don20_break_vol1.5": lambda d: events_donchian(d, 1.5),
    "don20_break_vol2.0": lambda d: events_donchian(d, 2.0),
    "bottom_compression": events_bottom_compression,
    "break_retest": events_break_retest,
}


def collect(frames, fn):
    rows = []
    for sym, raw in frames.items():
        df = features(raw)
        mask = fn(df).fillna(False).to_numpy()
        close = df["close"].to_numpy()
        n = len(close)
        for i in np.flatnonzero(mask):
            if i + max(HORIZONS) >= n:
                continue
            rec = {"symbol": sym, "date": df["date"].iloc[i],
                   "atr": df["atr"].iloc[i], "vol_ratio": df["vol_ratio"].iloc[i]}
            for h in HORIZONS:
                rec[f"f{h}"] = close[i + h] / close[i] - 1
            rows.append(rec)
    return pd.DataFrame(rows)


def dedup_cooldown(df, h):
    """One event per symbol per h bars: overlapping windows are not independent
    samples and would inflate the t-stat."""
    if df.empty:
        return df
    keep = []
    for _, grp in df.sort_values("date").groupby("symbol"):
        last = None
        for idx, row in grp.iterrows():
            if last is None or (row["date"] - last).days >= h * 1.4:
                keep.append(idx)
                last = row["date"]
    return df.loc[keep]


def baseline(frames):
    vals = {}
    for h in HORIZONS:
        acc = []
        for raw in frames.values():
            c = raw["close"].to_numpy()
            if len(c) > h:
                acc.append(c[h:] / c[:-h] - 1)
        vals[f"f{h}"] = np.concatenate(acc) if acc else np.array([])
    return vals


def stats(sub, h):
    col = f"f{h}"
    if sub.empty:
        return dict(n=0, mean=float("nan"), median=float("nan"),
                    win=float("nan"), t=0.0, net=float("nan"))
    x = sub[col].to_numpy()
    n = len(x)
    mean = float(np.mean(x))
    sd = float(np.std(x, ddof=1)) if n > 2 else 0.0
    t = mean / (sd / np.sqrt(n)) if sd > 0 and n > 2 else 0.0
    return dict(n=n, mean=mean, median=float(np.median(x)),
                win=float(np.mean(x > 0)), t=t, net=mean - ROUND_TRIP)


def rule_pool(frames, top_n):
    """Point-in-time cap pool: 流通市值 ~ close * volume * 100 / turn.

    Ranked at each quarter-end and applied to the *next* quarter, so selection
    never looks ahead.
    """
    caps = {}
    for sym, df in frames.items():
        turn = df["turn"].where(df["turn"] > 0)
        cap = (df["close"] * df["volume"] * 100 / turn).to_numpy()
        caps[sym] = pd.Series(cap, index=pd.DatetimeIndex(df["date"]), name=sym)
    cap = pd.DataFrame(caps).sort_index()
    qe = cap.groupby(cap.index.to_period("Q")).tail(1).sort_index()
    dates = list(qe.index)
    windows = []
    for i in range(len(dates) - 1):
        row = qe.loc[dates[i]].dropna()
        if row.empty:
            continue
        windows.append((dates[i], dates[i + 1], set(row.nlargest(top_n).index)))

    out = {}
    for sym, df in frames.items():
        keep = pd.Series(False, index=df.index)
        for start, end, chosen in windows:
            if sym not in chosen:
                continue
            keep |= (df["date"] >= start) & (df["date"] < end)
        sub = df[keep.to_numpy()].reset_index(drop=True)
        if len(sub) >= 260:
            out[sym] = sub
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="user_data/data")
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2026-10-10")
    ap.add_argument("--pool", default="all", choices=("all", "top"))
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    frames = load_universe(args.data, pd.Timestamp(args.start), pd.Timestamp(args.end))
    if args.pool == "top":
        frames = rule_pool(frames, args.top)
    print(f"universe: {len(frames)} symbols, {args.start}..{args.end}, pool={args.pool}\n")

    base = baseline(frames)
    print("baseline (all bars, close-to-close)")
    print(f"{'h':>4} {'mean%':>8} {'median%':>8} {'win%':>7}")
    for h in HORIZONS:
        b = base[f"f{h}"]
        print(f"{h:>4} {100*b.mean():>8.2f} {100*np.median(b):>8.2f} "
              f"{100*np.mean(b>0):>7.1f}")

    summary = {}
    for name, fn in EVENT_SETS.items():
        ev = collect(frames, fn)
        print(f"\n=== {name} :: raw events {len(ev)} ===")
        print(f"{'h':>4} {'n':>6} {'mean%':>8} {'med%':>8} {'win%':>7} "
              f"{'t':>6} {'net%':>8}")
        summary[name] = {}
        for h in HORIZONS:
            s = stats(dedup_cooldown(ev, h), h)
            summary[name][f"h{h}"] = s
            if s["n"] < 5:
                print(f"{h:>4} {s['n']:>6}   (too few)")
                continue
            print(f"{h:>4} {s['n']:>6} {100*s['mean']:>8.2f} "
                  f"{100*s['median']:>8.2f} {100*s['win']:>7.1f} "
                  f"{s['t']:>6.2f} {100*s['net']:>8.2f}")

    if args.json:
        pd.json_normalize(summary).to_json(args.json, force_ascii=False)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
