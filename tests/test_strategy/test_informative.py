"""
Test informative decorator and merge_informative_pair utilities.
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from bullseye.strategy.interface import (
    IStrategy,
    collect_informative_specs,
    informative,
    merge_informative_pair,
    resolve_informative_pair,
)


def make_frames():
    tf = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=4, freq="1h"),
        "close": [10.0, 20.0, 30.0, 40.0],
    })
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=24, freq="5min"),
        "close": list(range(24)),
    })
    return df, tf


class TestMergeInformativePair:
    def test_merge_produces_suffixed_columns(self):
        df, tf = make_frames()
        merged = merge_informative_pair(df, tf, "5m", "1h")
        assert "close_1h" in merged.columns
        assert "date_merge_1h" in merged.columns or "date_1h" in merged.columns
        assert len(merged) == len(df)  # no rows dropped/added

    def test_second_merge_same_tf_keeps_bare_column_names(self):
        """Two @informative methods on the same timeframe must not leave
        _x/_y suffix collisions (breaks strategy lookups like rsi_1h)."""
        df, tf = make_frames()
        tf2 = tf.copy()
        tf2["extra"] = [1.0, 2.0, 3.0, 4.0]
        merged = merge_informative_pair(df, tf, "5m", "1h")
        merged2 = merge_informative_pair(merged, tf2, "5m", "1h")
        assert "close_1h" in merged2.columns
        assert "extra_1h" in merged2.columns
        assert not any(
            c.endswith("_x") or c.endswith("_y") for c in merged2.columns
        )
        assert merged2["close_1h"].dropna().iloc[0] == pytest.approx(10.0)

    def test_no_lookahead_before_first_candle_close(self):
        """A 1h candle stamped 10:00 covers 10:00-11:00; rows before 11:00
        must not see it."""
        df, tf = make_frames()
        merged = merge_informative_pair(df, tf, "5m", "1h")
        before_close = merged[merged["date"] < datetime(2024, 1, 1, 1, 0)]
        assert before_close["close_1h"].isna().all()

    def test_value_available_at_candle_close(self):
        df, tf = make_frames()
        merged = merge_informative_pair(df, tf, "5m", "1h")
        at_close = merged[merged["date"] == datetime(2024, 1, 1, 1, 0)]
        assert at_close["close_1h"].iloc[0] == pytest.approx(10.0)

    def test_ffill_propagates_last_value(self):
        df, tf = make_frames()
        merged = merge_informative_pair(df, tf, "5m", "1h", ffill=True)
        # After 11:00, values keep filling forward until the next 1h candle
        later = merged[merged["date"] == datetime(2024, 1, 1, 1, 55)]
        assert later["close_1h"].iloc[0] == pytest.approx(10.0)

    def test_drop_informative_removes_columns(self):
        df, tf = make_frames()
        merged = merge_informative_pair(df, tf, "5m", "1h", drop_informative=True)
        assert "close_1h" not in merged.columns

    def test_sessioned_market_without_midnight_rows(self):
        """A-share 30m rows never hit midnight date_merge keys; the merge
        must still attach the latest closed daily candle (backward asof),
        not all-NaN like exact matching produces."""
        base = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-02 09:30", "2024-01-02 10:00",
                                    "2024-01-03 09:30"]),
            "close": [1.0, 2.0, 3.0],
        })
        inf = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "close": [10.0, 20.0], "open": 1.0, "high": 1.0,
            "low": 1.0, "volume": 1.0,
        })
        merged = merge_informative_pair(base, inf, "30m", "1d")
        assert merged["close_1d"].tolist() == [10.0, 10.0, 20.0]


class TestInformativeDecorator:
    def test_decorator_tags_function(self):
        @informative("1h")
        def populate_indicators_1h(self, dataframe, metadata):
            return dataframe

        assert getattr(populate_indicators_1h, "_bullseye_informative", None) is not None
        assert populate_indicators_1h._bullseye_informative["timeframe"] == "1h"

    def test_decorator_preserves_call(self):
        called = []

        class S(IStrategy):
            @informative("1h")
            def populate_indicators_1h(self, dataframe, metadata):
                called.append(metadata["pair"])
                return dataframe

        s = S()
        df = pd.DataFrame({"date": [datetime(2024, 1, 1)]})
        s.populate_indicators_1h(df, {"pair": "BTC/USDT"})
        assert called == ["BTC/USDT"]


class TestHelpers:
    def test_collect_specs(self):
        class S(IStrategy):
            @informative("1d")
            def populate_indicators_1d(self, dataframe, metadata):
                return dataframe

            @informative("1h", "ETH/USDT")
            def populate_indicators_eth_1h(self, dataframe, metadata):
                return dataframe

            def populate_indicators(self, dataframe, metadata):
                return dataframe

        specs = {s["method_name"]: s for s in collect_informative_specs(S())}
        assert set(specs) == {"populate_indicators_1d",
                              "populate_indicators_eth_1h"}
        assert specs["populate_indicators_1d"]["timeframe"] == "1d"
        assert specs["populate_indicators_eth_1h"]["asset"] == "ETH/USDT"

    def test_resolve_pair(self):
        assert resolve_informative_pair("ETH/USDT", "") == "ETH/USDT"
        assert resolve_informative_pair("ETH/USDT", "BTC/{stake}") == "BTC/USDT"
        assert resolve_informative_pair("ETH/USDT", "{base}/{stake}") == "ETH/USDT"
        assert resolve_informative_pair("600036.SH", "") == "600036.SH"


def _write_ohlcv(datadir, pair, timeframe, dates, closes, fmt="json"):
    import pandas as pd
    from bullseye.commands.data_commands import _save_ohlcv_df

    df = pd.DataFrame({
        "date": pd.DatetimeIndex(dates),
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [100.0] * len(dates),
    })
    _save_ohlcv_df(df, str(datadir), pair, timeframe, fmt,
                   prepend=False, erase=True,
                   meta={"adjust": None, "datafeed": "test"})


class DailyTrendStrategy(IStrategy):
    """Base 1h + @informative('1d') trend filter (crypto, no validation)."""

    timeframe = "1h"
    startup_candle_count = 5
    minimal_roi = {}
    stoploss = 0

    @informative("1d")
    def populate_indicators_1d(self, dataframe, metadata):
        dataframe["dtrend"] = (dataframe["close"] > 100).astype(int)
        return dataframe

    def populate_indicators(self, dataframe, metadata):
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        # Defensive: informative columns only exist when the 1d data was
        # available (missing informative data warns and skips the merge).
        if "dtrend_1d" not in dataframe.columns:
            return dataframe
        dataframe.loc[
            (dataframe["dtrend_1d"] == 1) & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "daily_trend")
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = 0
        return dataframe


class CrossAssetStrategy(DailyTrendStrategy):
    """Same but the informative leg comes from another pair."""

    @informative("1d", "ETH/USDT")
    def populate_indicators_eth_1d(self, dataframe, metadata):
        dataframe["etrend"] = (dataframe["close"] > 100).astype(int)
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        if "etrend_1d" not in dataframe.columns:
            return dataframe
        dataframe.loc[
            (dataframe["etrend_1d"] == 1) & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "eth_trend")
        return dataframe


class TestBacktestInformative:
    def _engine(self, tmp_path):
        from bullseye.backtesting.engine import BacktestEngine
        from bullseye.configuration.config import Config

        config = Config()
        config.set("datadir", str(tmp_path / "data"))
        config.set("dry_run_wallet", 10000)
        config.set("stake_amount", 100)
        config.set("max_open_trades", 1)
        return BacktestEngine(config)

    def test_daily_filter_trades(self, tmp_path):
        base_dates = pd.date_range("2024-01-01", periods=72, freq="1h")
        _write_ohlcv(tmp_path / "data", "BTC/USDT", "1h",
                     base_dates, [10.0] * 72)
        daily_dates = pd.date_range("2024-01-01", periods=3, freq="1d")
        _write_ohlcv(tmp_path / "data", "BTC/USDT", "1d",
                     daily_dates, [50.0, 150.0, 150.0])
        engine = self._engine(tmp_path)
        result = engine.run(
            strategy_class=DailyTrendStrategy, pairlist=["BTC/USDT"],
            timeframe="1h", initial_balance=10000,
        )
        # Day-2 daily close 150 > 100: base candles from day-3 00:00 carry
        # dtrend_1d == 1 and must produce entries; day-1/2 rows stay flat.
        assert result.metrics.total_trades >= 1
        first = result.trades[0]
        assert first.entry_date >= datetime(2024, 1, 3)

    def test_no_lookahead_day_one(self, tmp_path):
        from bullseye.backtesting.engine import BacktestDataProvider
        from bullseye.order.position_manager import PositionManager
        from bullseye.order.order_executor import OrderExecutor
        from bullseye.wallets.wallets import Wallets
        from bullseye.configuration.config import Config

        base_dates = pd.date_range("2024-01-01", periods=48, freq="1h")
        _write_ohlcv(tmp_path / "data", "BTC/USDT", "1h",
                     base_dates, [10.0] * 48)
        daily_dates = pd.date_range("2024-01-01", periods=2, freq="1d")
        _write_ohlcv(tmp_path / "data", "BTC/USDT", "1d",
                     daily_dates, [150.0, 150.0])
        config = Config()
        config.set("datadir", str(tmp_path / "data"))
        engine = self._engine(tmp_path)
        data = engine._load_data(["BTC/USDT"], "1h")
        strategy = DailyTrendStrategy()
        pairlist = ["BTC/USDT"]
        wallets = Wallets(config, initial_balance=10000)
        pm = PositionManager(config, wallets)
        pm.set_strategy(strategy)
        oe = OrderExecutor(config, pm, wallets)
        oe.set_strategy(strategy)
        bt_dp = BacktestDataProvider(data, pairlist)
        strategy.dp, strategy.wallets = bt_dp, wallets
        strategy.config = config.to_dict()
        trades = engine._run_backtest_loop(
            strategy=strategy, data=data, pairlist=pairlist,
            timeframe="1h", wallets=wallets, position_manager=pm,
            order_executor=oe, bt_dp=bt_dp, max_open_trades=1,
            stake_amount=100, initial_balance=10000,
        )
        # Day-1 base rows must not see any daily value yet.
        assert all(t.entry_date >= datetime(2024, 1, 2) for t in trades)

    def test_cross_asset(self, tmp_path):
        base_dates = pd.date_range("2024-01-01", periods=72, freq="1h")
        _write_ohlcv(tmp_path / "data", "BTC/USDT", "1h",
                     base_dates, [10.0] * 72)
        daily_dates = pd.date_range("2024-01-01", periods=3, freq="1d")
        _write_ohlcv(tmp_path / "data", "ETH/USDT", "1d",
                     daily_dates, [50.0, 150.0, 150.0])
        engine = self._engine(tmp_path)
        result = engine.run(
            strategy_class=CrossAssetStrategy, pairlist=["BTC/USDT"],
            timeframe="1h", initial_balance=10000,
        )
        assert result.metrics.total_trades >= 1

    def test_missing_informative_warns_not_crashes(self, tmp_path, caplog):
        import logging as _logging

        base_dates = pd.date_range("2024-01-01", periods=30, freq="1h")
        _write_ohlcv(tmp_path / "data", "BTC/USDT", "1h",
                     base_dates, [10.0] * 30)
        engine = self._engine(tmp_path)
        with caplog.at_level(_logging.WARNING):
            result = engine.run(
                strategy_class=DailyTrendStrategy, pairlist=["BTC/USDT"],
                timeframe="1h", initial_balance=10000,
            )
        assert result.metrics.total_trades == 0
        assert any("no data" in r.message.lower()
                   or "informative" in r.message.lower()
                   for r in caplog.records)


class TestLiveRunnerInformative:
    def test_runner_merges_by_date_not_position(self):
        from unittest.mock import MagicMock
        from bullseye.bot.strategy_runner import StrategyRunner
        from bullseye.configuration.config import Config

        class S(IStrategy):
            timeframe = "1h"

            @informative("1d")
            def populate_indicators_1d(self, dataframe, metadata):
                dataframe["dval"] = dataframe["close"] * 10
                return dataframe

            def populate_indicators(self, dataframe, metadata):
                return dataframe

            def populate_entry_trend(self, dataframe, metadata):
                return dataframe

            def populate_exit_trend(self, dataframe, metadata):
                return dataframe

        base = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="1h"),
            "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
            "volume": 1.0,
        })
        daily = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=2, freq="1d"),
            "open": 1.0, "high": 1.0, "low": 1.0,
            "close": [5.0, 7.0], "volume": 1.0,
        })
        dp = MagicMock()
        dp.historic_ohlcv.side_effect = lambda pair, timeframe, **k: daily
        runner = StrategyRunner(Config(), S(), dp, MagicMock(),
                                MagicMock(), MagicMock())
        merged = runner._add_informative_pairs(base.copy(), "BTC/USDT")
        day1 = merged[merged["date"] < datetime(2024, 1, 2)]
        day2 = merged[merged["date"] >= datetime(2024, 1, 2)]
        # Day-1 rows see nothing (day-1 candle closes at day-2 00:00);
        # day-2 rows see day-1's value (5 * 10), never day-2's (7 * 10).
        assert day1["dval_1d"].isna().all()
        assert (day2["dval_1d"] == 50.0).all()
