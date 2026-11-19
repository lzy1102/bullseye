"""Incremental intraday bars for A-shares (baostock, 2020-01-01 onward).

baostock serves 5/15/30/60 minute bars but only from 2020; anything earlier
comes back empty. Resumable: one parquet per symbol and frequency, skipped if
already on disk.

    python3 scripts/research/fetch_intraday.py --freq 5 \
        --codes-dir user_data/data_fund --out user_data/data_5m \
        --max-seconds 10800
"""
import argparse
import glob
import os
import socket
import sys
import time

import baostock as bs
import pandas as pd

FIELDS = "date,time,code,open,high,low,close,volume,amount"
socket.setdefaulttimeout(90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freq", default="5", choices=["5", "15", "30", "60"])
    ap.add_argument("--codes-dir", default="user_data/data_fund",
                    help="take symbols from *-1d.parquet files in this dir")
    ap.add_argument("--out", default="user_data/data_5m")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-10-10")
    ap.add_argument("--max-seconds", type=int, default=0)
    ap.add_argument("--pause", type=float, default=0.2)
    ap.add_argument("--stop-after-empty", type=int, default=15)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    syms = sorted(os.path.basename(p)[:-len("-1d.parquet")]
                  for p in glob.glob(os.path.join(args.codes_dir, "*-1d.parquet")))
    if args.limit:
        syms = syms[:args.limit]
    todo = [s for s in syms
            if not os.path.exists(os.path.join(args.out, f"{s}-{args.freq}m.parquet"))]
    print(f"symbols {len(syms)}, missing {len(todo)}", flush=True)

    bs.login()
    t0 = time.time()
    saved = empty = 0
    streak = 0
    for i, sym in enumerate(todo, 1):
        if args.max_seconds and time.time() - t0 > args.max_seconds:
            print(f"time budget reached at {i}", flush=True)
            break
        code = ("sh." if sym.endswith(".SH") else "sz.") + sym.split(".")[0]
        fp = os.path.join(args.out, f"{sym}-{args.freq}m.parquet")
        buf = []
        try:
            rs = bs.query_history_k_data_plus(code, FIELDS,
                                              start_date=args.start,
                                              end_date=args.end,
                                              frequency=args.freq, adjustflag="2")
            while rs.next():
                buf.append(rs.get_row_data())
        except (socket.timeout, OSError) as e:
            print(f"  timeout {sym}: {type(e).__name__}", flush=True)
            buf = []
        if not buf:
            empty += 1
            streak += 1
            if streak >= args.stop_after_empty:
                print(f"throttled: {streak} empty in a row, stop", flush=True)
                break
        else:
            streak = 0
            d = pd.DataFrame(buf, columns=rs.fields)
            for c in ("open", "high", "low", "close", "volume", "amount"):
                d[c] = pd.to_numeric(d[c], errors="coerce")
            d["code"] = sym
            d = d[d["volume"] > 0]
            d.to_parquet(fp, index=False)
            saved += 1
        time.sleep(args.pause)
        if i % 20 == 0:
            print(f"  {i}/{len(todo)} saved={saved} empty={empty} "
                  f"{time.time()-t0:.0f}s", flush=True)
    bs.logout()
    print(f"done: +{saved} files, empty {empty}, {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
