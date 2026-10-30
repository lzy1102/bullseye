"""Correlation / blend test: is CoilBreakRetest a diversifying leg?

Runs the candidate against the incumbent A-share legs on the same window, then
compares daily and monthly return correlation, trade overlap, and a 50/50
daily-rebalanced blend.

    python3 scripts/research/strategy_correlation.py --timerange 20180101-20261010
"""
import argparse
import itertools
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

from bullseye.backtesting import BacktestEngine  # noqa: E402
from bullseye.configuration import Config  # noqa: E402

RUNS = {
    "CoilBreakRetest": "user_data/coil_retest_config.yaml",
    "TopRot": "user_data/combo_config.yaml",
    "ComboSteady": "user_data/combo_config.yaml",
    "MacdCandle": "user_data/candle_config.yaml",
    "SqueezeBreakSpot": "user_data/squeeze_top_config.yaml",
}


def curve(res):
    s = pd.Series({pd.Timestamp(d): float(v) for d, v in res.equity_curve}).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s / s.iloc[0] if len(s) else s


def stats(r):
    eq = (1 + r.fillna(0)).cumprod()
    days = max(1.0, (eq.index[-1] - eq.index[0]).days)
    cagr = eq.iloc[-1] ** (365.25 / days) - 1
    vol = r.std() * np.sqrt(252)
    dd = float((eq / eq.cummax() - 1).min())
    return dict(cagr=cagr * 100, vol=vol * 100, sharpe=(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0,
                dd=dd * 100, total=(eq.iloc[-1] - 1) * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timerange", default="20180101-20261010")
    ap.add_argument("--balance", type=float, default=100000.0)
    args = ap.parse_args()

    res, rets, trades = {}, {}, {}
    for name, cfg_path in RUNS.items():
        cfg = Config(cfg_path)
        pairs = cfg.get("pairlist", [{}])[0].get("config", {}).get("pairs", [])
        engine = BacktestEngine(config=cfg)
        r = engine.run(strategy_name=name, pairlist=pairs, timeframe="1d",
                       timerange=args.timerange, initial_balance=args.balance,
                       max_open_trades=cfg.get("max_open_trades", 3), fee=0.001,
                       benchmark="000300.SH")
        res[name] = r
        rets[name] = curve(r).pct_change()
        trades[name] = r.trades
        st = stats(rets[name].dropna())
        print(f"{name:<18} total {st['total']:>8.1f}%  cagr {st['cagr']:>6.2f}%  "
              f"vol {st['vol']:>5.1f}%  sharpe {st['sharpe']:>5.2f}  dd {st['dd']:>6.2f}%  "
              f"trades {len(r.trades):>4}")

    names = list(RUNS)
    print("\ndaily-return correlation (Pearson / Spearman); monthly in brackets")
    print(f"{'':<18}" + "".join(f"{n[:12]:>14}" for n in names))
    for a in names:
        row = f"{a:<18}"
        for b in names:
            if a == b:
                row += f"{'—':>14}"
                continue
            j = pd.concat([rets[a], rets[b]], axis=1, keys=["a", "b"]).dropna()
            if len(j) < 60:
                row += f"{'n/a':>14}"
                continue
            p = j["a"].corr(j["b"])
            s = j["a"].corr(j["b"], method="spearman")
            ma = j["a"].resample("ME").apply(lambda x: (1 + x).prod() - 1)
            mb = j["b"].resample("ME").apply(lambda x: (1 + x).prod() - 1)
            mp = pd.concat([ma, mb], axis=1).dropna()
            mc = mp["a"].corr(mp["b"]) if len(mp) > 6 else np.nan
            row += f"{p:>6.2f}/{s:>4.2f}({mc:>4.2f})"
        print(row)

    base = "CoilBreakRetest"
    print(f"\ntrade overlap with {base} (same pair, entry within 10 calendar days)")
    for b in names:
        if b == base:
            continue
        mine = [(t.pair, t.entry_date) for t in trades[base] if t.entry_date]
        other = [(t.pair, t.entry_date) for t in trades[b] if t.entry_date]
        hit = sum(1 for p, d in mine
                  if any(p == p2 and abs((d - d2).days) <= 10 for p2, d2 in other))
        print(f"  {b:<16} {hit}/{len(mine)} = {100*hit/max(1,len(mine)):.0f}%")

    print("\nblend weight sweep (w = share of the candidate)")
    print(f"{'pair':<34} {'w':>4} {'cagr%':>7} {'dd%':>7} {'sharpe':>7}")
    for b in names:
        if b == base:
            continue
        j = pd.concat([rets[base], rets[b]], axis=1, keys=["a", "b"]).dropna()
        if len(j) < 60:
            continue
        sb = stats(j["b"])
        label = base[:14] + "+" + b[:14]
        print(f"{label:<34} {'0.0':>4} {sb['cagr']:>7.2f} "
              f"{sb['dd']:>7.2f} {sb['sharpe']:>7.2f}   <- incumbent alone")
        for w in (0.2, 0.3, 0.5):
            st = stats(w * j["a"] + (1 - w) * j["b"])
            print(f"{label:<34} {w:>4.1f} {st['cagr']:>7.2f} "
                  f"{st['dd']:>7.2f} {st['sharpe']:>7.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
