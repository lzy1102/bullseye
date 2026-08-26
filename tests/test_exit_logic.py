"""
Test exit logic module
"""
from datetime import datetime, timedelta
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bullseye.trader.exit_logic import ExitLogic, PairLock


class TestExitLogic:
    """Test suite for ExitLogic module."""

    def test_pair_lock_initialization(self):
        """Test PairLock initialization."""
        lock = PairLock()
        assert lock.locks == {}

    def test_pair_lock_operations(self):
        """Test pair lock and unlock operations."""
        lock = PairLock()
        pair = 'BTC/USDT'
        until = datetime.now() + timedelta(hours=1)
        reason = 'Testing lock'

        lock.lock_pair(pair, until, reason)
        assert pair in lock.locks
        assert lock.locks[pair]['until'] == until
        assert lock.locks[pair]['reason'] == reason

        assert lock.is_pair_locked(pair, datetime.now())

        lock.unlock_pair(pair)
        assert pair not in lock.locks
        assert not lock.is_pair_locked(pair, datetime.now())

    def test_pair_lock_cleanup(self):
        """Test expired lock cleanup."""
        lock = PairLock()
        pair = 'ETH/USDT'
        until = datetime.now() - timedelta(hours=1)
        reason = 'Expired lock'

        lock.lock_pair(pair, until, reason)

        assert not lock.is_pair_locked(pair, datetime.now())

        lock.cleanup_expired_locks(datetime.now())

        assert not lock.is_pair_locked(pair, datetime.now())
        assert lock.get_lock_info(pair) is None

    def test_exit_logic_initialization(self):
        """Test ExitLogic initialization."""
        config = {'exit_timeout': 3600}
        exit_logic = ExitLogic(config)

        assert exit_logic.config == config
        assert exit_logic.pair_lock is not None

    def test_should_exit_with_stoploss(self):
        """Test should_exit with stoploss condition."""
        exit_logic = ExitLogic()

        class MockTrade:
            stop_loss = -0.05
            open_date = datetime.now() - timedelta(hours=1)

        class MockStrategy:
            stoploss = -0.05

        decision = exit_logic.ft_stoploss_reached(
            pair='BTC/USDT',
            trade=MockTrade(),
            current_time=datetime.now(),
            current_rate=100,
            current_profit=-0.06,
            strategy=MockStrategy()
        )

        assert decision.should_exit is True
        assert decision.exit_reason == 'stoploss'
        assert decision.exit_tag == 'stoploss'
        assert decision.exit_type == 'stoploss'

    def test_should_exit_with_roi(self):
        """Test should_exit with ROI condition."""
        exit_logic = ExitLogic()

        class MockTrade:
            min_roi = 0.02
            open_date = datetime.now() - timedelta(hours=1)

        class MockStrategy:
            minimal_roi = 0.02

        decision = exit_logic.min_roi_reached(
            pair='ETH/USDT',
            trade=MockTrade(),
            current_time=datetime.now(),
            current_rate=100,
            current_profit=0.025,
            strategy=MockStrategy()
        )

        assert decision.should_exit is True
        assert decision.exit_reason == 'roi'
        assert decision.exit_tag == 'roi'
        assert decision.exit_type == 'roi'

    def test_should_exit_with_pair_lock(self):
        """Test should_exit with pair lock."""
        exit_logic = ExitLogic()

        class MockTrade:
            open_date = datetime.now() - timedelta(hours=1)

        pair = 'BTC/USDT'
        until = datetime.now() + timedelta(hours=1)
        exit_logic.lock_pair(pair, until, 'Testing lock')

        decision = exit_logic.should_exit(
            pair=pair,
            trade=MockTrade(),
            current_time=datetime.now(),
            current_rate=100,
            current_profit=0.01,
            strategy=None
        )

        assert decision.should_exit is True
        assert decision.exit_reason == 'pair_locked'
        assert decision.exit_tag == 'pair_lock'
        assert decision.exit_type == 'lock'

    def test_should_exit_no_condition(self):
        """Test should_exit when no exit condition is met."""
        exit_logic = ExitLogic()

        class MockTrade:
            stop_loss = -0.05
            min_roi = 0.02
            open_date = datetime.now() - timedelta(hours=1)

        class MockStrategy:
            stoploss = -0.05
            minimal_roi = 0.02

        decision = exit_logic.should_exit(
            pair='BTC/USDT',
            trade=MockTrade(),
            current_time=datetime.now(),
            current_rate=100,
            current_profit=0.01,
            strategy=MockStrategy()
        )

        assert decision.should_exit is False
        assert decision.exit_reason is None
        assert decision.exit_tag is None
        assert decision.exit_type is None
