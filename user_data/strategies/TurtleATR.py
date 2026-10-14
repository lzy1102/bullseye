"""
TurtleATR - 海龟式突破 + ATR吊灯出场 (大波段捕捉), 1d.

目标: 抓大波段 / 最大化吃波段 / 减小回吐损失.
- 进: 收盘突破前 entry_window 日最高 且 收盘>MA60 (趋势确认, 不接飞刀).
- 出: ① 吊灯止损: 收盘跌破 "持仓期最高收盘 - atr_mult*ATR20" (让赢家跑,
      止损随波动放宽, 不用固定百分比);
      ② 大盘门禁: 300指数跌破MA60 -> 全部离场 (熊市不留仓).
- 仓位: 等权 total/max_slots (slots 由配置 max_open_trades 决定).
- 池: 34只大中市值 (流通市值全部>=477亿, 符合"小市值不做").
"""
from pandas import DataFrame
import pandas as pd

from bullseye.strategy import IStrategy


class TurtleATR(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 280
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    entry_window: int = 55
    atr_period: int = 20
    atr_mult: float = 3.0
    max_slots: int = 6
    index_pair: str = "000300.SH"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        high, low, close = dataframe["high"], dataframe["low"], dataframe["close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        dataframe["atr"] = tr.rolling(self.atr_period).mean()
        dataframe["hh_entry"] = high.rolling(self.entry_window).max().shift(1)
        dataframe["ma60"] = close.rolling(60).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        brk = (
            (dataframe["close"] > dataframe["hh_entry"])
            & (dataframe["close"] > dataframe["ma60"])
            & (dataframe["volume"] > 0)
        ).fillna(False)
        dataframe.loc[brk, ["enter_long", "enter_tag"]] = (1, "turtle_break")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe

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
        if entry_tag != "turtle_break":
            return True
        if pair == self.index_pair:
            return False
        return self._index_bull()

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        if not self._index_bull():
            return "mkt_off"
        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        except Exception:
            return None
        if df is None or df.empty or "atr" not in df:
            return None
        last = df.iloc[-1]
        if pd.isna(last["atr"]):
            return None
        opened = pd.to_datetime(trade.open_date)
        held = df[pd.to_datetime(df["date"]) >= opened]
        if held.empty:
            return None
        peak = held["close"].max()
        if last["close"] < peak - self.atr_mult * last["atr"]:
            return "chandelier"
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
