"""
ComboSteady - 双引擎组合: 银行稳腿 (MacdPreGateW) + 轮动攻腿 (TopRot), 1d.

目标: 稳定收益, 不做单票赌注. 同一账户内:
- 银行腿 (四大行): 黑线DIF提前进+日线25/110周线10/20双门禁, 持有整段,
  每仓固定 stake_bank.
- 轮动腿 (AI+龙头27只): 年线之上且年线向上 (下行的票不做) + 10日动量池内
  前2, 强势回踩进, MA20破2天/-10%/30天出. 每仓=总资金/2复利. 大盘门禁.
钱共享: 轮动空闲现金自动给银行腿用, 不切账户不丢整手能力.
测试: 23-26 +109.2%, DD 8.35%, Sharpe 1.66; 分年 +12.9/+31.3/+10.1/+28.2;
45个月32胜, 最差月-2.8%. (含引擎预热修复: 长周期指标在区间首日即有效.)
"""
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy


class ComboSteady(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 280
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    # 银行腿参数 (MacdPreGateW).
    banks: tuple = ("601398.SH", "601288.SH", "601988.SH", "601939.SH")
    gate_fast: int = 25
    gate_slow: int = 110
    w_fast: int = 10
    w_slow: int = 20
    stake_bank: float = 12500.0

    # 轮动腿参数 (TopRot).
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
    top_n: int = 2
    mom_floor: float = 0.05
    wrong_cut: float = -0.10
    max_holding_days: int = 30
    index_pair: str = "000300.SH"

    def _is_bank(self, pair) -> bool:
        return pair in self.banks

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        dataframe["ma10"] = close.rolling(10).mean()
        dataframe["ma20"] = close.rolling(20).mean()
        dataframe["ma60"] = close.rolling(60).mean()
        dataframe["ma250"] = close.rolling(250).mean()
        dataframe["mom10"] = close / close.shift(10) - 1
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(
            span=26, adjust=False).mean()
        sig = macd.ewm(span=9, adjust=False).mean()
        dataframe["macd"] = macd
        dataframe["macd_sig"] = sig
        dataframe["hist"] = macd - sig
        dataframe["ma_fast"] = close.rolling(self.gate_fast).mean()
        dataframe["ma_slow"] = close.rolling(self.gate_slow).mean()
        dataframe["bull"] = (dataframe["ma_fast"] > dataframe["ma_slow"]).fillna(False)
        # 周线门禁 (W-FRI, shift 1周防未来).
        try:
            d = dataframe.copy()
            d["date"] = pd.to_datetime(d["date"])
            wk = d.set_index("date")["close"].resample("W-FRI").last().dropna()
            wf = wk.rolling(self.w_fast).mean()
            ws = wk.rolling(self.w_slow).mean()
            wb = (wf > ws).shift(1)
            w_df = pd.DataFrame({"wbull": wb}).dropna()
            w_df["date"] = w_df.index
            m = pd.merge_asof(
                d.sort_values("date"), w_df.sort_values("date"),
                on="date", direction="backward",
            )
            dataframe["wbull"] = m["wbull"].fillna(False).values
        except Exception:
            dataframe["wbull"] = True
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata.get("pair", "")
        vol = dataframe["volume"] > 0
        if self._is_bank(pair):
            h = dataframe["hist"]
            dif_up = (dataframe["macd"] > dataframe["macd"].shift(1)).fillna(False)
            rising2 = ((h > h.shift(1)) & (h.shift(1) > h.shift(2))).fillna(False)
            early = ((h < 0) & rising2 & dif_up).fillna(False)
            cross = (
                (dataframe["macd"] > dataframe["macd_sig"])
                & (dataframe["macd"].shift(1) <= dataframe["macd_sig"].shift(1))
            ).fillna(False)
            wb = dataframe["wbull"].fillna(False)
            dataframe.loc[
                ((early | cross) & dataframe["bull"] & wb & vol),
                ["enter_long", "enter_tag"],
            ] = (1, "bank_gate")
        else:
            # 长期趋势过滤: 年线之上且年线向上 (下行的票不做).
            long_up = (
                (dataframe["close"] > dataframe["ma250"])
                & (dataframe["ma250"] > dataframe["ma250"].shift(20))
            ).fillna(False)
            stack = (
                (dataframe["close"] > dataframe["ma20"])
                & (dataframe["ma20"] > dataframe["ma60"])
            ).fillna(False)
            pullback = (dataframe["close"] < dataframe["ma10"]).fillna(False)
            dataframe.loc[
                (long_up & stack & pullback & vol),
                ["enter_long", "enter_tag"],
            ] = (1, "rot_pullback")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata.get("pair", "")
        vol = dataframe["volume"] > 0
        if self._is_bank(pair):
            bear = (dataframe["ma_fast"] < dataframe["ma_slow"]).fillna(False)
            wb = dataframe["wbull"].fillna(False)
            dataframe.loc[
                ((bear | (~wb)) & vol),
                ["exit_long", "exit_tag"],
            ] = (1, "bank_gate_off")
        else:
            below = (dataframe["close"] < dataframe["ma20"]).fillna(False)
            break20 = below & below.shift(1).fillna(False)
            dataframe.loc[
                (break20 & vol),
                ["exit_long", "exit_tag"],
            ] = (1, "rot_ma20_break")
        return dataframe

    def _minute_strengths(self) -> dict:
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
        return strengths

    def confirm_trade_entry(
        self, pair: str, order_type: str, amount: float, rate: float,
        time_in_force: str, current_time, entry_tag, side: str, **kwargs,
    ) -> bool:
        if pair == self.index_pair:
            return False
        if entry_tag == "bank_gate":
            return True
        if entry_tag != "rot_pullback":
            return True
        try:
            idx_df, _ = self.dp.get_analyzed_dataframe(
                self.index_pair, self.timeframe)
            if idx_df is not None and not idx_df.empty and "ma60" in idx_df:
                if idx_df["close"].iloc[-1] < idx_df["ma60"].iloc[-1]:
                    return False
        except Exception:
            pass
        strengths = self._minute_strengths()
        if not strengths:
            return True
        if strengths.get(pair, 0) < self.mom_floor:
            return False
        ranked = sorted(strengths, key=strengths.get, reverse=True)
        return pair in ranked[: max(1, int(self.top_n))]

    def custom_stake_amount(
        self, pair: str, current_time, current_rate: float,
        proposed_stake: float, min_stake, max_stake: float,
        leverage: float, entry_tag, side: str, **kwargs,
    ):
        try:
            total = self.wallets.get_total_stake_amount()
        except Exception:
            total = None
        if self._is_bank(pair):
            stake = self.stake_bank
        else:
            if not total or total <= 0:
                return None
            stake = total / max(1, int(self.top_n))
        if max_stake and stake > max_stake:
            stake = max_stake
        return stake

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        if self._is_bank(pair):
            return None
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
