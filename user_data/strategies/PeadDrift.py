"""
PeadDrift - 财报后漂移 (PEAD), 1d.

原理: 业绩超预期公告后, 股价在1-2个月内继续漂移 (A股财报后效应明显).
信号: 季报同比增速 (netProfit为累计值, 同季度同比) >= threshold 视为超预期.
- 进: 公告日之后第一个交易日 (yoy>=threshold, 前值>0才有意义).
- 出: 持有 hold_days 个自然日后自动走 / -8%止损 (stoploss).
- 仓位: 等权 total/max_slots.
数据: pead_profit.csv (baostock query_profit_data, 2021Q1-2026Q2, 34只池).
"""
import csv
import numpy as np
import pandas as pd
from pandas import DataFrame
from pathlib import Path

from bullseye.strategy import IStrategy

try:
    _CSV = Path(__file__).with_name("pead_profit.csv")
    _ROWS = list(csv.DictReader(_CSV.open(encoding="utf-8")))
except Exception:  # pragma: no cover
    _ROWS = []

_EVENTS: dict = {}
for _r in _ROWS:
    try:
        _EVENTS.setdefault(_r["pair"], []).append(
            {
                "pub": pd.Timestamp(_r["pubDate"]),
                "year": int(_r["year"]),
                "quarter": int(_r["quarter"]),
                "np": float(_r["netProfit"]) if _r["netProfit"] else float("nan"),
            }
        )
    except Exception:
        continue

# per-pair YoY per event
for _p, _evs in _EVENTS.items():
    _by_q = {(e["year"], e["quarter"]): e for e in _evs}
    for e in _evs:
        prev = _by_q.get((e["year"] - 1, e["quarter"]))
        if prev and prev["np"] and prev["np"] > 0 and not pd.isna(e["np"]):
            e["yoy"] = (e["np"] - prev["np"]) / abs(prev["np"])
        else:
            e["yoy"] = float("nan")


class PeadDrift(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = -0.08
    trailing_stop = False

    position_adjustment_enable = False

    threshold: float = 0.20   # 同比增速门槛
    hold_days: int = 60       # 漂移持有窗口 (自然日)
    max_slots: int = 8

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ma20"] = dataframe["close"].rolling(20).mean()
        pair = metadata.get("pair", "")
        enter_idx, exit_idx = set(), set()
        if pair in _EVENTS and len(dataframe) > 0:
            dates = pd.to_datetime(dataframe["date"]).values
            for e in _EVENTS[pair]:
                yoy = e.get("yoy", float("nan"))
                if pd.isna(yoy) or yoy < self.threshold:
                    continue
                i = int(np.searchsorted(dates, np.datetime64(e["pub"]), side="right"))
                if 0 <= i < len(dates) - 1:
                    enter_idx.add(i)
                j = int(np.searchsorted(
                    dates,
                    np.datetime64(e["pub"]) + np.timedelta64(self.hold_days, "D"),
                    side="right",
                ))
                if j < len(dates):
                    exit_idx.add(j)
        dataframe["enter_long"] = 0
        dataframe["exit_long"] = 0
        if enter_idx:
            idx = sorted(enter_idx)
            dataframe.loc[dataframe.index[idx], ["enter_long"]] = 1
            dataframe.loc[dataframe.index[idx], ["enter_tag"]] = "pead"
        if exit_idx:
            idx = sorted(exit_idx)
            dataframe.loc[dataframe.index[idx], ["exit_long"]] = 1
            dataframe.loc[dataframe.index[idx], ["exit_tag"]] = "pead_end"
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if "enter_long" in dataframe:
            dataframe.loc[
                (dataframe["enter_long"] == 1) & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "pead")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if "exit_long" in dataframe:
            dataframe.loc[
                (dataframe["exit_long"] == 1) & (dataframe["volume"] > 0),
                ["exit_long", "exit_tag"],
            ] = (1, "pead_end")
        return dataframe

    def custom_stake_amount(
        self, pair: str, current_time, current_rate: float,
        proposed_stake: float, min_stake, max_stake: float,
        leverage: float, entry_tag, side: str, **kwargs,
    ):
        try:
            total = self.wallets.get_total_stake_amount()
        except Exception:
            return None
        if not total or total <= 0:
            return None
        stake = total / max(1, int(self.max_slots))
        if max_stake and stake > max_stake:
            stake = max_stake
        return stake
