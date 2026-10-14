"""
WideMultiFactor - 宽池多因子组合 (138只全市场样本), 1d.

宽池因子检验(23-26, 20d前瞻)确认: 小市值(小+1.86%/月 vs 大+0.77%)、
非流动性、低换手、低波动 均有正溢价; 全市场动量为负 (mom60 IC-0.075,
反转效应, 与34只精选池相反).
本策略 = 多因子合成:
- score = 低市值 + 低换手 + 低波动 + 反转(近期弱) 四个排名均值.
- 持有 score 前 n_hold 只, 掉出 2*n_hold 换马.
- 无止损无止盈 (纯因子), 月度级别的慢换手.

性能: 因子在 populate_indicators 预算一次存数组, 运行时二分定位 +
按日缓存排名 (140只×890天的 dp 逐日查询会超时).
"""
import numpy as np
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy


class WideMultiFactor(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 280
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    n_hold: int = 10
    mom_window: int = 20
    pool: tuple = ()

    FACTOR_COLS = ("size_log", "turn20", "vol20", "mom20")

    def __init__(self):
        self._store: dict = {}
        self._cache_key = None
        self._cache_top = set()
        self._cache_top2 = set()

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        dataframe["mom20"] = close / close.shift(self.mom_window) - 1
        dataframe["turn20"] = (
            dataframe["turn"].rolling(20).mean()
            if "turn" in dataframe else float("nan")
        )
        dataframe["vol20"] = close.pct_change().rolling(20).std()
        fcap = (
            close * 100.0 * dataframe["volume"]
            / dataframe["turn"].replace(0, np.nan)
        )
        dataframe["size_log"] = np.log10(fcap.where(fcap > 0))

        pair = metadata.get("pair")
        if pair:
            self._store[pair] = {
                "dates": pd.to_datetime(dataframe["date"]).values,
                **{
                    col: pd.to_numeric(
                        dataframe[col], errors="coerce"
                    ).to_numpy(dtype=float)
                    for col in self.FACTOR_COLS
                },
            }
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "wmulti")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe

    def _snapshots(self, current_time) -> dict:
        try:
            ts = pd.Timestamp(current_time).to_datetime64()
        except Exception:
            return {}
        pairs = self.pool if self.pool else list(self._store.keys())
        snap = {}
        for p in pairs:
            data = self._store.get(p)
            if not data:
                continue
            idx = int(np.searchsorted(data["dates"], ts, side="right")) - 1
            if idx < 0:
                continue
            row = {col: data[col][idx] for col in self.FACTOR_COLS}
            if any(pd.isna(v) for v in row.values()):
                continue
            snap[p] = row
        return snap

    def _top_sets(self, current_time):
        key = str(current_time)
        if key == self._cache_key:
            return self._cache_top, self._cache_top2
        snap = self._snapshots(current_time)
        top, top2 = set(), set()
        if len(snap) >= 30:
            df = pd.DataFrame(snap).T
            parts = []
            for col in self.FACTOR_COLS:
                ser = df[col].astype(float)
                if ser.notna().sum() < 30:
                    continue
                parts.append(1 - ser.rank(pct=True))
            if parts:
                score = pd.concat(parts, axis=1).mean(axis=1).dropna()
                top = set(score.nlargest(self.n_hold).index)
                top2 = set(score.nlargest(self.n_hold * 2).index)
        self._cache_key = key
        self._cache_top = top
        self._cache_top2 = top2
        return top, top2

    def confirm_trade_entry(
        self, pair: str, order_type: str, amount: float, rate: float,
        time_in_force: str, current_time, entry_tag, side: str, **kwargs,
    ) -> bool:
        if entry_tag != "wmulti":
            return True
        top, _ = self._top_sets(current_time)
        if not top:
            return True
        return pair in top

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        _, top2 = self._top_sets(current_time)
        if top2 and pair not in top2:
            return "rank_out"
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
        stake = total / max(1, int(self.n_hold))
        if max_stake and stake > max_stake:
            stake = max_stake
        return stake
