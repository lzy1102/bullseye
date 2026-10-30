"""HS300 multi-factor (value / quality / growth / momentum / low-vol).

Point-in-time: fundamentals become usable 90 days after the report date (the
feed has no publication date), and weights decided at a month-end earn from the
NEXT bar - the same-bar lookahead that broke the ETF test is avoided here.

    python3 scripts/research/multifactor.py --data user_data/data_fund \
        --start 2016-01-01 --end 2026-10-10
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

LAG_DAYS = 90


def load(data_dir):
    px, pb, turn, amount = {}, {}, {}, {}
    for p in glob.glob(os.path.join(data_dir, "kline", "*-1d.parquet")):
        sym = os.path.basename(p)[:-len("-1d.parquet")]
        d = pd.read_parquet(p)
        d["date"] = pd.to_datetime(d["date"])
        d = d.drop_duplicates("date").set_index("date")
        px[sym] = d["close"]
        pb[sym] = d["pbMRQ"]
        turn[sym] = d["turn"]
        amount[sym] = d["amount"]
    fin = {}
    for p in glob.glob(os.path.join(data_dir, "fin", "*.parquet")):
        sym = os.path.basename(p)[:-len(".parquet")]
        f = pd.read_parquet(p)
        if f.empty:
            continue
        f["date"] = pd.to_datetime(f["date"])
        f = f.drop_duplicates("date").sort_values("date")
        f["avail"] = f["date"] + pd.Timedelta(days=LAG_DAYS)
        fin[sym] = f.set_index("avail")
    return (pd.DataFrame(px).sort_index(), pd.DataFrame(pb).sort_index(),
            pd.DataFrame(turn).sort_index(), pd.DataFrame(amount).sort_index(), fin)


def asof_multi(fin, syms, dates, col):
    out = pd.DataFrame(np.nan, index=dates, columns=syms)
    for s in syms:
        f = fin.get(s)
        if f is None or col not in f:
            continue
        ser = f[col].dropna()
        if ser.empty:
            continue
        out[s] = ser.reindex(ser.index.union(dates)).ffill().reindex(dates)
    return out


def zscore(df, winsor=(0.01, 0.99)):
    lo = df.quantile(winsor[0], axis=1)
    hi = df.quantile(winsor[1], axis=1)
    d = df.clip(lower=lo, upper=hi, axis=0)
    return d.sub(d.mean(axis=1), axis=0).div(d.std(axis=1), axis=0)


def backtest(px, pb, turn, fin, start, end, top=30, fee=0.001, lag=LAG_DAYS,
             use=("value", "quality", "growth", "mom", "lowvol"),
             industry=None, max_per_ind=6, universe=None):
    dates = px.loc[start:end].index
    ret = px.pct_change().fillna(0).loc[dates]
    months = pd.Series(dates).dt.to_period("M").to_numpy()
    rebal = dates[np.r_[True, months[1:] != months[:-1]]]

    syms = [c for c in px.columns if c in fin]
    roe = asof_multi(fin, syms, dates, "roe")
    npyoy = asof_multi(fin, syms, dates, "np_yoy")
    gm = asof_multi(fin, syms, dates, "gross_margin")

    mom = px[syms].shift(21) / px[syms].shift(252) - 1
    vol = ret[syms].rolling(60).std()
    val = 1.0 / pb[syms].replace(0, np.nan)

    parts = []
    if "value" in use:
        parts.append(zscore(val))
    if "quality" in use:
        parts.append(zscore(roe))
    if "growth" in use:
        parts.append(zscore(npyoy))
    if "mom" in use:
        parts.append(zscore(mom))
    if "lowvol" in use:
        parts.append(zscore(-vol))
    score = sum(parts) / len(parts)
    score = score.replace([np.inf, -np.inf], np.nan)

    # NaN (not 0.0) so ffill carries the last monthly book forward
    w = pd.DataFrame(np.nan, index=dates, columns=syms)
    cur = pd.Series(0.0, index=syms)
    for d in rebal:
        row = score.loc[d].dropna()
        row = row[px.loc[d, row.index].notna()]
        if universe is not None:
            allowed = universe.get(d, set())
            row = row[row.index.isin(allowed)]
        if row.empty:
            w.loc[d] = cur
            continue
        picks = []
        if industry is not None:
            cnt = {}
            for s in row.sort_values(ascending=False).index:
                ind = industry.get(s, "?")
                if cnt.get(ind, 0) >= max_per_ind:
                    continue
                picks.append(s)
                cnt[ind] = cnt.get(ind, 0) + 1
                if len(picks) >= top:
                    break
        else:
            picks = row.nlargest(top).index.tolist()
        cur = pd.Series(0.0, index=syms)
        if picks:
            cur[picks] = 1.0 / len(picks)
        w.loc[d] = cur
    w = w.ffill().fillna(0)
    w_eff = w.shift(1).fillna(0)          # decide at close, earn from next bar
    gross = (w_eff * ret[syms]).sum(axis=1)
    turnv = (w - w.shift(1)).abs().sum(axis=1).fillna(0)
    net = gross - turnv * fee
    eq = (1 + net).cumprod()
    return eq, turnv


def stats(eq):
    r = eq.pct_change().fillna(0)
    days = max(1.0, (eq.index[-1] - eq.index[0]).days)
    dd = float((eq / eq.cummax() - 1).min()) * 100
    return dict(total=(eq.iloc[-1] - 1) * 100,
                cagr=(eq.iloc[-1] ** (365.25 / days) - 1) * 100, dd=dd,
                sharpe=r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0)


def show(label, s, extra=""):
    print(f"{label:<28} total {s['total']:>8.1f}%  cagr {s['cagr']:>6.2f}%  "
          f"dd {s['dd']:>7.2f}%  sharpe {s['sharpe']:>5.2f} {extra}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="user_data/data_fund")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-10-10")
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--universe", default="",
                    help="point-in-time membership parquet (date,symbol)")
    args = ap.parse_args()
    px, pb, turn, amount, fin = load(args.data)
    print(f"prices {px.shape[1]} symbols, fundamentals {len(fin)}, "
          f"{px.index[0].date()}..{px.index[-1].date()}\n")

    ind = None
    ip = os.path.join(args.data, "industry.parquet")
    if os.path.exists(ip):
        d = pd.read_parquet(ip)
        ind = {r["code"].split(".")[1] + "." + ("SH" if r["code"].startswith("sh") else "SZ"):
               str(r["industry"])[:2] for _, r in d.iterrows()}

    uni = None
    if args.universe:
        u = pd.read_parquet(args.universe)
        u["date"] = pd.to_datetime(u["date"])
        uni = u.groupby("date")["symbol"].apply(set).to_dict()
        print(f"PIT universe: {len(uni)} dates, "
              f"{u['symbol'].nunique()} names
")

    if uni is not None:
        sub = px.loc[args.start:args.end]
        mask = pd.DataFrame(False, index=sub.index, columns=sub.columns)
        for d, members in uni.items():
            if d in mask.index:
                cols = [c for c in members if c in mask.columns]
                mask.loc[d, cols] = True
        mask = mask.ffill().fillna(False)
        r = sub.pct_change().fillna(0).where(mask)
        ew = (1 + r.mean(axis=1).fillna(0)).cumprod()
        show("PIT universe equal-weight", stats(ew))
    else:
        ew = (1 + px.loc[args.start:args.end].pct_change().mean(axis=1).fillna(0)).cumprod()
        show("universal equal-weight", stats(ew))
    for top in (20, 30, 50):
        for label, use, use_ind in (
            ("all 5 factors", ("value", "quality", "growth", "mom", "lowvol"), False),
            ("all 5, industry cap", ("value", "quality", "growth", "mom", "lowvol"), True),
            ("value+quality", ("value", "quality"), False),
            ("mom+lowvol", ("mom", "lowvol"), False),
        ):
            eq, tv = backtest(px, pb, turn, fin, args.start, args.end, top=top,
                              fee=args.fee, use=use, industry=ind if use_ind else None,
                              universe=uni)
            show(f"top{top} {label}", stats(eq), f"turnover {tv.sum():.0f}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
