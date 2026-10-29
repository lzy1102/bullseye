"""SqueezeBreakSpot parameter sweep on A-share daily bars (research only).

`--config` only overrides roi/stoploss/trailing and hyperoptable parameters, so
plain strategy attributes (market_gate, time_stop, ...) cannot be varied from
the CLI. This drives the engine directly with a fresh strategy instance per
variant.

    python3 scripts/research/squeeze_break_scan.py --config user_data/squeeze_wide_config.yaml
"""
import argparse
import itertools
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

sys.path.insert(0, ".")
sys.path.insert(0, "user_data/strategies")

from bullseye.backtesting import BacktestEngine  # noqa: E402
from bullseye.configuration import Config  # noqa: E402
from SqueezeBreakSpot import SqueezeBreakSpot  # noqa: E402

BASE = dict(market_gate=True, time_stop=20, max_slots=3, squeeze_pct=0.20,
            require_above_ma250=False, use_trail=False, require_expand=True)


def variants():
    out = [("base", {})]
    out.append(("gate_off", {"market_gate": False}))
    for t in (10, 30, 40):
        out.append((f"t{t}", {"time_stop": t}))
    for s in (5, 8, 10, 20):
        out.append((f"slots{s}", {"max_slots": s}))
    out.append(("gateoff_s10", {"market_gate": False, "max_slots": 10}))
    out.append(("s10_t40", {"max_slots": 10, "time_stop": 40}))
    out.append(("ma250", {"require_above_ma250": True}))
    for p in (0.10, 0.15, 0.30):
        out.append((f"sq{int(p*100)}", {"squeeze_pct": p}))
    out.append(("no_expand", {"require_expand": False}))
    out.append(("trail", {"use_trail": True}))
    # FreqAI port: predicted vol -> position scaling
    for lo, hi in ((0.3, 1.5), (0.5, 1.5), (0.5, 2.0)):
        out.append((f"ml_vol_{lo}_{hi}", {"vol_sizing": "ml",
                                          "vol_scale_lo": lo, "vol_scale_hi": hi}))
    out.append(("ml_vol_glob", {"vol_sizing": "ml", "vol_target_mode": "global",
                                "vol_target": 0.018}))
    out.append(("atr_vol", {"vol_sizing": "atr"}))
    out.append(("atr_vol_glob", {"vol_sizing": "atr",
                                 "vol_target_mode": "global",
                                 "vol_target": 0.028}))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="user_data/squeeze_wide_config.yaml")
    ap.add_argument("--timerange", default="20230101-20261010")
    ap.add_argument("--balance", type=float, default=100000.0)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--benchmark", default="000300.SH")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    cfg = Config(args.config)
    # The index pair must stay in the pairlist: confirm_trade_entry reads it
    # through dp.get_analyzed_dataframe(), and entries on it are already
    # rejected by the strategy. Dropping it silently disables the gate.
    pairs = cfg.get("pairlist", [{}])[0].get("config", {}).get("pairs", [])
    engine = BacktestEngine(config=cfg)
    print(f"{len(pairs)} pairs, {args.timerange}, fee {args.fee}, "
          f"{args.balance:.0f}\n")

    rows = []
    hdr = f"{'variant':<12} {'n':>4} {'ret%':>8} {'cagr%':>7} {'dd%':>6} " \
          f"{'pf':>5} {'win%':>6} {'bm%':>7} {'excess%':>8}"
    print(hdr)
    print("-" * len(hdr))
    for name, over in variants():
        strat = SqueezeBreakSpot()
        for k, v in {**BASE, **over}.items():
            setattr(strat, k, v)
        slots = int(getattr(strat, "max_slots", 3))
        res = engine.run(
            strategy_instance=strat, pairlist=pairs, timeframe="1d",
            timerange=args.timerange, initial_balance=args.balance,
            max_open_trades=slots, fee=args.fee, benchmark=args.benchmark,
        )
        m = res.metrics

        def g(key, default=None):
            if isinstance(m, dict):
                return m.get(key, default)
            return getattr(m, key, default)
        days = max(1.0, float(g("backtest_days") or 1))
        total = float(g("total_profit_pct") or 0)
        cagr = ((1 + total / 100) ** (365.25 / days) - 1) * 100
        row = dict(variant=name, trades=g("total_trades"),
                   ret=total, cagr=cagr,
                   dd=float(g("max_drawdown") or 0) * 100
                   if (g("max_drawdown") or 0) <= 1 else g("max_drawdown"),
                   pf=g("profit_factor"),
                   win=float(g("win_rate") or 0) * 100,
                   bm=float(g("benchmark_return_pct") or 0),
                   excess=float(g("excess_return_pct") or 0))
        rows.append(row)
        print(f"{name:<12} {row['trades']:>4} {row['ret']:>8.2f} "
              f"{row['cagr']:>7.2f} {row['dd']:>6.2f} "
              f"{float(row['pf'] or 0):>5.2f} {row['win']:>6.1f} "
              f"{row['bm']:>7.2f} {row['excess']:>8.2f}")

    if args.out:
        pd.DataFrame(rows).to_csv(args.out, index=False)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
