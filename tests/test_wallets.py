"""
Unit tests for the Wallets balance management.
"""
import math

import pytest

from bullseye.configuration.config import Config
from bullseye.wallets.wallets import TradeInfo, WalletBalance, Wallets


@pytest.fixture
def config() -> Config:
    cfg = Config()
    cfg.set("dry_run", True)
    cfg.set("dry_run_wallet", 1000)
    cfg.set("stake_currency", "USDT")
    cfg.set("stake_amount", 100)
    cfg.set("max_open_trades", 3)
    cfg.set("tradable_balance_ratio", 1.0)
    return cfg


@pytest.fixture
def wallets(config) -> Wallets:
    return Wallets(config, initial_balance=1000)


def make_trade(pair="BTC/USDT", stake=100.0, amount=0.1, open_rate=100.0) -> TradeInfo:
    return TradeInfo(
        pair=pair,
        stake_amount=stake,
        amount=amount,
        open_rate=open_rate,
        current_rate=open_rate,
    )


class TestWalletInitialization:
    def test_dry_run_initial_balance(self, wallets):
        assert wallets.get_free() == 1000
        assert wallets.get_total() == 1000
        assert wallets.get_used() == 0

    def test_initial_balance_from_config_fallback(self, config):
        wallets = Wallets(config)  # no explicit initial_balance
        assert wallets.get_total() == config.dry_run_wallet

    def test_unknown_currency_returns_zero(self, wallets):
        assert wallets.get_free("ETH") == 0
        assert wallets.get_total("ETH") == 0
        assert wallets.get_used("ETH") == 0


class TestLockUnlock:
    def test_lock_moves_free_to_used(self, wallets):
        assert wallets.lock_amount("USDT", 300) is True
        assert wallets.get_free() == pytest.approx(700)
        assert wallets.get_used() == pytest.approx(300)
        assert wallets.get_total() == pytest.approx(1000)

    def test_lock_insufficient_balance(self, wallets):
        assert wallets.lock_amount("USDT", 5000) is False
        assert wallets.get_used() == 0

    def test_unlock_releases_locked_amount(self, wallets):
        wallets.lock_amount("USDT", 300)
        assert wallets.unlock_amount("USDT", 300) is True
        assert wallets.get_free() == pytest.approx(1000)
        assert wallets.get_used() == pytest.approx(0)

    def test_unlock_clamped_to_used(self, wallets):
        wallets.lock_amount("USDT", 200)
        # Unlocking more than locked only releases what is actually locked
        assert wallets.unlock_amount("USDT", 9999) is True
        assert wallets.get_used() == 0
        assert wallets.get_free() == pytest.approx(1000)

    def test_unlock_unknown_currency(self, wallets):
        assert wallets.unlock_amount("ETH", 1) is False


class TestDeductAdd:
    def test_deduct_from_free(self, wallets):
        assert wallets.deduct_amount("USDT", 400) is True
        assert wallets.get_free() == pytest.approx(600)
        assert wallets.get_total() == pytest.approx(600)

    def test_deduct_consumes_used_first_then_free(self, wallets):
        wallets.lock_amount("USDT", 300)
        assert wallets.deduct_amount("USDT", 500) is True
        assert wallets.get_used() == pytest.approx(0)
        assert wallets.get_free() == pytest.approx(500)
        assert wallets.get_total() == pytest.approx(500)

    def test_deduct_insufficient_funds(self, wallets):
        assert wallets.deduct_amount("USDT", 1001) is False
        assert wallets.get_total() == pytest.approx(1000)

    @pytest.mark.parametrize("amount", [-1.0, float("nan"), float("inf")])
    def test_deduct_invalid_amount(self, wallets, amount):
        assert wallets.deduct_amount("USDT", amount) is False
        assert wallets.get_total() == pytest.approx(1000)

    def test_add_creates_currency(self, wallets):
        assert wallets.add_amount("ETH", 2.5) is True
        assert wallets.get_free("ETH") == pytest.approx(2.5)
        assert wallets.get_total("ETH") == pytest.approx(2.5)

    def test_add_updates_total_consistently(self, wallets):
        wallets.lock_amount("USDT", 100)
        wallets.add_amount("USDT", 50)
        b = wallets.get_all_balances()["USDT"]
        assert b.total == pytest.approx(b.free + b.used)


class TestTradableRatioAndStake:
    def test_available_stake_applies_ratio(self, config):
        config.set("tradable_balance_ratio", 0.5)
        wallets = Wallets(config, initial_balance=1000)
        assert wallets.get_available_stake_amount() == pytest.approx(500)
        assert wallets.get_total_stake_amount() == pytest.approx(500)

    def test_fixed_stake_capped_by_available(self, wallets):
        assert wallets.get_trade_stake_amount("BTC/USDT") == pytest.approx(100)
        wallets.deduct_amount("USDT", 950)  # free = 50
        assert wallets.get_trade_stake_amount("BTC/USDT") == pytest.approx(50)

    def test_unlimited_stake_splits_by_remaining_slots(self, config):
        config.set("stake_amount", "unlimited")
        wallets = Wallets(config, initial_balance=1200)
        # Stake formula: available / (max_open_trades - open_trades)
        # First trade: 1200 / 3
        assert wallets.get_trade_stake_amount("BTC/USDT") == pytest.approx(400)
        wallets.register_trade(make_trade(stake=400))
        # Second trade: 1200 / (3 - 1)
        assert wallets.get_trade_stake_amount("ETH/USDT") == pytest.approx(600)
        # Last slot takes all remaining available
        wallets.register_trade(make_trade("ETH/USDT", stake=600))
        assert wallets.get_trade_stake_amount("SOL/USDT") == pytest.approx(1200)


class TestTradeTracking:
    def test_register_and_unregister(self, wallets):
        t = make_trade()
        wallets.register_trade(t)
        assert wallets.get_open_trade_count() == 1
        assert wallets.unregister_trade("BTC/USDT") is t
        assert wallets.get_open_trade_count() == 0
        assert wallets.unregister_trade("BTC/USDT") is None

    def test_can_open_trade_respects_max(self, config):
        config.set("max_open_trades", 2)
        wallets = Wallets(config, initial_balance=1000)
        assert wallets.can_open_trade() is True
        wallets.register_trade(make_trade("BTC/USDT"))
        wallets.register_trade(make_trade("ETH/USDT"))
        assert wallets.can_open_trade() is False

    def test_update_trade_rate_computes_profit_ratio(self, wallets):
        t = make_trade(open_rate=100.0)
        wallets.register_trade(t)
        wallets.update_trade_rate("BTC/USDT", 110.0)
        assert t.profit_ratio == pytest.approx(0.10)

    def test_get_open_trades_returns_copy(self, wallets):
        wallets.register_trade(make_trade())
        snapshot = wallets.get_open_trades()
        snapshot.clear()
        assert wallets.get_open_trade_count() == 1


class TestReset:
    def test_reset_restores_initial_state(self, wallets):
        wallets.deduct_amount("USDT", 800)
        wallets.add_amount("ETH", 3)
        wallets.register_trade(make_trade())

        wallets.reset()

        assert wallets.get_total() == pytest.approx(1000)
        assert wallets.get_free("ETH") == 0
        assert wallets.get_open_trade_count() == 0

    def test_reset_with_new_balance(self, wallets):
        wallets.reset(initial_balance=250)
        assert wallets.get_total() == pytest.approx(250)
