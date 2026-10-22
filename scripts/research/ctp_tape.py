#!/usr/bin/env python3
"""Land CTP market data to per-contract 1-minute bars.

The free daily sources stop at "main continuous" and give no minute history
(akshare only returns a rolling 1023 bars), so minute research needs a
collector of our own. This script connects to a CTP market-data front
(SimNow by default, a broker front for live), subscribes to the near
contracts of the requested products and writes 1-minute bars to disk.

Bars are keyed by the counter's own TradingDay, so the night session
(21:00-02:30) lands on the trading day it belongs to - the same convention
the daily series uses. One file per contract and trading day, rewritten as
the day progresses, so a crash loses at most the last flush.

Usage:
  python3 ctp_tape.py --dry-run --products RB,IF,AU
  python3 ctp_tape.py --products RB,IF,AU --user 12345678 --password secret \
      --out /opt/bullseye/user_data/data/futures_tape --duration 3600
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DEFAULT_PRODUCTS = "RB,IF,IH,IC,IM,AU,AG,CU,AL,ZN,M,Y,P,C,SR,TA,MA,FG,I,SC,T"
#: How many near contracts per product to subscribe to (the dominant one is
#: always inside this window).
NEAR_CONTRACTS = 6
#: Bars per (contract, trading day) are written to
#: <out>/1m/{contract}-{trading_day}.parquet
FLUSH_SECONDS = 30


def near_contracts(product: str, count: int = NEAR_CONTRACTS,
                   today: datetime | None = None) -> list:
    """Near contract codes of a product: current month plus the next ones.

    Chinese futures list every month, so the current and the following
    months cover the dominant contract of every product at all times.
    """
    today = today or datetime.now()
    year, month = today.year, today.month
    codes = []
    for i in range(count):
        m = month + i
        y = year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        codes.append("%s%02d%02d" % (product.upper(), y % 100, m))
    return codes


class Tape:
    """Aggregates CTP ticks into 1-minute bars and writes them to disk."""

    def __init__(self, out_dir: Path, save_ticks: bool = False):
        self.out_dir = out_dir
        self.bar_dir = out_dir / "1m"
        self.tick_dir = out_dir / "ticks"
        self.save_ticks = save_ticks
        self.bars: dict = {}          # (contract, day) -> {minute: bar}
        self.ticks: dict = {}         # (contract, day) -> list of ticks
        self.last_write = 0.0

    # ------------------------------------------------------------------
    def on_tick(self, tick) -> None:
        """Handle one depth market data tick."""
        contract = str(tick.InstrumentID)
        price = float(tick.LastPrice or 0.0)
        volume = float(tick.Volume or 0.0)
        if price <= 0:
            return
        trading_day = str(tick.TradingDay or "")
        update_time = str(tick.UpdateTime or "")
        if not trading_day or not update_time:
            return
        minute = update_time[:5]
        key = (contract, trading_day)
        day_bars = self.bars.setdefault(key, {})
        bar = day_bars.get(minute)
        if bar is None:
            # CTP's Volume is cumulative per trading day: the minute volume is
            # the difference to the previous tick, so a fresh bar starts at 0
            # and remembers the cumulative value it was opened at.
            day_bars[minute] = {
                "minute": minute, "open": price, "high": price, "low": price,
                "close": price, "volume": 0.0, "last_volume": volume,
                "open_interest": float(tick.OpenInterest or 0.0),
                "exchange": str(tick.ExchangeID or ""),
                "action_day": str(tick.ActionDay or ""),
            }
        else:
            bar["high"] = max(bar["high"], price)
            bar["low"] = min(bar["low"], price)
            bar["close"] = price
            # CTP volume is cumulative per session: derive the minute volume
            if volume >= bar["last_volume"]:
                bar["volume"] += volume - bar["last_volume"]
            bar["last_volume"] = volume
            bar["open_interest"] = float(tick.OpenInterest or 0.0)
        if self.save_ticks:
            self.ticks.setdefault(key, []).append({
                "time": update_time, "price": price, "volume": volume,
                "open_interest": float(tick.OpenInterest or 0.0),
                "bid": float(tick.BidPrice1 or 0.0),
                "ask": float(tick.AskPrice1 or 0.0),
            })

    # ------------------------------------------------------------------
    def flush(self, force: bool = False) -> None:
        """Write the buffered bars (and ticks) to parquet."""
        now = time.time()
        if not force and now - self.last_write < FLUSH_SECONDS:
            return
        self.last_write = now
        import pandas as pd
        for (contract, day), day_bars in self.bars.items():
            if not day_bars:
                continue
            rows = []
            for minute in sorted(day_bars):
                bar = day_bars[minute]
                rows.append({
                    "date": pd.Timestamp("%s %s" % (day, minute)),
                    "open": bar["open"], "high": bar["high"],
                    "low": bar["low"], "close": bar["close"],
                    "volume": bar["volume"],
                    "hold": bar["open_interest"],
                    "exchange": bar["exchange"],
                    "trading_day": day,
                    "action_day": bar.get("action_day", ""),
                })
            frame = pd.DataFrame(rows)
            path = self.bar_dir / ("%s-%s.parquet" % (contract, day))
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(path, index=False)
            if self.save_ticks:
                ticks = self.ticks.get((contract, day))
                if ticks:
                    tick_path = self.tick_dir / ("%s-%s.parquet" % (contract, day))
                    tick_path.parent.mkdir(parents=True, exist_ok=True)
                    pd.DataFrame(ticks).to_parquet(tick_path, index=False)
        self.ticks.clear()


def run(args) -> int:
    products = [p.strip().upper() for p in args.products.split(",") if p.strip()]
    today = datetime.now()
    codes = []
    for product in products:
        codes.extend(near_contracts(product, args.near, today))
    print("products: %s" % ",".join(products))
    print("subscribing %d contracts: %s" % (len(codes), ",".join(codes)))
    if args.dry_run:
        print("--dry-run: not connecting")
        return 0

    try:
        from openctp_ctp import thostmduserapi as mdapi
    except ImportError as exc:
        print("openctp-ctp is required: pip install openctp-ctp==6.7.11.*", file=sys.stderr)
        print("(%s)" % exc, file=sys.stderr)
        print("On Linux the CTP libraries also need the zh_CN.GB18030 locale; "
              "the bullseye image already has it.", file=sys.stderr)
        return 2

    state = {"subscribed": False}

    class MdSpi(mdapi.CThostFtdcMdSpi):
        def OnFrontConnected(self):
            print("[md] front connected", flush=True)
            req = mdapi.CThostFtdcReqUserLoginField()
            req.BrokerID = args.broker_id
            req.UserID = args.user
            req.Password = args.password
            self.api.ReqUserLogin(req, 0)

        def OnFrontDisconnected(self, nReason):
            print("[md] front disconnected reason=%s" % nReason, flush=True)

        def OnRspUserLogin(self, pRsp, pInfo, nRequestID, bIsLast):
            print("[md] login err=%s msg=%r"
                  % (pInfo.ErrorID, pInfo.ErrorMsg), flush=True)
            if pInfo.ErrorID == 0:
                # The instrument array is the one place where openctp still
                # wants bytes (its char** typemap); every char* field takes str.
                self.api.SubscribeMarketData(
                    [c.encode() for c in codes], len(codes))
                state["subscribed"] = True
                print("[md] subscribed %d contracts" % len(codes), flush=True)

        def OnRspSubMarketData(self, pInstrument, pInfo, nRequestID, bIsLast):
            if pInfo.ErrorID != 0:
                print("[md] subscribe failed %s: %s"
                      % (pInstrument.InstrumentID, pInfo.ErrorMsg), flush=True)

        def OnRtnDepthMarketData(self, pDepthMarketData):
            tape.on_tick(pDepthMarketData)

        def OnRspError(self, pRsp, pInfo, nRequestID, bIsLast):
            print("[md] error %s: %r" % (pInfo.ErrorID, pInfo.ErrorMsg), flush=True)

    tape = Tape(Path(args.out), save_ticks=args.save_ticks)
    flow = Path(args.flow or (str(Path(args.out) / "ctp_flow")))
    (flow / "Md").mkdir(parents=True, exist_ok=True)
    api = mdapi.CThostFtdcMdApi.CreateFtdcMdApi(str(flow / "Md"))
    spi = MdSpi()
    spi.api = api
    api.RegisterSpi(spi)
    api.RegisterFront(args.md_address)
    api.Init()

    print("[tape] writing to %s/1m" % args.out, flush=True)
    started = time.time()
    try:
        while True:
            time.sleep(1)
            tape.flush()
            if args.duration and (time.time() - started) > args.duration:
                print("[tape] duration reached", flush=True)
                break
            if args.max_bars and sum(len(b) for b in tape.bars.values()) >= args.max_bars:
                print("[tape] max bars reached", flush=True)
                break
    except KeyboardInterrupt:
        print("[tape] interrupted", flush=True)
    finally:
        tape.flush(force=True)
        try:
            api.Release()
        except Exception:
            pass
    total = sum(len(b) for b in tape.bars.values())
    print("[tape] done: %d bars in %d contract-days" % (total, len(tape.bars)), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products", default=DEFAULT_PRODUCTS)
    parser.add_argument("--near", type=int, default=NEAR_CONTRACTS)
    parser.add_argument("--out", default="/opt/bullseye/user_data/data/futures_tape")
    parser.add_argument("--user", default=os.environ.get("CTP_USER_ID", ""))
    parser.add_argument("--password", default=os.environ.get("CTP_PASSWORD", ""))
    parser.add_argument("--broker-id", default="9999")
    parser.add_argument("--md-address", default="tcp://182.254.243.31:30011")
    parser.add_argument("--flow", default="")
    parser.add_argument("--duration", type=int, default=0,
                        help="stop after N seconds (0 = run until Ctrl-C)")
    parser.add_argument("--max-bars", type=int, default=0,
                        help="stop after N bars have been collected")
    parser.add_argument("--save-ticks", action="store_true",
                        help="also write the raw ticks to disk")
    parser.add_argument("--dry-run", action="store_true",
                        help="only list the contracts that would be subscribed")
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
