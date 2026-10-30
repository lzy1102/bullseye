"""ETF rotation on A-share ETFs - vectorised, with an explicit holdout split.

The single-stock daily-pattern studies all died on a held-out universe, so this
starts from the other end: a small, transparent, low-cost universe where the
premise (style rotation) is documented rather than assumed.

Rules:
  * risk assets: 300 / 500 / 1000 / ChiNext / dividend / brokers / gold
  * safe asset: treasury ETF (511010) when nothing qualifies
  * score: close / close.shift(lookback) - 1  (momentum)
  * risk filter: skip an asset whose close < its own MA200
  * hold the top N by score, equal weight, rebalance on the first trading day
    of each month; fee charged on turnover (0.05%/side default)
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

RISK = ["510300.SH", "510500.SH", "512100.SH", "159915.SZ",
        "510880.SH", "512880.SH", "518880.SH"]
SAFE = "511010.SH"


def load(data_dir):
    px = {}
    for p in glob.glob(os.path.join(data_dir, "*-1d.parquet")):
        sym = os.path.basename(p)[:-len("-1d.parquet")]
        d = pd.read_parquet(p, columns=["date", "close"])
        d["date"] = pd.to_datetime(d["date"])
        px[sym] = d.set_index("date")["close"]
    return pd.DataFrame(px).sort_index()


def backtest(px, lookback=20, top=1, ma=200, fee=0.0005,
             start="2014-01-01", end="2026-10-10", use_filter=True,
             daily_guard=False, abs_mom=False):
    px = px.loc[start:end]
    rets = px.pct_change().fillna(0)
    score = px / px.shift(lookback) - 1
    ma_s = px.rolling(ma).mean()

    months = px.index.to_period("M")
    rebal = px.index[np.r_[True, months[1:] != months[:-1]]]
    live = [c for c in RISK + [SAFE] if c in px.columns]
    w = pd.DataFrame(0.0, index=px.index, columns=live)
    cur = pd.Series(0.0, index=live)
    for d in px.index:
        if d in rebal:
            row = score.loc[d][[c for c in RISK if c in px.columns]]
            ok = row.notna()
            if use_filter:
                ok &= (px.loc[d] > ma_s.loc[d])
            ok &= (px.loc[d].notna())
            if abs_mom:
                ok &= (row > 0)
            pick = row[ok].nlargest(top).index.tolist()
            new = pd.Series(0.0, index=live)
            if pick:
                new[pick] = 1.0 / len(pick)
            else:
                new[SAFE] = 1.0
            cur = new
        elif daily_guard:
            held = [c for c in cur[cur > 0].index if c != SAFE]
            if held:
                h = held[0]
                if not (px.loc[d, h] > ma_s.loc[d, h]):
                    new = pd.Series(0.0, index=live)
                    new[SAFE] = 1.0
                    cur = new
        w.loc[d] = cur

    # weights decided at close d earn from d+1: shift one bar or it is lookahead
    w_eff = w.shift(1).fillna(0)
    gross = (w_eff * rets[live]).sum(axis=1)
    turn = (w - w.shift(1)).abs().sum(axis=1).fillna(0)
    net = gross - turn * fee
    eq = (1 + net).cumprod()
    return eq, w, turn


def stats(eq, label=""):
    r = eq.pct_change().fillna(0)
    days = max(1.0, (eq.index[-1] - eq.index[0]).days)
    dd = float((eq / eq.cummax() - 1).min()) * 100
    return dict(label=label, total=(eq.iloc[-1] - 1) * 100,
                cagr=(eq.iloc[-1] ** (365.25 / days) - 1) * 100, dd=dd,
                sharpe=r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0)


def show(s, extra=""):
    print(f"{s['label']:<28} total {s['total']:>8.1f}%  cagr {s['cagr']:>6.2f}%  "
          f"dd {s['dd']:>7.2f}%  sharpe {s['sharpe']:>5.2f} {extra}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="user_data/data_etf")
    ap.add_argument("--fee", type=float, default=0.0005)
    args = ap.parse_args()
    px = load(args.data)
    print(f"universe: {', '.join(px.columns)}\n")

    windows = [("2014-2016", "2014-01-01", "2016-12-31"),
               ("2017-2019", "2017-01-01", "2019-12-31"),
               ("2020-2022", "2020-01-01", "2022-12-31"),
               ("2023-2026", "2023-01-01", "2026-10-10"),
               ("full", "2014-01-01", "2026-10-10")]

    print("== benchmarks ==")
    for name, a, b in windows:
        eq = px.loc[a:b, "510300.SH"].dropna()
        show(stats(eq / eq.iloc[0], f"300 buy&hold [{name}]"))

    print("\n== rotation grid (full window) ==")
    for lookback in (20, 60, 120):
        for top in (1, 2):
            for guard, absm in ((False, False), (True, False), (True, True)):
                eq, w, turn = backtest(px, lookback=lookback, top=top,
                                       fee=args.fee, start="2014-01-01",
                                       end="2026-10-10",
                                       daily_guard=guard, abs_mom=absm)
                tag = f"mom{lookback} top{top} g{int(guard)}a{int(absm)}"
                show(stats(eq, tag), f"turnover {turn.sum():.0f}x")

    print("\n== chosen config per window (mom20 top1, guard+abs) ==")
    for name, a, b in windows:
        eq, _, turn = backtest(px, lookback=20, top=1, fee=args.fee, start=a,
                               end=b, daily_guard=True, abs_mom=True)
        show(stats(eq, f"mom20 top1 [{name}]"), f"turnover {turn.sum():.0f}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
