"""
BasketLowRisk - 低风险篮子策略 (低波单因子 / 多因子合成), 1d.

因子检验(34只池, 20d前瞻)结论: 低波动/低换手/低beta/高EP/高BP 有正溢价.
本策略把它们做成"稳健篮子"长持:
- mode=lowvol: 按20日波动率升序, 持有最低的 n_hold 只.
- mode=multi : 合成排名 = 低波 + 低换手 + 高EP + 高BP, 持有前 n_hold.
- 进场: 先满足趋势条件 (close>MA20>MA60, 不接飞刀), 再通过排名检查.
- 出场: 掉出前 n_hold*2 (滞后缓冲) 或 跌破MA60.
- 仓位: 每仓 = 总资金 / n_hold (等权).
"""
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy


class BasketLowRisk(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 280
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    mode: str = "lowvol"   # lowvol | multi
    n_hold: int = 5

    pool: tuple = (
        "601398.SH", "601288.SH", "601988.SH", "601939.SH", "600036.SH",
        "600016.SH", "000001.SZ", "300750.SZ", "002594.SZ", "688981.SH",
        "600276.SH", "603259.SH", "300760.SZ", "000333.SZ", "000651.SZ",
        "601318.SH", "600030.SH", "600887.SH", "600900.SH", "601088.SH",
        "600941.SH", "601899.SH", "600309.SH", "002475.SZ", "000063.SZ",
        "688041.SH", "688256.SH", "603019.SH", "601138.SH", "603986.SH",
        "688008.SH", "002049.SZ", "601985.SH", "600025.SH",
    )

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        dataframe["ma20"] = close.rolling(20).mean()
        dataframe["ma60"] = close.rolling(60).mean()
        dataframe["vol20"] = close.pct_change().rolling(20).std()
        dataframe["turn20"] = (
            dataframe["turn"].rolling(20).mean()
            if "turn" in dataframe else float("nan")
        )
        dataframe["ep"] = (
            1.0 / dataframe["peTTM"].replace(0, float("nan"))
            if "peTTM" in dataframe else float("nan")
        )
        dataframe["bp"] = (
            1.0 / dataframe["pbMRQ"].replace(0, float("nan"))
            if "pbMRQ" in dataframe else float("nan")
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        trend = (
            (dataframe["close"] > dataframe["ma20"])
            & (dataframe["ma20"] > dataframe["ma60"])
        ).fillna(False)
        dataframe.loc[
            (trend & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "basket")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe

    def _snapshots(self) -> dict:
        """Latest closed-bar factor snapshot per pool pair."""
        snap = {}
        for p in self.pool:
            try:
                df, _ = self.dp.get_analyzed_dataframe(p, self.timeframe)
            except Exception:
                continue
            if df is None or df.empty:
                continue
            last = df.iloc[-1]
            snap[p] = {
                "vol20": last.get("vol20"),
                "turn20": last.get("turn20"),
                "ep": last.get("ep"),
                "bp": last.get("bp"),
            }
        return snap

    def _ranks(self, snap: dict):
        """Higher score = better. Returns ascending list of pair names."""
        df = pd.DataFrame(snap).T
        if self.mode == "lowvol":
            score = (-df["vol20"]).rank(pct=True)
        else:
            parts = []
            for col, asc in (("vol20", True), ("turn20", True),
                             ("ep", False), ("bp", False)):
                ser = df[col]
                if ser.notna().sum() < 8:
                    continue
                r = ser.rank(pct=True)
                parts.append(1 - r if asc else r)
            if not parts:
                return []
            score = pd.concat(parts, axis=1).mean(axis=1)
        score = score.dropna().sort_values(ascending=False)
        return list(score.index)

    def confirm_trade_entry(
        self, pair: str, order_type: str, amount: float, rate: float,
        time_in_force: str, current_time, entry_tag, side: str, **kwargs,
    ) -> bool:
        if entry_tag != "basket":
            return True
        snap = self._snapshots()
        ranked = self._ranks(snap)
        if not ranked:
            return True
        return pair in ranked[: self.n_hold]

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        except Exception:
            return None
        if df is None or df.empty:
            return None
        last = df.iloc[-1]
        if pd.notna(last.get("ma60")) and last["close"] < last["ma60"]:
            return "ma60_break"
        ranked = self._ranks(self._snapshots())
        if ranked and pair in ranked[self.n_hold * 2:]:
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
