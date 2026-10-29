"""Does the FreqAI volatility finding port to A-shares?

docs/FreqAI_MLpilot_结果.md: direction is unlearnable, but forward volatility is
highly learnable (OOS IC 0.30, monotone deciles). On crypto, V6 (predicted
vol -> position scaling) still lost, so this must be re-tested honestly.

Walk-forward, no lookahead: train on every year before Y, predict Y, expanding.
Target = log realised vol over the next `--h` trading days.

Compares the ML forecaster against cheap causal estimators (persistence,
EWMA, ATR) so we can tell whether a sidecar model is even worth it - if a
20-day realised vol series is as good, the strategy needs no ML at all.

    python3 scripts/research/vol_forecast.py --data user_data/data \
        --start 2015-01-01 --end 2026-10-10 --pool top --top 50 --h 10
"""
import argparse
import glob
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

FEATURES = [
    "rv5", "rv10", "rv20", "rv60", "rv_ratio", "log_rv20",
    "atr14", "atr20_z", "hl_range", "hl_range5", "abs_ret", "abs_ret5",
    "vol_ratio", "turn_ratio", "bw", "bw_pct", "ma_spread", "dist_ma20",
    "mkt_rv20",
]


def load_universe(data_dir, start, end):
    frames = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "*-1d.parquet"))):
        sym = os.path.basename(path)[:-len("-1d.parquet")]
        if not (sym.endswith(".SH") or sym.endswith(".SZ")) or sym == "000300.SH":
            continue
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        need = {"date", "open", "high", "low", "close", "volume", "turn"}
        if not need <= set(df.columns):
            continue
        df["date"] = pd.to_datetime(df["date"])
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        df = df[(df["volume"] > 0) & (df["isST"].fillna(0) == 0)] if "isST" in df else df
        if len(df) < 400:
            continue
        frames[sym] = df.reset_index(drop=True)
    return frames


def market_rv(data_dir, start, end):
    path = os.path.join(data_dir, "000300.SH-1d.parquet")
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"])
    r = np.log(df["close"]).diff()
    df["mkt_rv20"] = r.rolling(20).std()
    return df[["date", "mkt_rv20"]]


def features(df, mkt):
    c, h, l, o, v = (df[k] for k in ("close", "high", "low", "open", "volume"))
    lr = np.log(c).diff()
    out = df.copy()
    for n in (5, 10, 20, 60):
        out[f"rv{n}"] = lr.rolling(n).std()
    out["rv_ratio"] = out["rv5"] / out["rv20"]
    out["log_rv20"] = np.log(out["rv20"].clip(lower=1e-6))
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                   axis=1).max(axis=1)
    out["atr14"] = tr.rolling(14).mean() / c
    atr20 = tr.rolling(20).mean() / c
    out["atr20_z"] = atr20 / atr20.rolling(100).mean()
    out["hl_range"] = (h - l) / c
    out["hl_range5"] = out["hl_range"].rolling(5).mean()
    out["abs_ret"] = lr.abs()
    out["abs_ret5"] = out["abs_ret"].rolling(5).mean()
    out["vol_ratio"] = v / v.shift(1).rolling(96).median()
    turn = df["turn"].where(df["turn"] > 0)
    out["turn_ratio"] = turn / turn.rolling(20).mean()
    ma20 = c.rolling(20).mean()
    sd = c.rolling(20).std()
    out["bw"] = (4 * sd) / ma20
    out["bw_pct"] = out["bw"].rolling(100).rank(pct=True)
    ma5, ma10 = c.rolling(5).mean(), c.rolling(10).mean()
    out["ma_spread"] = (pd.concat([ma5, ma10, ma20], axis=1).max(axis=1)
                        - pd.concat([ma5, ma10, ma20], axis=1).min(axis=1)) / ma20
    out["dist_ma20"] = c / ma20 - 1
    out["lr"] = lr
    out = out.merge(mkt, on="date", how="left")
    return out


def build(frames, mkt, h):
    rows = []
    for sym, raw in frames.items():
        df = features(raw, mkt)
        lr = np.log(df["close"]).diff()
        # forward realised vol over the next h bars (strictly future)
        fwd = lr.shift(-1).rolling(h).std().shift(-(h - 1))
        df["y"] = np.log(fwd.clip(lower=1e-6))
        df["fwd_vol"] = fwd
        df["symbol"] = sym
        df["year"] = df["date"].dt.year
        rows.append(df.dropna(subset=FEATURES + ["y"]))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def spearman(a, b):
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


def deciles(df, pred_col):
    q = pd.qcut(df[pred_col].rank(method="first"), 10, labels=False)
    g = df.groupby(q)
    return pd.DataFrame({
        "fwd_vol_bp": g["fwd_vol"].mean() * 1e4,
        "fwd_ret_bp": g["lr"].mean() * 1e4 if "lr" in df else np.nan,
        "n": g.size(),
    })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="user_data/data")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default="2026-10-10")
    ap.add_argument("--h", type=int, default=10)
    ap.add_argument("--pool", default="top", choices=("all", "top"))
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--out", default="")
    ap.add_argument("--sidecar", default="",
                    help="write walk-forward predictions here "
                         "(symbol,date,pred_ml) for the strategy overlay")
    args = ap.parse_args()

    frames = load_universe(args.data, pd.Timestamp(args.start), pd.Timestamp(args.end))
    mkt = market_rv(args.data, args.start, args.end)
    if args.pool == "top":
        from freqtrade_port_events import rule_pool
        frames = rule_pool(frames, args.top)
    data = build(frames, mkt, args.h)
    print(f"rows {len(data)}, symbols {data['symbol'].nunique()}, h={args.h}\n")

    years = sorted(y for y in data["year"].unique() if y >= 2017)
    hdr = f"{'year':>6} {'train':>7} {'test':>6} {'IC_ml':>7} {'IC_rv20':>8} {'IC_ewma':>8} {'IC_atr':>7}"
    print(hdr)
    print("-" * len(hdr))
    ics = {"ml": [], "rv20": [], "ewma": [], "atr": []}
    preds = []
    for y in years:
        tr = data[data["year"] < y]
        te = data[data["year"] == y]
        if len(tr) < 2000 or len(te) < 100:
            continue
        X = tr[FEATURES].to_numpy(float)
        mu, sd = X.mean(0), X.std(0)
        sd[sd == 0] = 1.0
        Z = (X - mu) / sd
        coef = np.linalg.solve(Z.T @ Z + args.alpha * np.eye(Z.shape[1]), Z.T @ tr["y"].to_numpy())
        pred = ((te[FEATURES].to_numpy(float) - mu) / sd) @ coef
        te = te.assign(pred_ml=pred, pred_rv20=te["rv20"],
                       pred_ewma=te["rv20"].ewm(halflife=10).mean(),
                       pred_atr=te["atr14"])
        row = dict(year=int(y), train=len(tr), test=len(te),
                   IC_ml=spearman(te["pred_ml"], te["fwd_vol"]),
                   IC_rv20=spearman(te["pred_rv20"], te["fwd_vol"]),
                   IC_ewma=spearman(te["pred_ewma"], te["fwd_vol"]),
                   IC_atr=spearman(te["pred_atr"], te["fwd_vol"]))
        print(f"{row['year']:>6} {row['train']:>7} {row['test']:>6} "
              f"{row['IC_ml']:>7.3f} {row['IC_rv20']:>8.3f} "
              f"{row['IC_ewma']:>8.3f} {row['IC_atr']:>7.3f}")
        ics["ml"].append(row["IC_ml"]); ics["rv20"].append(row["IC_rv20"])
        ics["ewma"].append(row["IC_ewma"]); ics["atr"].append(row["IC_atr"])
        preds.append(te)

    print("\nmean IC:", {k: round(float(np.mean(v)), 3) for k, v in ics.items() if v})

    if preds:
        allp = pd.concat(preds, ignore_index=True)
        print("\ndecile of predicted vol -> realised forward vol (bp) | forward return (bp)")
        print(deciles(allp, "pred_ml").to_string(float_format=lambda x: f"{x:8.1f}"))

    if args.out:
        if preds:
            pd.concat(preds, ignore_index=True)[
                ["symbol", "date", "pred_ml", "fwd_vol"]
            ].to_parquet(args.out, index=False)
            print(f"\nwrote {args.out}")

    if args.sidecar and preds:
        sc = pd.concat(preds, ignore_index=True)[["symbol", "date", "pred_ml"]]
        sc = sc.rename(columns={"pred_ml": "pred_vol"})
        sc["pred_vol"] = np.exp(sc["pred_vol"])
        sc.to_parquet(args.sidecar, index=False)
        print(f"wrote {args.sidecar} ({len(sc)} rows, "
              f"{sc['symbol'].nunique()} symbols)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
