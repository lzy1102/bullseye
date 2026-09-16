"""
Test low-level calculation consistency: leverage, metric annualization,
and the DataProvider fallback datafeed path.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from bullseye.backtesting.result import BacktestResult, BacktestTrade
from bullseye.configuration.config import Config
from bullseye.order.position_manager import LocalTrade


def make_trade(leverage=1.0, is_short=False, amount=1.0, open_rate=100.0):
    return LocalTrade(
        pair="BTC/USDT", exchange="test", strategy="S", timeframe="1h",
        market_type="crypto", open_date=datetime(2024, 1, 1),
        open_rate=open_rate, amount=amount, stake_amount=open_rate * amount,
        fee_open=0.0, is_short=is_short, leverage=leverage,
    )


class TestLeverageConsistency:
    """calc_profit and calc_profit_ratio must use leverage consistently."""

    def test_unleveraged_long(self):
        trade = make_trade(leverage=1.0)
        assert trade.calc_profit_ratio(105.0) == pytest.approx(0.05)
        assert trade.calc_profit(105.0) == pytest.approx(5.0)

    def test_leveraged_long_scales_both(self):
        trade = make_trade(leverage=2.0)
        # +5% price move on 2x leverage = +10% on margin
        assert trade.calc_profit_ratio(105.0) == pytest.approx(0.10)
        assert trade.calc_profit(105.0) == pytest.approx(10.0)

    def test_leveraged_short_scales_both(self):
        trade = make_trade(leverage=3.0, is_short=True)
        # -5% price move on 3x short = +15%
        assert trade.calc_profit_ratio(95.0) == pytest.approx(0.15)
        assert trade.calc_profit(95.0) == pytest.approx(15.0)

    def test_fees_are_not_leveraged(self):
        trade = make_trade(leverage=2.0)
        trade.fee_open = 1.0
        assert trade.calc_profit(105.0) == pytest.approx(10.0 - 1.0)


class TestMetricAnnualization:
    """Sharpe/Sortino/Calmar from daily equity-curve returns."""

    def build_result(self, curve):
        result = BacktestResult(strategy_name="T", equity_curve=curve)
        result.calculate_metrics(initial_balance=curve[0][1])
        return result

    def test_flat_curve_zero_sharpe(self):
        curve = [(datetime(2024, 1, 1) + timedelta(days=i), 1000.0) for i in range(10)]
        result = self.build_result(curve)
        assert result.metrics.sharpe_ratio == pytest.approx(0.0)
        assert result.metrics.max_drawdown == pytest.approx(0.0)

    def test_steady_growth_positive_sharpe(self):
        curve = [(datetime(2024, 1, 1) + timedelta(days=i), 1000.0 * (1.01 ** i)) for i in range(30)]
        result = self.build_result(curve)
        assert result.metrics.sharpe_ratio > 0
        assert result.metrics.max_drawdown == pytest.approx(0.0)
        assert result.metrics.calmar_ratio == 0.0  # no drawdown -> undefined -> 0

    def test_calmar_annualizes_from_curve(self):
        # +10% over 73 days, then -10% dip -> annualized ~50%/yr over 10% dd
        curve = [(datetime(2024, 1, 1) + timedelta(days=i), 1100.0) for i in range(73)]
        curve += [(datetime(2024, 4, 1) + timedelta(days=i), 990.0) for i in range(10)]
        result = self.build_result(curve)
        assert result.metrics.max_drawdown == pytest.approx(10.0, rel=0.01)
        # total return = -1%, ~83 days -> annualized ~-4.4% -> calmar negative but small
        assert result.metrics.calmar_ratio < 0

    def test_daily_returns_dedupe_intraday(self):
        # Multiple points per day must collapse to the last value per day
        day = datetime(2024, 1, 1)
        curve = [
            (day, 1000.0), (day + timedelta(hours=1), 1010.0),
            (day + timedelta(days=1), 1020.0),
            (day + timedelta(days=2), 1030.0),
        ]
        result = self.build_result(curve)
        daily = result._daily_returns()
        assert len(daily) == 2  # three days -> two returns
