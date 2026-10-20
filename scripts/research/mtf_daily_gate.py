#!/usr/bin/env python3
"""Multi-timeframe scan: daily regime gate + 30m entry patterns.

For a 30m bar on day D, the last completed daily bar is D-1, so the daily
regime is shifted by one trading day before it is merged onto intraday bars.

Usage: python3 mtf_daily_gate.py [start] [end] [tf]
Default: 2023-01-01 2026-10-10 30m
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/bullseye/user_data/strategies")
sys.path.insert(0, "/opt/bullseye/user_data")

from candle_patterns import detect, indicator_states  # noqa: E402

DATA = "/opt/bullseye/user_data/data"
PAIRS = [
    "000001.SZ", "000063.SZ", "000333.SZ", "000651.SZ", "002475.SZ",
    "002594.SZ", "300750.SZ", "300760.SZ", "600016.SH", "600030.SH",
    "600036.SH", "600276.SH", "600309.SH", "600887.SH", "600900.SH",
    "600941.SH", "601088.SH", "601288.SH", "601318.SH", "601398.SH",
    "601899.SH", "601939.SH", "601988.SH", "603259.SH", "688981.SH",
]


def daily_regime(pair):
    df = pd.read_parquet(f"{DATA}/{pair}-1d.parquet")
    df["day"] = pd.to_datetime(df["date"]).dt.date
    close = df["close"]
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    df["up"] = close > ma60
    df["strong"] = (close > ma60) & (ma20 > ma60) & (ma20 > ma20.shift(5))
    df["down"] = close < ma60
    for c in ("up", "strong", "down"):
        df[c] = df[c].shift(1)  # regime known before day D opens
    return df[["day", "up", "strong", "down"]]


def prep_intraday(pair, tf, start, end):
    df = pd.read_parquet(f"{DATA}/{pair}-{tf}.parquet")
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    df["pair"] = pair
    df["day"] = df["date"].dt.date
    df["tod"] = df["date"].dt.strftime("%H:%M")
    for pat, s in detect(df).items():
        df[pat] = s
    for name, s in indicator_states(df).items():
        if isinstance(s, pd.Series) and s.dtype == bool:
            df[f"st_{name}"] = s
    close = df["close"]
    for k in (4, 8, 16):
        df[f"f{k}"] = close.shift(-k) / close - 1
    df["ma20"] = close.rolling(20).mean()
    df["eod"] = df.groupby("day")["close"].transform("last") / close - 1
    reg = daily_regime(pair)
    return df.merge(reg, on="day", how="left")


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "2023-01-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2026-10-10"
    tf = sys.argv[3] if len(sys.argv) > 3 else "30m"

    big = pd.concat([prep_intraday(p, tf, start, end) for p in PAIRS],
                    ignore_index=True)
    base = big.groupby("tod")[["f4", "f8", "f16"]].mean()
    for k in (4, 8, 16):
        big[f"x{k}"] = big[f"f{k}"] - big["tod"].map(base[f"f{k}"])

    n_bars = len(big)
    print(f"=== MTF {tf} | {start}~{end} | {len(PAIRS)} pairs | bars={n_bars:,} ===")
    print(f"daily up share={big['up'].mean() * 100:.1f}%  "
          f"strong={big['strong'].mean() * 100:.1f}%  down={big['down'].mean() * 100:.1f}%")

    rows = []

    def add(name, mask):
        s = big[mask & big["f4"].notna()]
        if len(s) < 100:
            rows.append((name, len(s), *[np.nan] * 6))
            return
        rows.append((
            name, len(s),
            s["x4"].mean() * 100, (s["f4"] > 0).mean() * 100,
            s["x8"].mean() * 100, s["x16"].mean() * 100,
            s["eod"].mean() * 100,
            s["f4"].mean() * 100,
        ))

    for regime, rmask in (("up", big["up"]), ("strong", big["strong"]),
                          ("down", big["down"])):
        add(f"{regime}:all", rmask)
        add(f"{regime}:hammer", rmask & big["hammer"])
        add(f"{regime}:hammer+macd_bottom",
            rmask & big["hammer"] & big["st_macd_bottom"])
        add(f"{regime}:bull_engulfing", rmask & big["bull_engulfing"])
        add(f"{regime}:morning_star", rmask & big["morning_star"])
        add(f"{regime}:macd_bottom", rmask & big["st_macd_bottom"])
        add(f"{regime}:macd_bottom+<ma20",
            rmask & big["st_macd_bottom"] & (big["close"] < big["ma20"]))
        add(f"{regime}:hammer+<ma20",
            rmask & big["hammer"] & (big["close"] < big["ma20"]))

    cols = ["signal", "n", "x4%", "win4%", "x8%", "x16%", "eod%", "f4%"]
    res = pd.DataFrame(rows, columns=cols)
    print(res.round(2).to_string(index=False))

    ok = res.dropna(subset=["x4%"]).sort_values("x4%", ascending=False)
    print("\ntop by x4:")
    print(ok.head(10).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
