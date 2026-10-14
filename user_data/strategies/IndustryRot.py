"""
IndustryRot - 行业动量轮动 (吃板块波段), 1d.

思路: 单票动量易被个股噪声和暴雷打脸; 行业动量更稳.
- 行业动量: 行业成员股20日动量均值 (成员取全union池, 含小票以代表板块真实走势).
- 进场: 所属行业排前 top_k (行业动量), 股价 close>MA20>MA60, 流通市值>=300亿
  (小市值不做), 大盘门禁 300指数>MA60.
- 出场: 行业掉出前 top_k*2 / MA20两日跌破 / -10%认错.
- 仓位: 等权 total/max_slots.
行业映射: baostock query_stock_industry, 存 industry_map.json (与本文件同目录).
"""
import json
import numpy as np
import pandas as pd
from pandas import DataFrame
from pathlib import Path

from bullseye.strategy import IStrategy

try:
    INDUSTRY_MAP = json.loads(
        Path(__file__).with_name("industry_map.json").read_text(encoding="utf-8")
    )
except Exception:  # pragma: no cover
    INDUSTRY_MAP = {}


class IndustryRot(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 280
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    top_k: int = 3
    max_slots: int = 6
    wrong_cut: float = -0.10
    min_fcap: float = 3e10  # 300亿流通市值底线
    index_pair: str = "000300.SH"
    pool: tuple = ()
    agg_large_only: bool = False  # 行业动量只用大票成员统计
    reverse: bool = False         # True=买入超跌板块 (板块均值回归)

    def __init__(self):
        self._store: dict = {}
        self._cache_key = None
        self._cache_ok = set()
        self._cache_hold = set()
        self._cache_ready = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        dataframe["mom20"] = close / close.shift(20) - 1
        dataframe["ma20"] = close.rolling(20).mean()
        dataframe["ma60"] = close.rolling(60).mean()
        if "turn" in dataframe:
            fcap = (
                close * 100.0 * dataframe["volume"]
                / dataframe["turn"].replace(0, np.nan)
            )
        else:
            fcap = pd.Series(np.nan, index=dataframe.index)
        dataframe["fcap"] = fcap
        pair = metadata.get("pair")
        if pair:
            self._store[pair] = {
                "dates": pd.to_datetime(dataframe["date"]).values,
                "mom20": pd.to_numeric(dataframe["mom20"], errors="coerce").to_numpy(dtype=float),
                "close": pd.to_numeric(close, errors="coerce").to_numpy(dtype=float),
                "ma20": pd.to_numeric(dataframe["ma20"], errors="coerce").to_numpy(dtype=float),
                "ma60": pd.to_numeric(dataframe["ma60"], errors="coerce").to_numpy(dtype=float),
                "fcap": pd.to_numeric(fcap, errors="coerce").to_numpy(dtype=float),
            }
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        trend = (
            (dataframe["close"] > dataframe["ma20"])
            & (dataframe["ma20"] > dataframe["ma60"])
            & (dataframe["volume"] > 0)
        ).fillna(False)
        dataframe.loc[trend, ["enter_long", "enter_tag"]] = (1, "ind_rot")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        below = (dataframe["close"] < dataframe["ma20"]).fillna(False)
        brk = below & below.shift(1).fillna(False)
        dataframe.loc[
            (brk & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "ma20_break")
        return dataframe

    def _compute(self, current_time):
        key = str(current_time)
        if key == self._cache_key:
            return self._cache_ok, self._cache_hold, self._cache_ready
        self._cache_key = key
        self._cache_ok = set()
        self._cache_hold = set()
        self._cache_ready = False
        try:
            ts = pd.Timestamp(current_time).to_datetime64()
        except Exception:
            return self._cache_ok, self._cache_hold, False
        pairs = self.pool if self.pool else list(self._store.keys())
        snap = {}
        for p in pairs:
            data = self._store.get(p)
            if not data:
                continue
            idx = int(np.searchsorted(data["dates"], ts, side="right")) - 1
            if idx < 0:
                continue
            if np.isnan(data["mom20"][idx]) or np.isnan(data["fcap"][idx]):
                continue
            snap[p] = {
                "mom20": data["mom20"][idx],
                "close": data["close"][idx],
                "ma20": data["ma20"][idx],
                "ma60": data["ma60"][idx],
                "fcap": data["fcap"][idx],
            }
        if len(snap) < 30:
            return self._cache_ok, self._cache_hold, False
        ind_members = {}
        for p, s in snap.items():
            k = INDUSTRY_MAP.get(p)
            if not k:
                continue
            if self.agg_large_only and s["fcap"] < self.min_fcap:
                continue
            ind_members.setdefault(k, []).append(s["mom20"])
        ind_mom = {k: float(np.mean(v)) for k, v in ind_members.items() if v}
        ranked = [k for k, _ in sorted(ind_mom.items(), key=lambda kv: -kv[1])]
        if self.reverse:
            ranked = list(reversed(ranked))
        top_entry = set(ranked[: self.top_k])
        top_hold = set(ranked[: self.top_k * 2])
        ok, hold = set(), set()
        for p, s in snap.items():
            k = INDUSTRY_MAP.get(p)
            if not k:
                continue
            if s["fcap"] >= self.min_fcap and k in top_hold:
                hold.add(p)
            if (
                s["fcap"] >= self.min_fcap
                and k in top_entry
                and s["close"] > s["ma20"] > s["ma60"]
            ):
                ok.add(p)
        self._cache_ok = ok
        self._cache_hold = hold
        self._cache_ready = True
        return ok, hold, True

    def _index_bull(self) -> bool:
        try:
            idx, _ = self.dp.get_analyzed_dataframe(self.index_pair, self.timeframe)
        except Exception:
            return True
        if idx is None or idx.empty or "ma60" not in idx:
            return True
        last = idx.iloc[-1]
        if pd.isna(last["ma60"]):
            return True
        return bool(last["close"] >= last["ma60"])

    def confirm_trade_entry(
        self, pair: str, order_type: str, amount: float, rate: float,
        time_in_force: str, current_time, entry_tag, side: str, **kwargs,
    ) -> bool:
        if entry_tag != "ind_rot":
            return True
        if pair == self.index_pair:
            return False
        if not self._index_bull():
            return False
        ok, _, ready = self._compute(current_time)
        if not ready:
            return True
        return pair in ok

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        if current_profit <= self.wrong_cut:
            return "wrong_cut"
        _, hold, ready = self._compute(current_time)
        if ready and pair not in hold:
            return "ind_out"
        return None

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
