"""Download HS300 prices + fundamentals for a multi-factor test (resumable).

  * daily bars via baostock, with pbMRQ / peTTM / turn / isST (point-in-time)
  * quarterly fundamentals via sina's indicator feed, one call per stock
  * industry via baostock (current snapshot only - a known limitation)

Publication lag is NOT in the sina feed, so the backtest applies a fixed
conservative lag (default 90 days) instead of trusting the report date.

    python3 scripts/research/fetch_fundamentals.py --out user_data/data_fund
"""
import argparse
import os
import sys
import time

import akshare as ak
import baostock as bs
import pandas as pd

K_FIELDS = "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg,peTTM,pbMRQ,isST"
FIN_COLS = {
    "日期": "date",
    "净资产收益率(%)": "roe",
    "加权净资产收益率(%)": "roe_w",
    "净利润增长率(%)": "np_yoy",
    "主营业务收入增长率(%)": "rev_yoy",
    "销售毛利率(%)": "gross_margin",
    "销售净利率(%)": "net_margin",
    "资产负债率(%)": "debt_ratio",
    "流动比率": "current_ratio",
    "总资产增长率(%)": "asset_yoy",
    "每股净资产_调整后(元)": "bps",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="user_data/data_fund")
    ap.add_argument("--start", default="2014-01-01")
    ap.add_argument("--end", default="2026-10-10")
    ap.add_argument("--fin-start", default="2014")
    args = ap.parse_args()
    kdir = os.path.join(args.out, "kline")
    fdir = os.path.join(args.out, "fin")
    os.makedirs(kdir, exist_ok=True)
    os.makedirs(fdir, exist_ok=True)

    bs.login()
    rs = bs.query_hs300_stocks()
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    cons = pd.DataFrame(rows, columns=rs.fields)
    codes = cons["code"].tolist()
    print(f"HS300 constituents: {len(codes)}")

    ind_rows = []
    rs = bs.query_stock_industry()
    while rs.next():
        ind_rows.append(rs.get_row_data())
    ind = pd.DataFrame(ind_rows, columns=rs.fields)
    ind[["code", "code_name", "industry"]].to_parquet(
        os.path.join(args.out, "industry.parquet"), index=False)

    for i, code in enumerate(codes, 1):
        sym = code.split(".")[1] + "." + ("SH" if code.startswith("sh") else "SZ")
        kp = os.path.join(kdir, f"{sym}-1d.parquet")
        if not os.path.exists(kp):
            rs = bs.query_history_k_data_plus(
                code, K_FIELDS, start_date=args.start, end_date=args.end,
                frequency="d", adjustflag="2")
            buf = []
            while rs.next():
                buf.append(rs.get_row_data())
            if buf:
                d = pd.DataFrame(buf, columns=rs.fields)
                for c in ("open", "high", "low", "close", "preclose", "volume",
                          "amount", "turn", "pctChg", "peTTM", "pbMRQ", "isST"):
                    if c in d:
                        d[c] = pd.to_numeric(d[c], errors="coerce")
                d["date"] = pd.to_datetime(d["date"])
                d.to_parquet(kp, index=False)
        fp = os.path.join(fdir, f"{sym}.parquet")
        if not os.path.exists(fp):
            try:
                f = ak.stock_financial_analysis_indicator(
                    symbol=sym.split(".")[0], start_year=args.fin_start)
                if f is not None and not f.empty:
                    keep = {k: v for k, v in FIN_COLS.items() if k in f.columns}
                    f = f[list(keep)].rename(columns=keep)
                    f["date"] = pd.to_datetime(f["date"])
                    for c in f.columns:
                        if c != "date":
                            f[c] = pd.to_numeric(f[c], errors="coerce")
                    f.to_parquet(fp, index=False)
            except Exception as e:
                print(f"  {sym} fin failed: {type(e).__name__}")
            time.sleep(0.15)
        if i % 25 == 0:
            print(f"  {i}/{len(codes)}", flush=True)
    bs.logout()
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
