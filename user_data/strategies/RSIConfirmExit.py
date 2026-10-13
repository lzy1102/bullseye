"""RSIConfirmExit - RSIConfirm entries, confirmed euphoria-over exits.

Experiment: does waiting for the cool-down beat selling the breakout?
- Entry: inherited from RSIConfirm (cross below + stabilization).
- Exit (tag 'rsi_cooled'): RSI falls back to <= `overbought`
  after having been above it (first bar of cooling). Holds through
  the overbought zone instead of selling its first touch.
No gate, no DCA, no ROI, no stoploss: isolates the exit effect.
"""
from bullseye.strategy import IntParameter
from pandas import DataFrame

try:
    from RSIConfirm import RSIConfirm, _int
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.RSIConfirm import RSIConfirm, _int


class RSIConfirmExit(RSIConfirm):
    INTERFACE_VERSION = 3

    rsi_period = IntParameter(7, 21, default=16, space="buy", optimize=True)
    oversold = IntParameter(15, 40, default=35, space="buy", optimize=True)
    overbought = IntParameter(60, 85, default=80, space="buy", optimize=True)

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ob = _int(self.overbought)
        cooled = (
            (dataframe["rsi"] <= ob)
            & (dataframe["rsi"].shift(1) > ob)
        ).fillna(False)
        dataframe.loc[
            (cooled & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "rsi_cooled")
        return dataframe
