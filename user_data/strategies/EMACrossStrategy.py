"""
Simple EMA Crossover Strategy

A simple strategy that doesn't require TA-Lib.
Uses only pandas for calculations, making it easy to get started.

Strategy Logic:
- Buy when fast EMA crosses above slow EMA (golden cross)
- Sell when fast EMA crosses below slow EMA (death cross)
- Uses volume confirmation
"""
from bullseye.strategy import (
    IStrategy,
    IntParameter,
    DecimalParameter,
)
from pandas import DataFrame


class EMACrossStrategy(IStrategy):
    """
    EMA Crossover Strategy

    A simple moving average crossover strategy that demonstrates
    basic strategy development without external dependencies.

    Entry: Fast EMA crosses above Slow EMA
    Exit: Fast EMA crosses below Slow EMA
    """

    INTERFACE_VERSION = 3

    timeframe = "1h"
    startup_candle_count = 50
    can_short = False

    minimal_roi = {
        "0": 0.10,
        "60": 0.05,
        "120": 0.02,
    }

    stoploss = -0.08

    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    fast_ema_period = IntParameter(5, 20, default=8, space="buy", optimize=True)
    slow_ema_period = IntParameter(20, 60, default=21, space="buy", optimize=True)
    volume_factor = DecimalParameter(0.5, 2.0, default=1.0, decimals=1, space="buy", optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        fast = self.fast_ema_period.value
        slow = self.slow_ema_period.value

        dataframe["ema_fast"] = dataframe["close"].ewm(span=fast, adjust=False).mean()
        dataframe["ema_slow"] = dataframe["close"].ewm(span=slow, adjust=False).mean()

        dataframe["ema_cross"] = (
            (dataframe["ema_fast"] > dataframe["ema_slow"]).astype(int)
            - (dataframe["ema_fast"] < dataframe["ema_slow"]).astype(int)
        )

        dataframe["volume_mean"] = dataframe["volume"].rolling(20).mean()

        dataframe["atr"] = (
            dataframe["high"] - dataframe["low"]
        ).rolling(14).mean()

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        vf = self.volume_factor.value

        dataframe.loc[
            (
                (dataframe["ema_cross"].shift(1) <= 0)
                & (dataframe["ema_cross"] == 1)
                & (dataframe["volume"] > dataframe["volume_mean"] * vf)
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "ema_golden_cross")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["ema_cross"].shift(1) >= 0)
                & (dataframe["ema_cross"] == -1)
                & (dataframe["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "ema_death_cross")

        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        exit_reason: str,
        **kwargs,
    ):
        if current_profit > 0.15:
            return "take_profit_15pct"
        return None
