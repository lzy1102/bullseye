#!/usr/bin/env python3
"""Daily backtest on Chinese futures main-continuous contracts.

Uses the real contract specs written by futures_daily_data.py: contract
multiplier, margin rate, per-lot fees (including the close-today rate) and
the exchange price-limit band.

Usage:
  python3 futures_backtest.py --pairs RB0@SHFE,IF0@CFFEX --capital 1000000
  python3 futures_backtest.py --strategy MacdCandle --timerange 20230101-20261010
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from bullseye.backtesting.engine import BacktestEngine  # noqa: E402
from bullseye.configuration.config import Config  # noqa: E402
from bullseye.strategy.interface import IStrategy  # noqa: E402

DATA_DIR = REPO_ROOT / "user_data" / "data" / "futures"


class SmaCrossStrategy(IStrategy):
    """Built-in fallback: 20/60 MA cross on the daily bar."""

    timeframe = "1d"
    startup_candle_count = 60
    minimal_roi = {"0": 0.30}
    stoploss = -0.08

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe["sma20"] = dataframe["close"].rolling(20).mean()
        dataframe["sma60"] = dataframe["close"].rolling(60).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe.loc[
            (dataframe["sma20"] > dataframe["sma60"])
            & (dataframe["sma20"].shift(1) <= dataframe["sma60"].shift(1)),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe.loc[
            (dataframe["sma20"] < dataframe["sma60"])
            & (dataframe["sma20"].shift(1) >= dataframe["sma60"].shift(1)),
            "exit_long",
        ] = 1
        return dataframe


def load_strategy(name: str):
    """Load a repo strategy by name (user_data/strategies/<Name>.py)."""
    strategies_dir = REPO_ROOT / "user_data" / "strategies"
    path = strategies_dir / ("%s.py" % name)
    if not path.exists():
        raise SystemExit("strategy not found: %s" % path)
    sys.path.insert(0, str(strategies_dir))
    module = __import__(name)
    return getattr(module, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", default="RB0@SHFE,IF0@CFFEX,AU0@SHFE,M0@DCE")
    parser.add_argument("--capital", type=float, default=1_000_000.0)
    parser.add_argument("--stake", type=float, default=200_000.0,
                        help="margin committed per position")
    parser.add_argument("--max-trades", type=int, default=3)
    parser.add_argument("--timerange", default="20230101-20261010")
    parser.add_argument("--strategy", default="")
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    args = parser.parse_args()

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    data_dir = Path(args.data_dir)

    config = Config()
    config.set("stake_currency", "CNY")
    config.set("stake_amount", args.stake)
    config.set("max_open_trades", args.max_trades)
    config.set("dry_run", True)
    config.set("dry_run_wallet", args.capital)
    config.set("fee", 0.0)
    config.set("datadir", str(data_dir.parent))
    config.set("exchange.name", "futures")
    config.set("futures.contracts_file", str(data_dir / "contracts.json"))

    strategy_cls = load_strategy(args.strategy) if args.strategy else SmaCrossStrategy

    data = {}
    for pair in pairs:
        path = data_dir / ("%s-1d.parquet" % pair)
        if not path.exists():
            print("[skip] %s (no %s)" % (pair, path.name), file=sys.stderr)
            continue
        data[pair] = pd.read_parquet(path)
    if not data:
        raise SystemExit("no data found in %s" % data_dir)

    engine = BacktestEngine(config)
    result = engine.run(
        strategy_class=strategy_cls,
        pairlist=list(data.keys()),
        timeframe="1d",
        timerange=args.timerange,
        data=data,
    )

    metrics = result.metrics
    print("=== futures backtest: %s | %s | %s ===" % (
        args.strategy or "SmaCross", args.timerange, ",".join(data.keys())))
    for name in ("total_trades", "win_rate", "profit_total", "profit_total_abs",
                 "max_drawdown", "max_drawdown_abs", "final_balance",
                 "trades_per_day", "wins", "losses", "draws"):
        if hasattr(metrics, name):
            print("  %-22s %s" % (name, getattr(metrics, name)))
    if result.trades:
        fees = sum(t.fee_open + t.fee_close for t in result.trades)
        wins = [t for t in result.trades if t.profit_abs > 0]
        losses = [t for t in result.trades if t.profit_abs < 0]
        print("  %-22s %.2f" % ("total_fees", fees))
        print("  %-22s %.2f" % ("avg_profit_per_trade",
                                 sum(t.profit_abs for t in result.trades) / len(result.trades)))
        if wins:
            print("  %-22s %.2f" % ("avg_win", sum(t.profit_abs for t in wins) / len(wins)))
        if losses:
            print("  %-22s %.2f" % ("avg_loss", sum(t.profit_abs for t in losses) / len(losses)))
        print("--- last 5 trades ---")
        for t in result.trades[-5:]:
            print("  %s %s->%s lots=%.0f stake=%.0f fee=%.2f pnl=%.2f (%.2f%%) %s" % (
                t.pair, t.entry_date.date(), t.exit_date.date(), t.amount,
                t.stake_amount, t.fee_open + t.fee_close, t.profit_abs,
                t.profit_pct, t.exit_reason))


if __name__ == "__main__":
    main()
