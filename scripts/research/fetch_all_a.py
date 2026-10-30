"""Download daily bars for the whole A-share market (point-in-time universe).

Resumable: skips files already on disk. Writes a compact schema
(date, close, volume, amount, turn, pctChg, peTTM, pbMRQ, isST) which is all the
multi-factor model needs.

    python3 scripts/research/fetch_all_a.py --out user_data/data_all
"""
import argparse
import os
import sys
import time

import baostock as bs
import pandas as pd

FIELDS = "date,close,volume,amount,turn,pctChg,peTTM,pbMRQ,isST"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="user_data/data_all")
    ap.add_argument("--start", default="2014-01-01")
    ap.add_argument("--end", default="2026-10-10")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
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
    for i, code in enumerate(codes, 1):
        sym = code.split(".")[1] + "." + ("SH" if code.startswith("sh") else "SZ")
        fp = os.path.join(args.out, f"{sym}-1d.parquet")
        if os.path.exists(fp):
            done += 1
            continue
        try:
            buf = []
            for attempt in range(3):
                rs = bs.query_history_k_data_plus(code, FIELDS, start_date=args.start,
                                                  end_date=args.end, frequency="d",
                                                  adjustflag="2")
                buf = []
                while rs.next():
                    buf.append(rs.get_row_data())
                if buf:
                    break
                time.sleep(2 + 3 * attempt)
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
    print(f"done: {done} files in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
