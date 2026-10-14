"""
TopRot - 横截面动量轮动 (AI+龙头27只池), 1d.

目标导向: 稳定赚钱. 轮动 = 每天在池子里排名, 只持有动量最强的 top_n 只,
30天到期换马, 做错-10%清掉. 用 confirm_trade_entry 做横截面过滤:
- 长期趋势过滤: 年线之上且年线向上 (MA250上升, 下行的票不做).
- 进: close>MA20>MA60 且 close<MA10 (强势股回踩) 且 mom10>5%,
  且 mom10 在池内排前 top_n (横截面排名).
- 出: ① MA20连续2日跌破 ② -10%认错 ③ 30天轮动上限.
- 仓位: top_n 个槽位等权, 复利 (每仓=总资金/top_n). 大盘门禁300>MA60.
测试记录: 23-26 +172.0% (DD 15.5%); 分年 +2.1/+28.4/+30.3/+59.3.
年线过滤+8点 (升且之上=单升条件同效); 30天上限最优 (45/60/无上限更差);
top2最优 (top1 DD28/top3/top4差); mom10最优 (5/15/20差); 大盘门禁+29点;
剔掉最强3只变负 — 动量策略靠主题强趋势段, 靠排名自动换马分散个股.
"""
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy


class TopRot(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 280
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False
    max_holding_days: int = 30
    wrong_cut: float = -0.10
    top_n: int = 2
    mom_floor: float = 0.05

    pool: tuple = (
        # AI/算力/存储
        "688041.SH", "688256.SH", "603019.SH", "601138.SH",
        "603986.SH", "688008.SH", "002049.SZ", "601985.SH",
        "600025.SH",
        # 龙头18
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
        dataframe["ma250"] = close.rolling(250).mean()
        dataframe["hh20"] = (
            dataframe["high"].rolling(20).max().shift(1)
        )
        dataframe["mom20"] = close / close.shift(10) - 1
        return dataframe

    def custom_stake_amount(
        self, pair: str, current_time, current_rate: float,
        proposed_stake: float, min_stake, max_stake: float,
        leverage: float, entry_tag, side: str, **kwargs,
    ):
        # 复利: 每仓=当前总资金的1/top_n (随盈利增长, 随亏损收缩).
        try:
            total = self.wallets.get_total_stake_amount()
        except Exception:
            return None
        if total is None or total <= 0:
            return None
        stake = total / max(1, int(self.top_n))
        return min(stake, max_stake) if max_stake else stake

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 长期趋势过滤: 年线之上且年线向上 (下行的票不做).
        long_up = (
            (dataframe["close"] > dataframe["ma250"])
            & (dataframe["ma250"] > dataframe["ma250"].shift(20))
        ).fillna(False)
        stack = (
            (dataframe["close"] > dataframe["ma20"])
            & (dataframe["ma20"] > dataframe["ma60"])
        ).fillna(False)
        strong = (
            (dataframe["close"] < dataframe["ma10"])
        ).fillna(False)
        dataframe.loc[
            (long_up & stack & strong & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "top_rot")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        below = (dataframe["close"] < dataframe["ma20"]).fillna(False)
        break20 = below & below.shift(1).fillna(False)
        dataframe.loc[
            (break20 & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "ma20_break")
        return dataframe

    def _pool_strengths(self) -> dict:
        strengths = {}
        for p in self.pool:
            try:
                df, _ = self.dp.get_analyzed_dataframe(p, self.timeframe)
            except Exception:
                continue
            if df is None or df.empty or "mom20" not in df:
                continue
            val = df["mom20"].iloc[-1]
            if pd.notna(val):
                strengths[p] = float(val)
        return strengths

    def _is_top_ranked(self, pair: str) -> bool:
        strengths = self._pool_strengths()
        if not strengths:
            return True
        ranked = sorted(strengths, key=strengths.get, reverse=True)
        return pair in ranked[: max(1, int(self.top_n))]

    def confirm_trade_entry(
        self, pair: str, order_type: str, amount: float, rate: float,
        time_in_force: str, current_time, entry_tag, side: str, **kwargs,
    ) -> bool:
        if entry_tag != "top_rot":
            return True
        if pair == "000300.SH":
            return False
        # 大盘门禁: 300指数跌破MA60时不开新仓 (2023式熊市空仓).
        try:
            idx_df, _ = self.dp.get_analyzed_dataframe("000300.SH", self.timeframe)
            if idx_df is not None and not idx_df.empty and "ma60" in idx_df:
                if idx_df["close"].iloc[-1] < idx_df["ma60"].iloc[-1]:
                    return False
        except Exception:
            pass
        strengths = self._pool_strengths()
        if not strengths:
            return True
        if strengths.get(pair, 0) < self.mom_floor:
            return False
        ranked = sorted(strengths, key=strengths.get, reverse=True)
        return pair in ranked[: max(1, int(self.top_n))]

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
            return "time_30d"
        if current_profit <= self.wrong_cut:
            return "wrong_cut"
        return None
