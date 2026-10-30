"""Download a held-out A-share universe (never used in the research).

Picks liquid names that are NOT already in user_data/data, so results are a true
out-of-universe test rather than another cut of the same 168 symbols.

    python3 scripts/research/fetch_new_universe.py --out user_data/data_new --n 150
"""
import argparse
import os
import sys

import baostock as bs
import pandas as pd

FIELDS = ("date,code,open,high,low,close,preclose,volume,amount,"
          "adjustflag,turn,tradestatus,pctChg,isST")


def existing(data_dir):
    out = set()
    if not os.path.isdir(data_dir):
        return out
    for f in os.listdir(data_dir):
        if f.endswith("-1d.parquet"):
            out.add(f[:-len("-1d.parquet")])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="user_data/data_new")
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--old", default="user_data/data")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default="2026-10-10")
    ap.add_argument("--min-bars", type=int, default=1200)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    bs.login()
    rs = bs.query_all_stock("2026-10-09")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    allc = pd.DataFrame(rows, columns=rs.fields)

    have = existing(args.old)
    codes = []
    for c in allc["code"]:
        if not (c.startswith("sh.6") or c.startswith("sz.0") or c.startswith("sz.3")):
            continue
        sym = c.split(".")[1] + "." + ("SH" if c.startswith("sh") else "SZ")
        if sym in have:
            continue
        codes.append((c, sym))
    codes.sort()
    # deterministic, evenly spread sample (no cherry picking by outcome)
    step = max(1, len(codes) // args.n)
    pick = codes[::step][: args.n]
    print(f"candidates {len(codes)}, picking {len(pick)}")

    got = 0
    for code, sym in pick:
        rs = bs.query_history_k_data_plus(
            code, FIELDS, start_date=args.start, end_date=args.end,
            frequency="d", adjustflag="2")
        buf = []
        while rs.next():
            buf.append(rs.get_row_data())
        if not buf:
            continue
        d = pd.DataFrame(buf, columns=rs.fields)
        for col in ("open", "high", "low", "close", "preclose", "volume",
                    "amount", "turn", "pctChg", "isST"):
            d[col] = pd.to_numeric(d[col], errors="coerce")
        d = d[(d["volume"] > 0) & (d["tradestatus"] == "1")]
        if len(d) < args.min_bars or d["close"].isna().any():
            continue
        d["date"] = pd.to_datetime(d["date"])
        out = d[["date", "open", "high", "low", "close", "volume",
                 "preclose", "turn", "pctChg", "isST"]].reset_index(drop=True)
        # liquidity floor, same spirit as the screen (median amount >= 1e8)
        if float((out["close"] * out["volume"] * 100).median()) < 5e7:
            continue
        out.to_parquet(os.path.join(args.out, f"{sym}-1d.parquet"), index=False)
        got += 1
        if got % 25 == 0:
            print(f"  {got} saved…", flush=True)
    bs.logout()
    print(f"done: {got} symbols -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
