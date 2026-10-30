"""Parallel top-up for the HS300 fundamentals set (kline sequential, fin threaded)."""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import akshare as ak
import baostock as bs
import pandas as pd

K_FIELDS = "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg,peTTM,pbMRQ,isST"
FIN_COLS = {
    "日期": "date", "净资产收益率(%)": "roe", "加权净资产收益率(%)": "roe_w",
    "净利润增长率(%)": "np_yoy", "主营业务收入增长率(%)": "rev_yoy",
    "销售毛利率(%)": "gross_margin", "销售净利率(%)": "net_margin",
    "资产负债率(%)": "debt_ratio", "流动比率": "current_ratio",
    "总资产增长率(%)": "asset_yoy", "每股净资产_调整后(元)": "bps",
}


def fetch_fin(sym, fdir, start_year):
    fp = os.path.join(fdir, f"{sym}.parquet")
    if os.path.exists(fp):
        return sym, "cached"
    try:
        f = ak.stock_financial_analysis_indicator(
            symbol=sym.split(".")[0], start_year=start_year)
        if f is None or f.empty:
            return sym, "empty"
        keep = {k: v for k, v in FIN_COLS.items() if k in f.columns}
        f = f[list(keep)].rename(columns=keep)
        f["date"] = pd.to_datetime(f["date"])
        for c in f.columns:
            if c != "date":
                f[c] = pd.to_numeric(f[c], errors="coerce")
        f.to_parquet(fp, index=False)
        return sym, "ok"
    except Exception as e:
        return sym, f"fail:{type(e).__name__}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="user_data/data_fund")
    ap.add_argument("--start", default="2014-01-01")
    ap.add_argument("--end", default="2026-10-10")
    ap.add_argument("--fin-start", default="2014")
    ap.add_argument("--workers", type=int, default=8)
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
    codes = [r[1] for r in pd.DataFrame(rows, columns=rs.fields).itertuples(index=False)] \
        if False else [r[1] for r in pd.DataFrame(rows, columns=rs.fields).values]
    todo = []
    for code in codes:
        sym = code.split(".")[1] + "." + ("SH" if code.startswith("sh") else "SZ")
        todo.append((code, sym))
        kp = os.path.join(kdir, f"{sym}-1d.parquet")
        if os.path.exists(kp):
            continue
        rs = bs.query_history_k_data_plus(code, K_FIELDS, start_date=args.start,
                                          end_date=args.end, frequency="d",
                                          adjustflag="2")
        buf = []
        while rs.next():
            buf.append(rs.get_row_data())
        if not buf:
            continue
        d = pd.DataFrame(buf, columns=rs.fields)
        for c in ("open", "high", "low", "close", "preclose", "volume",
                  "amount", "turn", "pctChg", "peTTM", "pbMRQ", "isST"):
            if c in d:
                d[c] = pd.to_numeric(d[c], errors="coerce")
        d["date"] = pd.to_datetime(d["date"])
        d.to_parquet(kp, index=False)
    bs.logout()
    print(f"kline done: {len(os.listdir(kdir))} files")

    missing = [(c, s) for c, s in todo
               if not os.path.exists(os.path.join(fdir, f"{s}.parquet"))]
    print(f"fin missing: {len(missing)}")
    ok = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_fin, s, fdir, args.fin_start): s for _, s in missing}
        for i, fut in enumerate(as_completed(futs), 1):
            sym, st = fut.result()
            ok += st == "ok"
            if i % 20 == 0:
                print(f"  {i}/{len(missing)} ok={ok}", flush=True)
    print(f"fin done: {len(os.listdir(fdir))} files (+{ok})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
