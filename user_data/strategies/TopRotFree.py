"""
TopRotFree - 横截面动量轮动, 无时间上限版 (AI+龙头27只池), 1d.

用户目标: 稳定赚钱, 不靠单票运气, 换到任何股票都能赚.
与TopRot区别: 去掉30天硬上限, 改为"强者恒强 + 掉队换马":
- 进: close>MA20>MA60 且 close<MA10 (强势回踩) 且 mom10 池内前 top_n.
- 出: ① MA20连续2日跌破 (趋势断) ② -10%认错 ③ 动量掉出前 rank_exit
  (强者变弱即换到新强者) ④ 90天保险丝.
- 仓位: top_n 个槽位等权. 大盘门禁: 300跌破MA60不开新仓.
"""
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy


class TopRotFree(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 80
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False
    max_holding_days: int = 90
    wrong_cut: float = -0.10
    top_n: int = 2
    rank_exit: int = 2
    mom_floor: float = 0.05
    mom_window: int = 10

    pool: tuple = (
        "688041.SH", "688256.SH", "603019.SH", "601138.SH",
        "603986.SH", "688008.SH", "002049.SZ", "601985.SH",
        "600025.SH",
        "300750.SZ", "002594.SZ", "688981.SH", "600276.SH",
        "603259.SH", "300760.SZ", "000333.SZ", "000651.SZ",
        "601318.SH", "600030.SH", "600887.SH", "600900.SH",
        "601088.SH", "600941.SH", "601899.SH", "600309.SH",
        "002475.SZ", "000063.SZ",
    )

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        dataframe["ma10"] = close.rolling(10).mean()
        dataframe["ma20"] = close.rolling(20).mean()
        dataframe["ma60"] = close.rolling(60).mean()
        dataframe["mom10"] = close / close.shift(self.mom_window) - 1
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        stack = (
            (dataframe["close"] > dataframe["ma20"])
            & (dataframe["ma20"] > dataframe["ma60"])
        ).fillna(False)
        pullback = (dataframe["close"] < dataframe["ma10"]).fillna(False)
        dataframe.loc[
            (stack & pullback & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "top_free")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        below = (dataframe["close"] < dataframe["ma20"]).fillna(False)
        break20 = below & below.shift(1).fillna(False)
        dataframe.loc[
            (break20 & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "ma20_break")
        return dataframe

    def _rank_of(self, pair: str):
        strengths = {}
        for p in self.pool:
            try:
                df, _ = self.dp.get_analyzed_dataframe(p, self.timeframe)
            except Exception:
                continue
            if df is None or df.empty or "mom10" not in df:
                continue
            val = df["mom10"].iloc[-1]
            if pd.notna(val):
                strengths[p] = float(val)
        if not strengths or pair not in strengths:
            return None, strengths
        ranked = sorted(strengths, key=strengths.get, reverse=True)
        return ranked.index(pair) + 1, strengths

    def confirm_trade_entry(
        self, pair: str, order_type: str, amount: float, rate: float,
        time_in_force: str, current_time, entry_tag, side: str, **kwargs,
    ) -> bool:
        if entry_tag != "top_free":
            return True
        if pair == "000300.SH":
            return False
        try:
            idx_df, _ = self.dp.get_analyzed_dataframe("000300.SH", self.timeframe)
            if idx_df is not None and not idx_df.empty and "ma60" in idx_df:
                if idx_df["close"].iloc[-1] < idx_df["ma60"].iloc[-1]:
                    return False
        except Exception:
            pass
        rank, strengths = self._rank_of(pair)
        if rank is None:
            return True
        if strengths.get(pair, 0) < self.mom_floor:
            return False
        return rank <= self.top_n

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        try:
            days = (
                pd.to_datetime(current_time) - pd.to_datetime(trade.open_date)
            ).days
        except (TypeError, ValueError, AttributeError):
            days = 0
        if days >= self.max_holding_days:
            return "time_90d"
        if current_profit <= self.wrong_cut:
            return "wrong_cut"
        rank, _ = self._rank_of(pair)
        if rank is not None and rank > self.rank_exit:
            return "rank_out"
        return None
