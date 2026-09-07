"""
Test Settlement Rules (T+0/T+1 detection and settlement date calculation).
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    import exchange_calendars  # noqa: F401
    HAS_EXCHANGE_CALENDARS = True
except ImportError:
    HAS_EXCHANGE_CALENDARS = False


from bullseye.order.settlement import (
    SettlementDetector,
    SettlementType,
    detect_settlement_rule,
    get_settlement_date,
    init_settlement_detector,
    is_t1_market,
    _calendar_cache,
)


class TestPairDetection:
    @pytest.mark.parametrize("pair,expected_t1", [
        ("000001.SZ", True),
        ("600000.SH", True),
        ("688001.SH", True),
        ("430047.BJ", True),
        ("000001", True),
        ("BTC/USDT", False),
        ("00700.HK", False),
        ("AAPL", False),
        ("AU2506@SHFE", False),
    ])
    def test_pair_format_detection(self, pair, expected_t1):
        assert is_t1_market(pair) is expected_t1

    def test_rule_types(self):
        assert detect_settlement_rule("000001.SZ").settlement_type == SettlementType.T1
        assert detect_settlement_rule("BTC/USDT").settlement_type == SettlementType.T0

    def test_config_override_wins(self):
        detector = SettlementDetector(
            settlement_config={"overrides": {"000001.SZ": "t0"}, "default": "t1"}
        )
        rule = detector.detect_settlement_rule("000001.SZ")
        assert rule.settlement_type == SettlementType.T0

    def test_default_fallback(self):
        detector = SettlementDetector(settlement_config={"default": "t1"})
        # Unknown pair format falls back to configured default
        assert detector.detect_settlement_rule("XYZ123").settlement_type == SettlementType.T1


class TestSettlementDate:
    """Weekend/holiday aware T+1 dates for the A-share calendar."""

    @pytest.mark.parametrize("open_dt,expected", [
        # Thursday 14:50 -> Friday open
        (datetime(2024, 1, 4, 14, 50), datetime(2024, 1, 5, 9, 30)),
        # Friday 14:50 -> next Monday open (weekend skipped)
        (datetime(2024, 1, 5, 14, 50), datetime(2024, 1, 8, 9, 30)),
    ])
    def test_weekend_cases(self, open_dt, expected):
        assert get_settlement_date(open_dt, "000001.SZ") == expected

    @pytest.mark.skipif(not HAS_EXCHANGE_CALENDARS, reason="exchange_calendars not installed")
    def test_chinese_holiday_skipped(self):
        """Buy on the last trading day before National Day (Oct 1-7)."""
        settlement = get_settlement_date(datetime(2024, 9, 30, 14, 50), "000001.SZ")
        assert settlement == datetime(2024, 10, 8, 9, 30)

    @pytest.mark.skipif(not HAS_EXCHANGE_CALENDARS, reason="exchange_calendars not installed")
    def test_spring_festival_skipped(self):
        """2024 Spring Festival holiday: Feb 10-17. Last trading day Feb 8."""
        settlement = get_settlement_date(datetime(2024, 2, 8, 14, 50), "600000.SH")
        assert settlement == datetime(2024, 2, 19, 9, 30)

    @pytest.mark.skipif(HAS_EXCHANGE_CALENDARS, reason="tests fallback path only")
    def test_fallback_without_calendar_package(self):
        settlement = get_settlement_date(datetime(2024, 9, 30, 14, 50), "000001.SZ")
        # Without a calendar the weekend-skip fallback lands on Oct 1 (wrong but safe)
        assert settlement == datetime(2024, 10, 1, 9, 30)

    def test_calendar_is_cached(self):
        """Repeated lookups reuse one calendar instance."""
        _calendar_cache.clear()
        get_settlement_date(datetime(2024, 1, 4, 14, 50), "000001.SZ")
        assert len(_calendar_cache) >= 1
        cached = dict(_calendar_cache)
        get_settlement_date(datetime(2024, 1, 5, 14, 50), "000001.SZ")
        assert _calendar_cache == cached

    def test_t0_returns_open_date(self):
        open_dt = datetime(2024, 1, 4, 14, 50)
        assert get_settlement_date(open_dt, "BTC/USDT") == open_dt

    def test_tz_aware_open_date_preserves_timezone(self):
        """tz-aware input (e.g. UTC from ccxt) must not produce naive output
        that crashes datetime comparisons later."""
        from datetime import timezone
        open_dt = datetime(2024, 1, 4, 14, 50, tzinfo=timezone.utc)
        settlement = get_settlement_date(open_dt, "000001.SZ")
        assert settlement.tzinfo is not None
        # Comparison with aware now must not raise
        assert datetime(2024, 1, 5, 10, 0, tzinfo=timezone.utc) >= settlement


class TestT2AndLivePath:
    """T+2 overrides and the live (wall-clock) availability gate."""

    def test_t2_override_skips_weekend(self):
        detector = SettlementDetector(
            settlement_config={"overrides": {"600000.SH": "t2"}}
        )
        # Thursday -> Fri, Mon (2 trading sessions)
        assert detector.get_settlement_date(
            datetime(2024, 1, 4, 14, 50), "600000.SH"
        ) == datetime(2024, 1, 8, 9, 30)
        # Friday -> Mon, Tue
        assert detector.get_settlement_date(
            datetime(2024, 1, 5, 14, 50), "600000.SH"
        ) == datetime(2024, 1, 9, 9, 30)

    def test_unknown_override_type_warns_and_falls_back_to_t0(self, caplog):
        detector = SettlementDetector(
            settlement_config={"overrides": {"600000.SH": "t3"}}
        )
        rule = detector.detect_settlement_rule("600000.SH")
        assert rule.settlement_type == SettlementType.T0
        assert any("Unknown settlement type" in r.message for r in caplog.records)

    def test_available_for_sale_tz_aware_no_crash(self):
        """Live path: tz-aware open dates (ccxt-style) must not crash the
        availability comparison."""
        from datetime import timezone
        from bullseye.order.position_manager import LocalTrade

        trade = LocalTrade(
            pair="600000.SH", exchange="test", strategy="S", timeframe="1d",
            market_type="stock",
            open_date=datetime(2024, 1, 4, 6, 50, tzinfo=timezone.utc),
            open_rate=10.0, amount=100.0, stake_amount=1000.0, fee_open=1.0,
            is_short=False,
        )
        assert trade.settlement_date.tzinfo is not None
        # Must not raise; position opened today-ish is still restricted
        assert isinstance(trade.available_for_sale, bool)


class TestManualMode:
    """mode: manual disables pair-format auto-detection entirely."""

    def test_manual_ignores_auto_detection(self):
        # Would auto-detect as T+1 in auto mode; manual must NOT
        detector = SettlementDetector(
            settlement_config={"mode": "manual", "default": "t0"}
        )
        assert detector.detect_settlement_rule("000001.SZ").settlement_type == SettlementType.T0
        assert detector.detect_settlement_rule("BTC/USDT").settlement_type == SettlementType.T0

    def test_manual_uses_default_for_everything(self):
        detector = SettlementDetector(
            settlement_config={"mode": "manual", "default": "t1"}
        )
        assert detector.detect_settlement_rule("BTC/USDT").settlement_type == SettlementType.T1
        assert detector.detect_settlement_rule("AAPL").settlement_type == SettlementType.T1

    def test_manual_override_wins_over_default(self):
        detector = SettlementDetector(
            settlement_config={
                "mode": "manual",
                "default": "t1",
                "overrides": {"BTC/USDT": "t0"},
            }
        )
        assert detector.detect_settlement_rule("BTC/USDT").settlement_type == SettlementType.T0
        assert detector.detect_settlement_rule("600000.SH").settlement_type == SettlementType.T1

    def test_auto_mode_still_detects(self):
        detector = SettlementDetector(settlement_config={"mode": "auto"})
        assert detector.detect_settlement_rule("000001.SZ").settlement_type == SettlementType.T1


class TestGlobalSimpleMode:
    """One-switch configuration: settlement: "t0" / "t1" / "t2"."""

    @pytest.fixture(autouse=True)
    def restore_global_detector(self):
        """Global detector is mutated by init; restore after each test."""
        import bullseye.order.settlement as settlement_mod
        old = settlement_mod._detector
        yield
        settlement_mod._detector = old

    def test_global_t1_applies_to_all_pairs(self):
        init_settlement_detector("t1")
        assert detect_settlement_rule("BTC/USDT").settlement_type == SettlementType.T1
        assert detect_settlement_rule("AAPL").settlement_type == SettlementType.T1
        assert detect_settlement_rule("000001.SZ").settlement_type == SettlementType.T1

    def test_global_t0_applies_to_all_pairs(self):
        init_settlement_detector("t0")
        assert detect_settlement_rule("000001.SZ").settlement_type == SettlementType.T0

    def test_global_mode_ignores_pair_format(self):
        init_settlement_detector("t0")
        # A-share pair would auto-detect T1 in dict mode; global says t0
        assert detect_settlement_rule("600000.SH").settlement_type == SettlementType.T0

    def test_global_invalid_value_warns_falls_back_t0(self, caplog):
        init_settlement_detector("t9")
        assert detect_settlement_rule("000001.SZ").settlement_type == SettlementType.T0
        assert any("Unknown settlement type" in r.message for r in caplog.records)

    def test_dict_mode_still_works_after_init(self):
        init_settlement_detector({"overrides": {"600000.SH": "t2"}, "default": "t0"})
        assert detect_settlement_rule("600000.SH").settlement_type == SettlementType.T2
        assert detect_settlement_rule("000001.SZ").settlement_type == SettlementType.T1
