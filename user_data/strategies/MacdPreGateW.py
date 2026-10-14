"""
MacdPreGateW - 四大行专用 (601398/601288/601988/601939), 1d.

思路: 黑线DIF拐头提前进 (不等金叉) 吃中段, 日线25/110+周线10/20双门禁拿住
大波段 (601288一笔+114%), 熊市 (周熊) 空仓. 平均持仓171-348天, 一年开不了几枪.
目标: 四大行慢钱, 十年+159.9% (15-26), 23-26约+90% (年化18.6%).
不适合轮动 (太慢) / 龙头AI (门禁套死) ——轮动用 MacdPreRot.
"""
from typing import Dict, Optional

from bullseye.strategy import IStrategy
from pandas import DataFrame


class MacdPreGateW(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 200
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = True
    max_tranches: int = 5
    gate_fast: int = 25
    gate_slow: int = 110
    w_fast: int = 10
    w_slow: int = 20

    def __init__(self):
        self._adds: Dict[str, int] = {}

    def _auto_tranche(self) -> float:
        try:
            total = self.wallets.get_total_stake_amount()
        except Exception:
            total = 0.0
        if total <= 0:
            return 0.0
        return total / max(1, int(self.max_tranches))

    def custom_stake_amount(
        self, pair: str, current_time, current_rate: float,
        proposed_stake: float, min_stake: Optional[float],
        max_stake: float, leverage: float,
        entry_tag: Optional[str], side: str, **kwargs,
    ) -> Optional[float]:
        auto = self._auto_tranche()
        if auto > 0:
            return min(auto, max_stake)
        return None

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        import pandas as pd

        close = dataframe["close"]
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(
            span=26, adjust=False).mean()
        sig = macd.ewm(span=9, adjust=False).mean()
        dataframe["macd"] = macd
        dataframe["macd_sig"] = sig
        dataframe["hist"] = macd - sig
        dataframe["ma_fast"] = close.rolling(self.gate_fast).mean()
        dataframe["ma_slow"] = close.rolling(self.gate_slow).mean()
        dataframe["bull"] = (dataframe["ma_fast"] > dataframe["ma_slow"]).fillna(False)

        # Weekly regime from daily bars (no 1w files needed).
        try:
            d = dataframe.copy()
            d["date"] = pd.to_datetime(d["date"])
            wk = (
                d.set_index("date")["close"]
                .resample("W-FRI")
                .last()
                .dropna()
            )
            w_fast = wk.rolling(self.w_fast).mean()
            w_slow = wk.rolling(self.w_slow).mean()
            w_bull = (w_fast > w_slow).shift(1)  # last CLOSED week only
            w_df = pd.DataFrame({"wbull": w_bull}).dropna()
            w_df["date"] = w_df.index
            m = pd.merge_asof(
                d.sort_values("date"),
                w_df.sort_values("date"),
                on="date",
                direction="backward",
            )
            dataframe["wbull"] = m["wbull"].fillna(False).values
        except Exception:
            dataframe["wbull"] = True
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        h = dataframe["hist"]
        dif_up = (dataframe["macd"] > dataframe["macd"].shift(1)).fillna(False)
        rising2 = ((h > h.shift(1)) & (h.shift(1) > h.shift(2))).fillna(False)
        early = ((h < 0) & rising2 & dif_up).fillna(False)
        cross = (
            (dataframe["macd"] > dataframe["macd_sig"])
            & (dataframe["macd"].shift(1) <= dataframe["macd_sig"].shift(1))
        ).fillna(False)
        wb = dataframe["wbull"].fillna(False) if "wbull" in dataframe else True
        dataframe.loc[
            ((early | cross) & dataframe["bull"] & wb & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "macd_pre_w")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        bear = (dataframe["ma_fast"] < dataframe["ma_slow"]).fillna(False)
        wb = dataframe["wbull"].fillna(False) if "wbull" in dataframe else True
        exit_sig = (bear | (~wb)).fillna(False)
        dataframe.loc[
            (exit_sig & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "gate_bear_w")
        return dataframe

    def adjust_trade_position(
        self, trade, current_time, current_rate: float,
        current_profit: float, min_stake: Optional[float],
        max_stake: float, current_entry_rate: float,
        current_exit_rate: float, current_entry_profit: float,
        current_exit_profit: float, min_limit: float,
        max_limit: float, **kwargs,
    ) -> Optional[float]:
        if trade.nr_of_successful_entries >= self.max_tranches:
            return None
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
        except Exception:
            return None
        if dataframe is None or dataframe.empty:
            return None
        last = dataframe.iloc[-1]
        if not last["bull"]:
            return None
        if "wbull" in dataframe and not last["wbull"]:
            return None
        if current_rate >= last["close"]:
            return None
        size = self._auto_tranche()
        if size <= 0:
            return None
        return min(size, max_stake)
