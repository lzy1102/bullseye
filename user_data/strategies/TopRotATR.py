"""
TopRotATR - TopRot 出场改为 ATR 吊灯 (减小回吐), 1d.

TopRot 的 MA20 两日跌破出场在震荡里容易被洗, 且一跌破就把利润回吐一大块.
本版: 出场 = 收盘跌破 "持仓期最高收盘 - atr_mult*ATR20" (吊灯止损, 随波动放宽),
其余 (30天上限, -10%认错, 排名/大盘门禁入场) 与 TopRot 相同.
"""
import pandas as pd
from pandas import DataFrame

try:
    from strategies.TopRot import TopRot
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.TopRot import TopRot


class TopRotATR(TopRot):
    INTERFACE_VERSION = 3

    atr_period: int = 20
    atr_mult: float = 3.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        high, low, close = dataframe["high"], dataframe["low"], dataframe["close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        dataframe["atr"] = tr.rolling(self.atr_period).mean()
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        base = super().custom_exit(
            pair=pair, trade=trade, current_time=current_time,
            current_rate=current_rate, current_profit=current_profit, **kwargs,
        )
        if base:
            return base
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
