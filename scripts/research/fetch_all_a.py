"""Download daily bars for the whole A-share market (point-in-time universe).

Resumable: skips files already on disk. Writes a compact schema
(date, close, volume, amount, turn, pctChg, peTTM, pbMRQ, isST) which is all the
multi-factor model needs.

    python3 scripts/research/fetch_all_a.py --out user_data/data_all
"""
import argparse
import os
import socket
import sys
import time

import baostock as bs
import pandas as pd

# baostock 在被限流时不会返回错误，而是让 socket 读永远阻塞。
# 全局默认超时让卡住的请求抛异常，从而计入"空结果"并由 --stop-after-empty 收手。
socket.setdefaulttimeout(90)

FIELDS = "date,close,volume,amount,turn,pctChg,peTTM,pbMRQ,isST"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="user_data/data_all")
    ap.add_argument("--start", default="2014-01-01")
    ap.add_argument("--end", default="2026-10-10")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--max-seconds", type=int, default=0,
                    help="stop after this many seconds (0 = unlimited)")
    ap.add_argument("--stop-after-empty", type=int, default=12,
                    help="stop after this many consecutive empty results (throttling)")
    ap.add_argument("--pause", type=float, default=0.2,
                    help="sleep between symbols")
    ap.add_argument("--reason", default="",
                    help="tag appended to the progress log line")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    codes_path = os.path.join(args.out, "codes.txt")

    bs.login()
    if os.path.exists(codes_path):
        codes = [l.strip() for l in open(codes_path) if l.strip()]
    else:
        rs = bs.query_all_stock("2026-10-09")
        buf = []
        while rs.next():
            buf.append(rs.get_row_data())
        d = pd.DataFrame(buf, columns=rs.fields)
        codes = [c for c in d["code"]
                 if (c.startswith("sh.6") or c.startswith("sz.0") or c.startswith("sz.3"))
                 and not c.startswith("sz.399")]
        open(codes_path, "w").write("\n".join(codes))
    if args.shards > 1:
        codes = codes[args.shard::args.shards]
    print(f"codes: {len(codes)} (shard {args.shard}/{args.shards})", flush=True)

    done = 0
    empty_streak = 0
    t0 = time.time()
    for i, code in enumerate(codes, 1):
        if args.max_seconds and time.time() - t0 > args.max_seconds:
            print(f"time budget reached at {i}", flush=True)
            break
        sym = code.split(".")[1] + "." + ("SH" if code.startswith("sh") else "SZ")
        fp = os.path.join(args.out, f"{sym}-1d.parquet")
        if os.path.exists(fp):
            done += 1
            continue
        time.sleep(args.pause)
        try:
            buf = []
            for attempt in range(3):
                try:
                    rs = bs.query_history_k_data_plus(code, FIELDS, start_date=args.start,
                                                      end_date=args.end, frequency="d",
                                                      adjustflag="2")
                    buf = []
                    while rs.next():
                        buf.append(rs.get_row_data())
                except (socket.timeout, OSError) as e:
                    print(f"  timeout {code}: {type(e).__name__}", flush=True)
                    buf = []
                if buf:
                    break
                time.sleep(2 + 3 * attempt)
            if not buf:
                empty_streak += 1
                if empty_streak >= args.stop_after_empty:
                    print(f"throttled: {empty_streak} empty in a row, stop", flush=True)
                    bs.logout()
                    return 2
            else:
                empty_streak = 0
            if buf and len(buf) > 200:
                d = pd.DataFrame(buf, columns=rs.fields)
                for c in FIELDS.split(",")[1:]:
                    d[c] = pd.to_numeric(d[c], errors="coerce")
                d["date"] = pd.to_datetime(d["date"])
                d = d[(d["volume"] > 0) & d["close"].notna()]
                d.to_parquet(fp, index=False)
                done += 1
        except Exception:
            pass
        if i % 200 == 0:
            print(f"  {i}/{len(codes)} saved={done}", flush=True)
    bs.logout()
    print(f"done: {done} files in {args.out} "
          f"in {time.time() - t0:.0f}s {args.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
