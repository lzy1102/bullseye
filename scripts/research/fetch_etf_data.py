"""Download ETF daily bars (baostock, 前复权) into the repo parquet layout."""
import argparse
import os
import sys

import baostock as bs
import pandas as pd

ETFS = {
    "510300.SH": "沪深300",
    "510500.SH": "中证500",
    "512100.SH": "中证1000",
    "159915.SZ": "创业板",
    "510880.SH": "红利",
    "512880.SH": "证券",
    "518880.SH": "黄金",
    "511010.SH": "国债",
    "511880.SH": "货币",
}
FIELDS = "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="user_data/data_etf")
    ap.add_argument("--start", default="2013-01-01")
    ap.add_argument("--end", default="2026-10-10")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    bs.login()
    for sym, name in ETFS.items():
        code = f"{sym.split('.')[1].lower()}.{sym.split('.')[0]}"
        rs = bs.query_history_k_data_plus(
            code, FIELDS, start_date=args.start, end_date=args.end,
            frequency="d", adjustflag="2")
        buf = []
        while rs.next():
            buf.append(rs.get_row_data())
        if not buf:
            print(f"{sym} {name}: NO DATA ({rs.error_code})")
            continue
        d = pd.DataFrame(buf, columns=rs.fields)
        for c in ("open", "high", "low", "close", "preclose", "volume",
                  "amount", "turn", "pctChg"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d[(d["volume"] > 0) & d["close"].notna()]
        d["date"] = pd.to_datetime(d["date"])
        out = d[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
        out.to_parquet(os.path.join(args.out, f"{sym}-1d.parquet"), index=False)
        print(f"{sym} {name}: {len(out)} bars {out.date.iloc[0].date()}..{out.date.iloc[-1].date()}")
    bs.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
