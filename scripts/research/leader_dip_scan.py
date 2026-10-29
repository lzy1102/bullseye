"""LeaderPocDip sweep (research only)."""
import argparse
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.path.insert(0, "user_data/strategies")

from bullseye.backtesting import BacktestEngine  # noqa: E402
from bullseye.configuration import Config  # noqa: E402
from LeaderPocDip import LeaderPocDip  # noqa: E402

BASE = dict(time_stop=10, max_slots=3, stoploss=-0.07, dip_frac=0.33,
            min_bars=15, market_gate=False, spring_atr=1.5, dry_mult=0.60)


def variants():
    out = [("base", {})]
    for t in (5, 20, 40):
        out.append((f"t{t}", {"time_stop": t}))
    for sl in (-0.05, -0.10, -0.15):
        out.append((f"stop{int(abs(sl)*100)}", {"stoploss": sl}))
    out.append(("gate", {"market_gate": True}))
    out.append(("dip50", {"dip_frac": 0.50}))
    out.append(("bars10", {"min_bars": 10}))
    out.append(("bars20", {"min_bars": 20}))
    out.append(("spring2", {"spring_atr": 2.0}))
    out.append(("dry80", {"dry_mult": 0.80}))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="user_data/leader_dip_config.yaml")
    ap.add_argument("--timerange", default="20180101-20261010")
    ap.add_argument("--balance", type=float, default=100000.0)
    args = ap.parse_args()
    cfg = Config(args.config)
    pairs = cfg.get("pairlist", [{}])[0].get("config", {}).get("pairs", [])
    engine = BacktestEngine(config=cfg)
    print(f"{len(pairs)} pairs, {args.timerange}\n")
    hdr = f"{'variant':<10} {'n':>4} {'ret%':>8} {'cagr%':>7} {'dd%':>6} {'pf':>5} {'win%':>6}"
    print(hdr)
    print("-" * len(hdr))
    for name, over in variants():
        s = LeaderPocDip()
        for k, v in {**BASE, **over}.items():
            setattr(s, k, v)
        res = engine.run(strategy_instance=s, pairlist=pairs, timeframe="1d",
                         timerange=args.timerange, initial_balance=args.balance,
                         max_open_trades=s.max_slots, fee=0.001,
                         benchmark="000300.SH")
        m = res.metrics
        g = (lambda k, d=None: m.get(k, d) if isinstance(m, dict) else getattr(m, k, d))
        days = max(1.0, float(g("backtest_days") or 1))
        total = float(g("total_profit_pct") or 0)
        cagr = ((1 + total / 100) ** (365.25 / days) - 1) * 100
        dd = float(g("max_drawdown") or 0)
        dd = dd * 100 if dd <= 1 else dd
        print(f"{name:<10} {g('total_trades'):>4} {total:>8.2f} {cagr:>7.2f} "
              f"{dd:>6.2f} {float(g('profit_factor') or 0):>5.2f} "
              f"{100*float(g('win_rate') or 0):>6.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
