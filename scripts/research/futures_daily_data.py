#!/usr/bin/env python3
"""Build a Chinese futures daily dataset for the backtest engine.

Sources (akshare, free):
  * futures_main_sina(symbol="RB0")   -> main-continuous daily OHLC + settlement
  * futures_fees_info()                -> per-contract multiplier, tick, fees,
                                          margin rate/amount (refreshed daily)

Output layout (compatible with bullseze's parquet handler):
  <out>/{PAIR}-1d.parquet       date/open/high/low/close/volume/hold/settle/pre_settle
  <out>/{PAIR}-1d.meta.json     sidecar in the repo's meta convention
  <out>/contracts.json           contract specs keyed by pair

Pairs use the engine's futures convention: {PRODUCT}0@{EXCHANGE} (e.g. RB0@SHFE).

Usage:
  python3 futures_daily_data.py --out /opt/bullseye/user_data/data/futures
  python3 futures_daily_data.py --out ... --symbols RB0,IF0 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import akshare
import pandas as pd

# product -> exchange. akshare main-continuous symbols are "<PRODUCT>0".
DEFAULT_SYMBOLS = [
    "IF0",   # 沪深300股指
    "IH0",   # 上证50
    "IC0",   # 中证500
    "IM0",   # 中证1000
    "RB0",   # 螺纹钢
    "I0",    # 铁矿石
    "CU0",   # 沪铜
    "AL0",   # 沪铝
    "ZN0",   # 沪锌
    "AU0",   # 沪金
    "AG0",   # 沪银
    "M0",    # 豆粕
    "Y0",    # 豆油
    "P0",    # 棕榈油
    "C0",    # 玉米
    "SR0",   # 白糖
    "TA0",   # PTA
    "MA0",   # 甲醇
    "FG0",   # 玻璃
    "SC0",   # 原油
    "T0",    # 10年国债
]

EXCHANGE_OF = {
    "IF": "CFFEX", "IH": "CFFEX", "IC": "CFFEX", "IM": "CFFEX", "T": "CFFEX",
    "RB": "SHFE", "CU": "SHFE", "AL": "SHFE", "ZN": "SHFE", "AU": "SHFE",
    "AG": "SHFE", "SP": "SHFE", "FU": "SHFE", "BU": "SHFE", "RU": "SHFE",
    "I": "DCE", "M": "DCE", "Y": "DCE", "P": "DCE", "C": "DCE", "A": "DCE",
    "PP": "DCE", "L": "DCE", "V": "DCE", "EG": "DCE", "EB": "DCE",
    "SR": "CZCE", "TA": "CZCE", "MA": "CZCE", "FG": "CZCE", "SA": "CZCE",
    "OI": "CZCE", "RM": "CZCE", "CF": "CZCE", "AP": "CZCE", "UR": "CZCE",
    "SC": "INE",
}

# Exchange price-limit bands (fraction of previous settlement). Chinese futures
# limits are set per contract; these are the exchange defaults and can be
# overridden in contracts.json by hand.
DEFAULT_LIMIT_RATIO = {
    "CFFEX": 0.10,
    "SHFE": 0.08,
    "DCE": 0.08,
    "CZCE": 0.08,
    "INE": 0.10,
}


def product_of(symbol: str) -> str:
    """RB0 -> RB, IF0 -> IF."""
    return symbol.rstrip("0") or symbol


def pair_of(symbol: str) -> str:
    """RB0 -> RB0@SHFE."""
    prod = product_of(symbol)
    exch = EXCHANGE_OF.get(prod, "SHFE")
    return "%s@%s" % (symbol, exch)


def _num(value, default=0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(out):
        return default
    return out


def fetch_fee_table() -> pd.DataFrame:
    """Per-contract fee/margin table (akshare)."""
    return akshare.futures_fees_info()


def _fixed_fee(value) -> float:
    """Fixed per-lot fee in CNY.

    akshare's "开仓费用/手" column carries the exchange's *fixed* per-lot fee
    plus a 0.01 CNY rounding artifact from the upstream site (3.01 for a 3 CNY
    fee, 1.51 for 1.5, 0.01 for "none"). The variable part is carried
    separately in the rate columns and applied to the traded notional.
    """
    fee = _num(value)
    if fee <= 0:
        return 0.0
    return max(0.0, round(fee - 0.01, 2))


def pick_contract_row(fees: pd.DataFrame, product: str) -> dict:
    """Representative contract spec for a product: the most active contract."""
    rows = fees[fees["品种代码"].astype(str).str.upper() == product.upper()]
    if rows.empty:
        return {}
    rows = rows.copy()
    rows["_volume"] = rows["成交量"].apply(_num)
    rows = rows.sort_values("_volume", ascending=False)
    row = rows.iloc[0]

    close_fixed = _fixed_fee(row.get("平仓费用/手"))
    close_today_fixed = _fixed_fee(row.get("平今费用/手"))
    if close_today_fixed <= 0 and close_fixed > 0:
        # No close-today column for this product: exchanges charge close-today
        # at (at least) the close fee, so keep the fixed part and let the
        # close-today rate column add any surcharge.
        close_today_fixed = close_fixed

    return {
        "contract": str(row["合约代码"]),
        "multiplier": _num(row.get("合约乘数"), 1.0) or 1.0,
        "tick_size": _num(row.get("最小跳动"), 0.01),
        "open_fee_fixed_per_lot": _fixed_fee(row.get("开仓费用/手")),
        "close_fee_fixed_per_lot": close_fixed,
        "close_today_fee_fixed_per_lot": close_today_fixed,
        "open_fee_rate": _num(row.get("开仓费率")),
        "close_fee_rate": _num(row.get("平仓费率")),
        "close_today_fee_rate": _num(row.get("平今费率")),
        "margin_rate": _num(row.get("做多保证金率")),
        "short_margin_rate": _num(row.get("做空保证金率")),
        "last_settle": _num(row.get("上日结算价")),
        "last_price": _num(row.get("最新价")),
        "notional_per_lot": _num(row.get("1手市值")),
    }


def fetch_daily(symbol: str) -> pd.DataFrame:
    """Main-continuous daily bars with settlement price."""
    raw = akshare.futures_main_sina(symbol=symbol)
    if raw is None or raw.empty:
        raise ValueError("no data for %s" % symbol)
    df = pd.DataFrame({
        "date": pd.to_datetime(raw["日期"]),
        "open": raw["开盘价"].apply(_num),
        "high": raw["最高价"].apply(_num),
        "low": raw["最低价"].apply(_num),
        "close": raw["收盘价"].apply(_num),
        "volume": raw["成交量"].apply(_num),
        "hold": raw["持仓量"].apply(_num) if "持仓量" in raw else 0.0,
        "settle": raw["动态结算价"].apply(_num) if "动态结算价" in raw else 0.0,
    })
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    # sina leaves 动态结算价 at 0 for some products; fall back to the close.
    df.loc[df["settle"] <= 0, "settle"] = df.loc[df["settle"] <= 0, "close"]
    df["pre_settle"] = df["settle"].shift(1)
    # Main-continuous roll artifacts can produce bars whose high/low do not
    # contain the open/close; widen them so the bar stays self-consistent.
    df["high"] = df[["high", "open", "close"]].max(axis=1)
    df["low"] = df[["low", "open", "close"]].min(axis=1)
    return df


def write_dataset(out_dir: Path, symbols, dry_run: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    fees = fetch_fee_table()
    contracts = {}
    summary = []

    for symbol in symbols:
        product = product_of(symbol)
        pair = pair_of(symbol)
        try:
            df = fetch_daily(symbol)
        except Exception as exc:
            print("[skip] %s: %s" % (symbol, exc), file=sys.stderr)
            continue

        spec = pick_contract_row(fees, product)
        exchange = pair.split("@", 1)[1]
        spec.update({
            "pair": pair,
            "symbol": symbol,
            "product": product,
            "exchange": exchange,
            "lot": 1,
            "limit_ratio": DEFAULT_LIMIT_RATIO.get(exchange, 0.08),
            "fee_source": "akshare.futures_fees_info",
            "spec_asof": str(fees["更新时间"].iloc[0]) if "更新时间" in fees else None,
        })
        contracts[pair] = spec

        rows = len(df)
        first, last = str(df["date"].iloc[0].date()), str(df["date"].iloc[-1].date())
        summary.append((pair, rows, first, last, spec["multiplier"],
                        spec["tick_size"], spec["open_fee_fixed_per_lot"],
                        spec["close_fee_fixed_per_lot"],
                        spec["close_today_fee_fixed_per_lot"],
                        spec["open_fee_rate"], spec["close_today_fee_rate"],
                        spec["margin_rate"]))

        if dry_run:
            continue

        parquet_path = out_dir / ("%s-1d.parquet" % pair)
        df.to_parquet(parquet_path, index=False)
        meta = {
            "symbol": pair,
            "timeframe": "1d",
            "datafeed": "akshare:futures_main_sina",
            "product": product,
            "exchange": exchange,
            "downloaded_at": datetime.now().isoformat(),
            "rows": rows,
            "date_from": first,
            "date_to": last,
        }
        (out_dir / ("%s-1d.meta.json" % pair)).write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    if not dry_run:
        contracts_path = out_dir / "contracts.json"
        payload = {
            "generated_at": datetime.now().isoformat(),
            "source": "akshare",
            "note": "main-continuous proxies; fees/margin/specs taken from the "
                    "most active contract of each product on the fetch date",
            "contracts": contracts,
        }
        contracts_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("pair | rows | from | to | mult | tick | open_fix | close_fix | ct_fix | "
          "open_rate | ct_rate | margin_rate")
    for row in summary:
        print("%s | %d | %s | %s | %g | %g | %g | %g | %g | %g | %g | %.3f" % row)
    print("\n%d/%d symbols written to %s" % (len(summary), len(symbols), out_dir))
    return contracts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/opt/bullseye/user_data/data/futures")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    write_dataset(Path(args.out), symbols, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
