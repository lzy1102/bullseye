"""
TrendBollSpot - daily trend + Bollinger breakout timing.

- Direction (gate): SMA20 > SMA60, same as BaseSpot.
- Timing: enter on a cross above the Bollinger UPPER band while the
  gate is up (buy strength, not pullbacks).
- Exit: SMA20 < SMA60 (death cross), or an early exit when the close
  falls below the Bollinger LOWER band (momentum dead, don't wait
  for the slow death cross).
- No DCA, no ROI, no stoploss. Bollinger period/std are plain
  attributes so hyperopt can pick them up later.
"""
from bullseye.strategy import IStrategy
from pandas import DataFrame


class TrendBollSpot(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    # Bollinger parameters.
    boll_period: int = 20
    boll_std: float = 2.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        dataframe["ma20"] = close.rolling(20).mean()
        dataframe["ma60"] = close.rolling(60).mean()
        mid = close.rolling(self.boll_period).mean()
        sd = close.rolling(self.boll_period).std()
        dataframe["bb_mid"] = mid
        dataframe["bb_upper"] = mid + self.boll_std * sd
        dataframe["bb_lower"] = mid - self.boll_std * sd
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        gate = dataframe["ma20"] > dataframe["ma60"]
        above_upper = dataframe["close"] > dataframe["bb_upper"]
        was_inside = (
            dataframe["close"].shift(1) <= dataframe["bb_upper"].shift(1)
        ).fillna(False)
        dataframe.loc[
            (
                gate
                & above_upper
                & was_inside
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "boll_break")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["close"] < dataframe["bb_lower"])
                & (dataframe["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "boll_dead")
        dataframe.loc[
            (
                (dataframe["ma20"] < dataframe["ma60"])
                & (dataframe["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "trend_bear")
        return dataframe
