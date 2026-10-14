"""
MacdPreGateFull - full-size first tranche version of MacdPreGate.

Same signals (pre-cross entry + SMA25/110 gate exit), but one shot:
position_adjustment_enable=False, no DCA slicing. Each pair gets
config stake-amount (25k on big4 = fully invested like B&H).
"""
from bullseye.strategy import IStrategy
from pandas import DataFrame


class MacdPreGateFull(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 130
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False
    gate_fast: int = 25
    gate_slow: int = 110

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
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
        dataframe.loc[
            ((early | cross) & dataframe["bull"] & (dataframe["volume"] > 0)),
            ["enter_long", "enter_tag"],
        ] = (1, "macd_pre_gate_full")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        bear = (dataframe["ma_fast"] < dataframe["ma_slow"]).fillna(False)
        dataframe.loc[
            (bear & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "gate_bear")
        return dataframe
