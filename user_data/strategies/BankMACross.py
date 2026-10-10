"""
Bank MACross Strategy - A-share bank stock trend following.

Simple EMA golden-cross / death-cross system tuned for low-volatility
bank stocks on daily candles:

- Entry: fast EMA crosses above slow EMA (golden cross)
- Exit: fast EMA crosses below slow EMA (death cross)
- No shorting (A-shares are T+1 long-only here)

Tune with hyperopt later; 12/26 are sane daily defaults for banks.
"""
from bullseye.strategy import IStrategy, IntParameter
from pandas import DataFrame


def _int(value) -> int:
    """Unwrap hyperopt parameters on old and new engines.

    New engines return a bound view (has .value); old engines return the
    raw int. getattr covers both so the strategy runs everywhere.
    """
    return int(getattr(value, "value", value))


class BankMACross(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    minimal_roi = {
        "0": 0.08,
        "60": 0.04,
        "180": 0.02,
    }

    stoploss = -0.08

    fast_period = IntParameter(5, 20, default=12, space="buy", optimize=True)
    slow_period = IntParameter(20, 60, default=26, space="buy", optimize=True)

    # Bollinger early-exit parameters (exit leg only).
    boll_period: int = 20
    boll_std: float = 2.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        fast = _int(self.fast_period)
        slow = _int(self.slow_period)
        if slow <= fast:
            slow = fast + 1
        dataframe["ema_fast"] = (
            dataframe["close"].ewm(span=fast, adjust=False).mean()
        )
        dataframe["ema_slow"] = (
            dataframe["close"].ewm(span=slow, adjust=False).mean()
        )
        mid = dataframe["close"].rolling(self.boll_period).mean()
        sd = dataframe["close"].rolling(self.boll_period).std()
        dataframe["bb_lower"] = mid - self.boll_std * sd
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["ema_fast"] > dataframe["ema_slow"])
                & (dataframe["ema_fast"].shift(1) <= dataframe["ema_slow"].shift(1))
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "golden_cross")
        return dataframe

    def _boll_on(self) -> bool:
        # Kill-switch for the experiment: set use_boll_exit: false
        # in the config to run the pre-Bollinger baseline.
        cfg = getattr(self, "config", None)
        if isinstance(cfg, dict):
            return bool(cfg.get("use_boll_exit", True))
        return True

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if self._boll_on():
            dataframe.loc[
                (
                    (dataframe["close"] < dataframe["bb_lower"])
                    & (dataframe["volume"] > 0)
                ),
                ["exit_long", "exit_tag"],
            ] = (1, "boll_dead")
        dataframe.loc[
            (
                (dataframe["ema_fast"] < dataframe["ema_slow"])
                & (dataframe["ema_fast"].shift(1) >= dataframe["ema_slow"].shift(1))
                & (dataframe["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "death_cross")
        return dataframe
