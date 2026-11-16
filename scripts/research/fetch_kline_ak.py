"""Threaded akshare k-line top-up (Eastmoney), schema-compatible with data_fund.

Used when baostock throttles or blocks. Price/volume/amount/turn are sufficient
for momentum, low-vol and turnover; PB/PE columns are filled with NaN so the
value factor is simply unavailable for these names.

    python3 scripts/research/fetch_kline_ak.py --out user_data/data_fund \
        --index both --workers 8
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import akshare as ak
import baostock as bs
import pandas as pd

REN = {"日期": "date", "收盘": "close", "成交量": "volume", "成交额": "amount",
       "换手率": "turn", "涨跌幅": "pctChg"}


def fetch_one(sym, kdir, start, end):
    fp = os.path.join(kdir, f"{sym}-1d.parquet")
    if os.path.exists(fp):
        return sym, "cached"
    code = sym.split(".")[0]
    try:
        d = ak.stock_zh_a_hist(symbol=code, period="daily",
                               start_date=start.replace("-", ""),
                               end_date=end.replace("-", ""), adjust="qfq")
        if d is None or d.empty or len(d) < 200:
            return sym, "empty"
        keep = {k: v for k, v in REN.items() if k in d.columns}
        d = d[list(keep)].rename(columns=keep)
        d["date"] = pd.to_datetime(d["date"])
        for c in d.columns:
            if c != "date":
                d[c] = pd.to_numeric(d[c], errors="coerce")
        d["volume"] = d["volume"] * 100          # 手 -> 股
        d["pbMRQ"] = float("nan")
        d["peTTM"] = float("nan")
        d["isST"] = 0
        d = d[(d["volume"] > 0) & d["close"].notna()].sort_values("date")
        d.to_parquet(fp, index=False)
        return sym, "ok"
    except Exception as e:
        return sym, f"fail:{type(e).__name__}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="user_data/data_fund")
    ap.add_argument("--index", default="both", choices=["hs300", "zz500", "both"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--start", default="2014-01-01")
    ap.add_argument("--end", default="2026-10-10")
    args = ap.parse_args()
    kdir = os.path.join(args.out, "kline")
    os.makedirs(kdir, exist_ok=True)

    bs.login()
    codes = []
    for which in (["hs300", "zz500"] if args.index == "both" else [args.index]):
        rs = bs.query_hs300_stocks() if which == "hs300" else bs.query_zz500_stocks()
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        codes += [r[1] for r in pd.DataFrame(rows, columns=rs.fields).values]
    bs.logout()
    syms = [c.split(".")[1] + "." + ("SH" if c.startswith("sh") else "SZ") for c in codes]
    syms = list(dict.fromkeys(syms))
    todo = [s for s in syms if not os.path.exists(os.path.join(kdir, f"{s}-1d.parquet"))]
    print(f"codes {len(syms)}, missing {len(todo)}", flush=True)

    ok = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_one, s, kdir, args.start, args.end): s for s in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            sym, st = fut.result()
            ok += st == "ok"
            if i % 25 == 0:
                print(f"  {i}/{len(todo)} ok={ok}", flush=True)
    print(f"done: {len(os.listdir(kdir))} kline files (+{ok})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
