"""
RSIPlainW - 四大行专用 (601398/601288/601988/601939, 参数10/39/82), 1d.

思路: 超卖39下穿抄底、超买82上穿落袋, 均值回归; 周线10/20门禁过滤熊市
(周熊不开仓、持仓强制走). 十年+130.3%排MACD之后第二, 平均持仓224-314天.
不适合轮动 (太慢) ——轮动用 MacdPreRot.
"""
from pandas import DataFrame

try:
    from strategies.RSIPlain import RSIPlain
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.RSIPlain import RSIPlain


class RSIPlainW(RSIPlain):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 200
    w_fast: int = 10
    w_slow: int = 20

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        import pandas as pd

        dataframe = super().populate_indicators(dataframe, metadata)
        try:
            d = dataframe.copy()
            d["date"] = pd.to_datetime(d["date"])
            wk = d.set_index("date")["close"].resample("W-FRI").last().dropna()
            w_fast = wk.rolling(self.w_fast).mean()
            w_slow = wk.rolling(self.w_slow).mean()
            w_bull = (w_fast > w_slow).shift(1)
            w_df = pd.DataFrame({"wbull": w_bull}).dropna()
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
        try:
            from user_data.strategies.RSIPlain import _int
        except ImportError:
            from strategies.RSIPlain import _int
        os_ = _int(self.oversold)
        cross_down = (
            (dataframe["rsi"] < os_)
            & (dataframe["rsi"].shift(1) >= os_)
        ).fillna(False)
        wb = dataframe["wbull"].fillna(False) if "wbull" in dataframe else True
        dataframe.loc[
            ((cross_down) & wb & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "rsi_w")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        try:
            from user_data.strategies.RSIPlain import _int
        except ImportError:
            from strategies.RSIPlain import _int
        ob = _int(self.overbought)
        cross_up = (
            (dataframe["rsi"] > ob)
            & (dataframe["rsi"].shift(1) <= ob)
        ).fillna(False)
        wb = dataframe["wbull"].fillna(False) if "wbull" in dataframe else True
        exit_sig = (cross_up | (~wb)).fillna(False)
        dataframe.loc[
            (exit_sig & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "rsi_w_exit")
        return dataframe
