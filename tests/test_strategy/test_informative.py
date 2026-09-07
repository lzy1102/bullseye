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

from bullseye.strategy.interface import IStrategy, informative, merge_informative_pair


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
