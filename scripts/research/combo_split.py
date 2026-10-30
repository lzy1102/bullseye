"""70/30 portfolio implemented as two independent wallets (executable form).

ComboCoil (one process) underperforms because the engine allows one open trade
per pair, so the legs crowd each other out. The faithful implementation is two
configs with their own wallets, which is exactly what this script measures:
70% MacdCandle + 30% CoilBreakRetest, no rebalancing (weights drift), plus a
reference daily-rebalanced figure.

    python3 scripts/research/combo_split.py --timerange 20180101-20261010
"""
import argparse
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

from bullseye.backtesting import BacktestEngine  # noqa: E402
from bullseye.configuration import Config  # noqa: E402


def run(name, cfg_path, timerange):
    cfg = Config(cfg_path)
    pairs = cfg.get("pairlist", [{}])[0].get("config", {}).get("pairs", [])
    eng = BacktestEngine(config=cfg)
    r = eng.run(strategy_name=name, pairlist=pairs, timeframe="1d",
                timerange=timerange, initial_balance=100000.0,
                max_open_trades=cfg.get("max_open_trades", 3), fee=0.001,
                benchmark="000300.SH")
    s = pd.Series({pd.Timestamp(d): float(v) for d, v in r.equity_curve}).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s / s.iloc[0]


def stats(eq):
    r = eq.pct_change().fillna(0)
    days = max(1.0, (eq.index[-1] - eq.index[0]).days)
    dd = float((eq / eq.cummax() - 1).min()) * 100
    return dict(total=(eq.iloc[-1] - 1) * 100,
                cagr=(eq.iloc[-1] ** (365.25 / days) - 1) * 100,
                dd=dd,
                sharpe=r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timerange", default="20180101-20261010")
    ap.add_argument("--a", default="MacdCandle")
    ap.add_argument("--a-cfg", default="user_data/candle_config.yaml")
    ap.add_argument("--b", default="CoilBreakRetest")
    ap.add_argument("--b-cfg", default="user_data/coil_retest_config.yaml")
    ap.add_argument("--w", type=float, default=0.70)
    args = ap.parse_args()

    a = run(args.a, args.a_cfg, args.timerange)
    b = run(args.b, args.b_cfg, args.timerange)
    j = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    print(f"{args.a} + {args.b}, {args.w:.0%}/{1-args.w:.0%}\n")

    for label, eq in (("A alone", j["a"]), ("B alone", j["b"])):
        s = stats(eq)
        print(f"{label:<18} total {s['total']:>8.1f}%  cagr {s['cagr']:>6.2f}%  "
              f"dd {s['dd']:>7.2f}%  sharpe {s['sharpe']:>5.2f}")

    # two wallets, no rebalancing: weights drift with performance
    eq = args.w * j["a"] + (1 - args.w) * j["b"]
    s = stats(eq)
    final_a = args.w * j["a"].iloc[-1]
    final_b = (1 - args.w) * j["b"].iloc[-1]
    print(f"\n{'two wallets':<18} total {s['total']:>8.1f}%  cagr {s['cagr']:>6.2f}%  "
          f"dd {s['dd']:>7.2f}%  sharpe {s['sharpe']:>5.2f}")
    print(f"  final weights A {final_a/(final_a+final_b):.0%} / B "
          f"{final_b/(final_a+final_b):.0%} (drifted from "
          f"{args.w:.0%}/{1-args.w:.0%})")

    # reference: daily rebalanced
    ra, rb = j["a"].pct_change().fillna(0), j["b"].pct_change().fillna(0)
    eq2 = (1 + args.w * ra + (1 - args.w) * rb).cumprod()
    s2 = stats(eq2)
    print(f"{'daily rebalanced':<18} total {s2['total']:>8.1f}%  cagr {s2['cagr']:>6.2f}%  "
          f"dd {s2['dd']:>7.2f}%  sharpe {s2['sharpe']:>5.2f}")

    # reference: quarterly rebalanced
    ra.index = pd.DatetimeIndex(ra.index)
    tmp = pd.DataFrame({"ra": ra, "rb": rb})
    q = tmp.groupby(tmp.index.to_period("Q")).apply(
        lambda d: (1 + args.w * d["ra"] + (1 - args.w) * d["rb"]).prod() - 1)
    eq3 = (1 + q).cumprod()
    s3 = dict(total=(eq3.iloc[-1] - 1) * 100)
    print(f"{'quarterly rebal':<18} total {s3['total']:>8.1f}%  "
          f"(CAGR {eq3.iloc[-1] ** (4 / len(eq3)) - 1:.2%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
