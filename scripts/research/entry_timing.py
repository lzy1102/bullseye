"""Entry-timing study: what does it cost to actually get filled?

The multi-factor backtest assumes the fill happens at the signal day's close.
This measures, using 60-minute bars, what each realistic alternative costs
relative to that assumption.

Rules compared, per entry signal on day d:
  close_d      baseline: signal-day close (the backtest's assumption)
  open_d1      next day's open (the realistic default)
  m1030_d1     next day's first 60-minute bar close
  vwap_d1      next day's mean of 60-minute closes (VWAP proxy)
  pullback     limit at close_d * (1 - limit_pct), valid d+1..d+hold days,
               else filled at that day's close

Output is the per-entry delta versus close_d, the fill rate, and the implied
annual drag given 12 rebalances a year.

    python3 scripts/research/entry_timing.py --pool pit --start 2020-01-01
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

LAG = 90


def load_daily(data_dir):
    o, h, l, c = {}, {}, {}, {}
    for p in glob.glob(os.path.join(data_dir, "*-1d.parquet")):
        s = os.path.basename(p)[:-len("-1d.parquet")]
        d = pd.read_parquet(p)
        d["date"] = pd.to_datetime(d["date"])
        d = d.drop_duplicates("date").set_index("date").sort_index()
        for col, store in (("open", o), ("high", h), ("low", l), ("close", c)):
            v = pd.to_numeric(d[col], errors="coerce")
            store[s] = v.where(v > 0)
    f = lambda x: pd.DataFrame(x).sort_index().astype("float32")
    return f(o), f(h), f(l), f(c)


def load_intraday(d60):
    """{symbol: DataFrame(index=date, columns=[first_close, vwap, last_close])}"""
    out = {}
    for p in glob.glob(os.path.join(d60, "*-60m.parquet")):
        s = os.path.basename(p)[:-len("-60m.parquet")]
        d = pd.read_parquet(p, columns=["date", "time", "close", "volume"])
        d["date"] = pd.to_datetime(d["date"])
        d = d[d["close"] > 0]
        g = d.groupby("date")
        out[s] = pd.DataFrame({
            "first": g["close"].first(),
            "vwap": d.assign(v=d["close"] * d["volume"]).groupby("date").apply(
                lambda x: x["v"].sum() / max(x["volume"].sum(), 1e-9),
                include_groups=False),
            "last": g["close"].last(),
        })
    return out


def score_panel(close):
    ret = close.pct_change()
    mom = close.shift(21) / close.shift(252) - 1
    vol = ret.rolling(60).std()
    z = lambda x: (x - x.mean(axis=1).values[:, None]) / x.std(axis=1).values[:, None]
    return (z(mom) - z(vol)) / 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="user_data/data_all")
    ap.add_argument("--d60", default="user_data/data_60m")
    ap.add_argument("--universe", default="user_data/data_all/pit_top300.parquet")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-10-10")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--limit-pct", type=float, default=0.01)
    ap.add_argument("--limit-days", type=int, default=3)
    args = ap.parse_args()

    o, h, l, c = load_daily(args.data)
    intra = load_intraday(args.d60)
    print(f"daily {c.shape[1]} symbols, intraday {len(intra)} symbols", flush=True)

    uni = None
    if os.path.exists(args.universe):
        u = pd.read_parquet(args.universe)
        u["date"] = pd.to_datetime(u["date"])
        uni = u.groupby("date")["symbol"].apply(set).to_dict()
        uni_dates = np.array(sorted(uni), dtype="datetime64[ns]")
        print(f"universe: {len(uni_dates)} snapshots", flush=True)

    sc = score_panel(c)
    dates = c.loc[args.start:args.end].index
    months = pd.Series(dates).dt.to_period("M").to_numpy()
    rebal = dates[np.r_[True, months[1:] != months[:-1]]]
    print(f"rebalances: {len(rebal)}", flush=True)

    rows = []
    for d in rebal:
        if uni is not None:
            k = int(np.searchsorted(uni_dates, np.datetime64(d), side="right")) - 1
            allowed = uni[uni_dates[k]] if k >= 0 else set()
        else:
            allowed = set(c.columns)
        s = sc.loc[d].dropna()
        s = s[s.index.isin(allowed) & c.loc[d, s.index].notna()]
        if s.empty:
            continue
        picks = s.nlargest(args.top).index.tolist()
        pos = c.index.get_indexer([d])[0]
        if pos + args.limit_days + 1 >= len(c.index):
            continue
        nxt = c.index[pos + 1]
        for sym in picks:
            base = c.at[d, sym]
            if not np.isfinite(base) or sym not in intra:
                continue
            it = intra[sym]
            rec = {"date": d, "symbol": sym, "base": base}
            rec["open_d1"] = o.at[nxt, sym] / base - 1
            if nxt in it.index:
                rec["m1030_d1"] = it.at[nxt, "first"] / base - 1
                rec["vwap_d1"] = it.at[nxt, "vwap"] / base - 1
            # 限价单：-limit_pct 挂 d+1 起 limit_days 天
            target = base * (1 - args.limit_pct)
            fill = np.nan
            for j in range(1, args.limit_days + 1):
                dd = c.index[pos + j]
                lo = l.at[dd, sym] if dd in l.index else np.nan
                if np.isfinite(lo) and lo <= target:
                    fill = target / base - 1
                    break
            if np.isnan(fill):
                dd = c.index[pos + args.limit_days]
                fill = (c.at[dd, sym] / base - 1) if np.isfinite(c.at[dd, sym]) else np.nan
                rec["missed"] = 1
            else:
                rec["missed"] = 0
            rec["pullback"] = fill
            rows.append(rec)

    df = pd.DataFrame(rows)
    print(f"\nentries: {len(df)}  (symbols with intraday: {df['symbol'].nunique()})\n")
    cols = ["open_d1", "m1030_d1", "vwap_d1", "pullback"]
    print("price delta vs the signal-day close; positive = you pay MORE (drag)")
    print(f"{'rule':<12}{'mean bp':>10}{'median bp':>12}{'pay more%':>12}{'annual bp':>12}")
    for col in cols:
        x = df[col].dropna()
        # 12 次调仓/年，每次全组合换手一次 → 年化影响 ≈ 12 × 均值
        print(f"{col:<12}{10000*x.mean():>10.1f}{10000*x.median():>12.1f}"
              f"{100*(x > 0).mean():>12.1f}{12*10000*x.mean():>12.1f}")
    if "missed" in df:
        print(f"\npullback limit {args.limit_pct*100:.1f}%: fill rate "
              f"{100*(1-df['missed'].mean()):.1f}%, "
              f"missed filled at close of day {args.limit_days}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
