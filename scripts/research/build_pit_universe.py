"""Point-in-time large-cap universe from the full market panel.

At each month-end rank every listed stock by float market cap
(close * volume * 100 / turn, 20-day median) and keep the top N. This is the
selection an investor could actually have made at the time - no knowledge of
today's index membership.

    python3 scripts/research/build_pit_universe.py --data user_data/data_all \
        --top 300 --out user_data/data_all/pit_top300.parquet
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="user_data/data_all")
    ap.add_argument("--top", type=int, default=300)
    ap.add_argument("--out", default="user_data/data_all/pit_top300.parquet")
    args = ap.parse_args()

    closes, caps = {}, {}
    for p in glob.glob(os.path.join(args.data, "*-1d.parquet")):
        sym = os.path.basename(p)[:-len("-1d.parquet")]
        try:
            d = pd.read_parquet(p, columns=["date", "close", "volume", "turn"])
        except Exception:
            continue
        if len(d) < 250:
            continue
        d["date"] = pd.to_datetime(d["date"])
        d = d.drop_duplicates("date").set_index("date").sort_index()
        closes[sym] = d["close"]
        t = d["turn"].where(d["turn"] > 0)
        cap = (d["close"] * d["volume"] * 100 / t).rolling(20).median()
        caps[sym] = cap
    close = pd.DataFrame(closes).sort_index()
    cap = pd.DataFrame(caps).sort_index()
    print(f"panel: {close.shape[1]} symbols, {len(close)} dates")

    month = close.index.to_period("M")
    month_end = close.index[np.r_[month[1:] != month[:-1], True]]
    rows = []
    for d in month_end:
        row = cap.loc[d].dropna()
        row = row[row > 0]
        if row.empty:
            continue
        picks = row.nlargest(args.top).index
        for s in picks:
            rows.append((d, s))
    pit = pd.DataFrame(rows, columns=["date", "symbol"])
    pit.to_parquet(args.out, index=False)
    print(f"wrote {args.out}: {len(pit)} rows, "
          f"{pit['symbol'].nunique()} unique names, {pit['date'].nunique()} dates")

    per = pit.groupby("date")["symbol"].nunique()
    print(f"names per date: median {per.median():.0f}, min {per.min()}")
    changes = []
    prev = set()
    for d, g in pit.groupby("date"):
        cur = set(g["symbol"])
        if prev:
            changes.append(len(cur - prev) / len(cur))
        prev = cur
    print(f"average monthly turnover of the universe: {100*np.mean(changes):.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
