#!/usr/bin/env python3
"""Build a roll-adjusted continuous futures series and the roll events.

sina's "主力连续" (main continuous) series is a raw splice: on the day the
dominant contract changes, the price jumps by the spread between the old and
the new contract. Those jumps are not market moves (a 14% overnight gap in
豆粕, whose limit is 8%, is a splice), and they trigger false signals and
false stop losses.

This builder works from per-contract daily bars instead:

1. fetch every contract of a product (cached on disk),
2. pick the dominant contract per day (volume, with hysteresis),
3. record the roll events (day, old contract, new contract, spread),
4. build the continuous series and remove the spread with an additive
   back-adjustment, so the series is continuous and keeps the market move of
   the new contract on the roll day.

Output (next to the main-continuous files produced by futures_daily_data.py):
  <out>/{PAIR}-1d.parquet      roll-adjusted continuous series (engine input)
  <out>/{PAIR}-1d.raw.parquet  the raw sina main-continuous series (reference)
  <out>/{PAIR}-rolls.json      roll events for the engine's roll-cost model

Usage:
  python3 futures_continuous.py --out /opt/bullseye/user_data/data/futures
  python3 futures_continuous.py --out ... --symbols RB0,IF0 --start 2023-01-01
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from futures_daily_data import EXCHANGE_OF, product_of  # noqa: E402

CACHE_DIRNAME = "_contract_cache"
#: Keep the incumbent contract while its volume is at least this share of the
#: best contract's volume - avoids flip-flopping between two similar contracts.
VOLUME_HYSTERESIS = 0.9
#: Smoothing window (trading days) for the liquidity metric.
VOLUME_WINDOW = 10
#: The challenger must beat the incumbent by this factor to take over.
DOMINANCE_FACTOR = 1.15
#: Minimum trading days between two switches (anti churn).
MIN_HOLD_DAYS = 10
#: Window used to smooth open interest before comparing contracts.
OI_WINDOW = 3


def contract_codes(product: str, start: str, end: str) -> list:
    """Every plausible contract code of a product between two dates.

    The window is extended by one year: the contract that dominates at the
    end of the window is usually next year's first expiry, and it has to be
    in the data or the series stays glued to the expiring contract.
    """
    start_year, start_month = int(start[:4]), int(start[5:7])
    end_year, end_month = int(end[:4]), int(end[5:7])
    codes = []
    for year in range(start_year, end_year + 2):
        for month in range(1, 13):
            if (year, month) < (start_year, start_month):
                continue
            if (year, month) > (end_year + 1, 12):
                continue
            codes.append("%s%02d%02d" % (product, year % 100, month))
    return codes


def fetch_contract(code: str, cache_dir: Path, refresh: bool = False):
    """Daily bars of one contract (cached). None when the code does not exist."""
    import akshare

    cache_path = cache_dir / ("%s.parquet" % code)
    if cache_path.exists() and not refresh:
        try:
            return pd.read_parquet(cache_path)
        except Exception:
            pass
    try:
        df = akshare.futures_zh_daily_sina(symbol=code)
    except Exception as exc:
        print("  [skip] %s: %s" % (code, exc), file=sys.stderr)
        return None
    if df is None or len(df) == 0:
        return None
    if "date" not in df.columns:
        return None
    out = df[["date", "open", "high", "low", "close", "volume", "hold", "settle"]].copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values("date").reset_index(drop=True)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache_path, index=False)
    time.sleep(0.15)  # be gentle with the upstream API
    return out


def dominant_contract(frames: dict):
    """Per-day dominant contract.

    Chinese "主力合约" is defined by open interest, not volume: the volume
    leader rotates between near months (沪铜 has 12 active months), while
    open interest concentrates in the contract traders actually hold and
    only migrates at a real roll. Open interest is therefore the primary
    criterion, volume the tie-break, both smoothed over a few days.

    Dead contracts (past delivery) must not compete: their last value would
    otherwise keep them "dominant" long after they expired, so volumes and
    open interest are zeroed outside each contract's life.
    """
    if not frames:
        return pd.Series(dtype=object)
    index = pd.DatetimeIndex(sorted(
        set().union(*[set(frame["date"]) for frame in frames.values()])
    ))
    alive = pd.DataFrame({
        code: pd.Series(
            (index >= frame["date"].min()) & (index <= frame["date"].max()),
            index=index,
        )
        for code, frame in frames.items()
    })
    volume = pd.DataFrame({
        code: frame.set_index("date")["volume"] for code, frame in frames.items()
    }).reindex(index)
    open_interest = pd.DataFrame({
        code: frame.set_index("date")["hold"] for code, frame in frames.items()
    }).reindex(index)
    volume = volume.where(alive, 0.0)
    open_interest = open_interest.where(alive, 0.0)

    oi_metric = open_interest.rolling(OI_WINDOW, min_periods=1).mean()
    vol_metric = volume.rolling(VOLUME_WINDOW, min_periods=1).sum()
    # Rank by open interest; volume only breaks near ties.
    oi_rank = oi_metric.rank(axis=1, ascending=False, method="min")
    vol_rank = vol_metric.rank(axis=1, ascending=False, method="min")
    combined = oi_rank * 10 + vol_rank
    best = combined.idxmin(axis=1)
    best_oi = oi_metric.max(axis=1)

    chosen = []
    incumbent = None
    last_switch_index = -MIN_HOLD_DAYS
    for position, date in enumerate(index):
        candidate = best.loc[date]
        if incumbent is not None:
            incumbent_oi = oi_metric.at[date, incumbent]
            challenger_oi = oi_metric.at[date, candidate]
            dominant = (
                not pd.isna(challenger_oi)
                and not pd.isna(incumbent_oi)
                and challenger_oi > incumbent_oi * DOMINANCE_FACTOR
            )
            stale = (position - last_switch_index) < MIN_HOLD_DAYS
            if not (dominant and not stale):
                candidate = incumbent
        if candidate not in frames:
            candidate = best.loc[date]
        if candidate not in frames:
            continue
        if candidate != incumbent:
            last_switch_index = position
        chosen.append((date, candidate))
        incumbent = candidate
    return pd.Series({d: c for d, c in chosen}, dtype=object)


def build_continuous(frames: dict):
    """Continuous series from per-contract bars, with roll events.

    Returns (series, rolls) where series carries the additive adjustment and
    rolls lists the switches with the spread that was removed.
    """
    dominant = dominant_contract(frames)
    if dominant.empty:
        return pd.DataFrame(), []

    rows = []
    for date, code in dominant.items():
        frame = frames[code]
        row = frame[frame["date"] == date]
        if row.empty:
            continue
        r = row.iloc[0]
        rows.append({
            "date": date, "contract": code,
            "open": r["open"], "high": r["high"], "low": r["low"],
            "close": r["close"], "volume": r["volume"], "hold": r["hold"],
            "settle": r["settle"],
        })
    series = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    rolls = []
    segments = []
    current = None
    for idx, row in series.iterrows():
        code = row["contract"]
        if current is None:
            current = code
            segments.append([code, idx, idx])
            continue
        if code != current:
            prev_date = series["date"].iloc[idx - 1]
            old = frames[current]
            new = frames[code]
            old_close = old[old["date"] == prev_date]["close"]
            # Spread between the two contracts at the previous close keeps the
            # market move of the new contract on the roll day. A contract that
            # listed on the roll day has no previous bar - fall back to the
            # same-day closes so the splice still gets neutralised.
            new_close = new[new["date"] == prev_date]["close"]
            fallback_old = old[old["date"] == row["date"]]["close"]
            fallback_new = new[new["date"] == row["date"]]["close"]
            if not old_close.empty and not new_close.empty:
                spread = float(new_close.iloc[0]) - float(old_close.iloc[0])
            elif not fallback_old.empty and not fallback_new.empty:
                spread = float(fallback_new.iloc[0]) - float(fallback_old.iloc[0])
            else:
                spread = 0.0
            rolls.append({
                "date": str(row["date"].date()),
                "from": current,
                "to": code,
                "spread": round(spread, 6),
                "segment": len(segments),
            })
            segments[-1][2] = idx - 1
            segments.append([code, idx, idx])
            current = code
        else:
            segments[-1][2] = idx
    segments[-1][2] = len(series) - 1

    # Additive back-adjustment: the most recent segment keeps the real prices
    # and every earlier segment is lifted by the spreads of the rolls that came
    # after it, so the series is continuous at every roll:
    #     old_close + adj(k-1) == new_open + adj(k)
    #   => adj(k) = adj(k-1) - spread(k) => adj(k) = +sum(spread of later rolls)
    # A positive spread (contango) therefore makes the synthetic history trade
    # higher, which is exactly the decay a rolling long pays.
    adj_by_index = {}
    for seg_idx, (code, first, last) in enumerate(segments):
        adj = 0.0
        for roll in rolls:
            if roll["segment"] > seg_idx:
                adj += roll["spread"]
        for idx in range(first, last + 1):
            adj_by_index[idx] = adj
    for roll in rolls:
        seg_idx = roll["segment"]
        roll["adjustment"] = round(adj_by_index.get(segments[seg_idx][1], 0.0), 6)
    adj_series = pd.Series([adj_by_index.get(i, 0.0) for i in range(len(series))])
    for col in ("open", "high", "low", "close", "settle"):
        series[col] = series[col] + adj_series
    series["pre_settle"] = series["settle"].shift(1)
    series["high"] = series[["high", "open", "close"]].max(axis=1)
    series["low"] = series[["low", "open", "close"]].min(axis=1)
    series = series.drop(columns=["contract"])
    return series, rolls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/opt/bullseye/user_data/data/futures")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--start", default="2022-06-01")
    parser.add_argument("--end", default="2026-10-10")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / CACHE_DIRNAME

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = []
        for meta_path in sorted(out_dir.glob("*-1d.meta.json")):
            pair = meta_path.name[: -len("-1d.meta.json")]
            symbol = pair.split("@")[0]
            if symbol and symbol not in symbols:
                symbols.append(symbol)

    for symbol in symbols:
        product = product_of(symbol)
        exchange = EXCHANGE_OF.get(product, "SHFE")
        pair = "%s@%s" % (symbol, exchange)
        print("=== %s (%s)" % (pair, product))

        frames = {}
        for code in contract_codes(product, args.start, args.end):
            frame = fetch_contract(code, cache_dir, refresh=args.refresh)
            if frame is not None and len(frame):
                frames[code] = frame
        if len(frames) < 2:
            print("  not enough contracts (%d) - skipped" % len(frames))
            continue

        series, rolls = build_continuous(frames)
        if series.empty:
            print("  empty series - skipped")
            continue

        out_cols = ["date", "open", "high", "low", "close", "volume", "hold",
                    "settle", "pre_settle"]
        # Keep the raw main-continuous series for reference before we
        # overwrite it with the roll-adjusted one.
        raw_path = out_dir / ("%s-1d.raw.parquet" % pair)
        target = out_dir / ("%s-1d.parquet" % pair)
        if target.exists() and not raw_path.exists():
            try:
                raw = pd.read_parquet(target)
                raw.to_parquet(raw_path, index=False)
            except Exception as exc:
                print("  [warn] cannot keep raw copy: %s" % exc, file=sys.stderr)
        series[out_cols].to_parquet(target, index=False)
        (out_dir / ("%s-rolls.json" % pair)).write_text(
            json.dumps({
                "pair": pair,
                "generated_at": datetime.now().isoformat(),
                "method": "additive back-adjustment, dominant contract by volume",
                "rolls": rolls,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        meta_path = out_dir / ("%s-1d.meta.json" % pair)
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["datafeed"] = "akshare:futures_zh_daily_sina (roll-adjusted)"
            meta["rolls"] = len(rolls)
            meta["rows"] = len(series)
            meta["date_from"] = str(series["date"].iloc[0].date())
            meta["date_to"] = str(series["date"].iloc[-1].date())
            meta_path.write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        print("  contracts=%d rows=%d %s -> %s rolls=%d"
              % (len(frames), len(series), str(series["date"].iloc[0].date()),
                 str(series["date"].iloc[-1].date()), len(rolls)))
        for roll in rolls[-4:]:
            print("    roll %s %s -> %s spread=%+.1f"
                  % (roll["date"], roll["from"], roll["to"], roll["spread"]))


if __name__ == "__main__":
    main()
