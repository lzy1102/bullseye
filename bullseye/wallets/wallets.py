"""
Wallets - Account and balance management for Bullseye.

Manages virtual wallet balances for dry-run mode and provides
a unified interface for balance queries and updates.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from bullseye.configuration.config import Config

logger = logging.getLogger(__name__)


@dataclass
class WalletBalance:
    """Represents a balance for a single currency."""

    currency: str
    total: float = 0.0
    free: float = 0.0
    used: float = 0.0

    @property
    def available(self) -> float:
        """Alias for free balance."""
        return self.free

    def __repr__(self) -> str:
        return f"WalletBalance({self.currency}: total={self.total}, free={self.free})"


@dataclass
class TradeInfo:
    """Information about an open trade for stake calculation."""

    pair: str
    stake_amount: float
    amount: float
    open_rate: float
    current_rate: float
    profit_ratio: float = 0.0


class Wallets:
    """
    Wallet and balance management for Bullseye.

    This class manages account balances, calculates available stake amounts,
    and tracks open trade positions for position sizing.

    In dry-run mode, this maintains virtual balances.
    In live mode, this syncs with exchange balances.
    """

    def __init__(
        self,
        config: Config,
        initial_balance: Optional[float] = None,
    ):
        """
        Initialize the Wallets manager.

        Args:
            config: Configuration object
            initial_balance: Initial balance for dry-run mode (overrides config)
        """
        self._config = config

        # Stake currency (e.g., USDT)
        self._stake_currency = config.stake_currency

        # Initialize balances
        self._balances: Dict[str, WalletBalance] = {}

        # Set initial balance for dry-run
        if config.dry_run:
            initial = initial_balance or config.dry_run_wallet
            self._balances[self._stake_currency] = WalletBalance(
                currency=self._stake_currency,
                total=initial,
                free=initial,
                used=0.0,
            )
            logger.info(f"Dry-run wallet initialized with {initial} {self._stake_currency}")

        # Open trades tracking
        self._open_trades: List[TradeInfo] = []

        # Settings
        self._max_open_trades = config.max_open_trades
        self._stake_amount = config.stake_amount
        self._tradable_balance_ratio = config.tradable_balance_ratio
        self._stake_amount_unlimited = config.stake_amount_unlimited

    def get_total_stake_amount(self) -> float:
        """
        Get the total stake amount available.

        This includes both free and used balance, multiplied by
        the tradable balance ratio.

        Returns:
            Total stake amount in stake currency
        """
        balance = self._balances.get(self._stake_currency)
        if not balance:
            return 0.0

        return balance.total * self._tradable_balance_ratio

    def get_available_stake_amount(self) -> float:
        """
        Get the available (free) stake amount.

        This is the amount that can be used for new trades.

        Returns:
            Available stake amount in stake currency
        """
        balance = self._balances.get(self._stake_currency)
        if not balance:
            return 0.0

        return balance.free * self._tradable_balance_ratio

    def get_free(self, currency: Optional[str] = None) -> float:
        """
        Get the free balance for a currency.

        Args:
            currency: Currency to get balance for (default: stake currency)

        Returns:
            Free balance amount
        """
        currency = currency or self._stake_currency
        balance = self._balances.get(currency)
        return balance.free if balance else 0.0

    def get_total(self, currency: Optional[str] = None) -> float:
        """
        Get the total balance for a currency.

        Args:
            currency: Currency to get balance for (default: stake currency)

        Returns:
            Total balance amount
        """
        currency = currency or self._stake_currency
        balance = self._balances.get(currency)
        return balance.total if balance else 0.0

    def get_used(self, currency: Optional[str] = None) -> float:
        """
        Get the used (locked) balance for a currency.

        Args:
            currency: Currency to get balance for (default: stake currency)

        Returns:
            Used balance amount
        """
        currency = currency or self._stake_currency
        balance = self._balances.get(currency)
        return balance.used if balance else 0.0

    def get_all_balances(self) -> Dict[str, WalletBalance]:
        """
        Get all wallet balances.

        Returns:
            Dictionary of currency -> WalletBalance
        """
        return self._balances.copy()

    def update_balance(
        self,
        currency: str,
        total: Optional[float] = None,
        free: Optional[float] = None,
        used: Optional[float] = None,
    ) -> None:
        """
        Update wallet balance.

        Args:
            currency: Currency to update
            total: New total balance (optional)
            free: New free balance (optional)
            used: New used balance (optional)
        """
        if currency not in self._balances:
            self._balances[currency] = WalletBalance(currency=currency)

        balance = self._balances[currency]

        if total is not None:
            balance.total = total
        if free is not None:
            balance.free = free
        if used is not None:
            balance.used = used

        logger.debug(f"Updated {currency} balance: total={balance.total}, free={balance.free}")

    def lock_amount(self, currency: str, amount: float) -> bool:
        """
        Lock (reserve) an amount for a pending trade.

        Args:
            currency: Currency to lock
            amount: Amount to lock

        Returns:
            True if successful, False if insufficient balance
        """
        balance = self._balances.get(currency)
        if not balance or balance.free < amount:
            return False

        balance.free -= amount
        balance.used += amount
        return True

    def unlock_amount(self, currency: str, amount: float) -> bool:
        """
        Unlock (release) a previously locked amount.

        Args:
            currency: Currency to unlock
            amount: Amount to unlock

        Returns:
            True if successful
        """
        balance = self._balances.get(currency)
        if not balance:
            return False

        # Ensure we don't unlock more than used
        actual_unlock = min(amount, balance.used)
        balance.used -= actual_unlock
        balance.free += actual_unlock
        return True

    def deduct_amount(self, currency: str, amount: float) -> bool:
        """
        Deduct an amount from the wallet (for executed trades).

        Args:
            currency: Currency to deduct
            amount: Amount to deduct

        Returns:
            True if successful, False if insufficient funds or invalid input
        """
        import math

        # Validate input
        if not currency or amount < 0 or not math.isfinite(amount):
            logger.warning(f"Invalid deduct_amount parameters: currency={currency}, amount={amount}")
            return False

        balance = self._balances.get(currency)
        if not balance:
            logger.warning(f"Currency {currency} not found in wallet")
            return False

        # Check sufficient funds
        available = balance.used + balance.free
        if available < amount:
            logger.warning(
                f"Insufficient funds for {currency}: requested={amount}, available={available}"
            )
            return False

        # Deduct from used (locked) first, then free
        if balance.used >= amount:
            balance.used -= amount
        else:
            remaining = amount - balance.used
            balance.used = 0
            balance.free = max(0, balance.free - remaining)

        balance.total = balance.free + balance.used
        return True

    def add_amount(self, currency: str, amount: float) -> bool:
        """
        Add an amount to the wallet (from closed trades).

        Args:
            currency: Currency to add
            amount: Amount to add

        Returns:
            True if successful, False if invalid input
        """
        import math

        # Validate input
        if not currency or amount < 0 or not math.isfinite(amount):
            logger.warning(f"Invalid add_amount parameters: currency={currency}, amount={amount}")
            return False

        if currency not in self._balances:
            self._balances[currency] = WalletBalance(currency=currency)

        balance = self._balances[currency]
        balance.free += amount
        balance.total = balance.free + balance.used
        return True

    # ==================== Trade Stake Calculation ====================

    def get_trade_stake_amount(self, pair: str) -> float:
        """
        Calculate the stake amount for a new trade.

        This considers:
        - Fixed stake amount from config
        - Available balance
        - Maximum open trades
        - Tradable balance ratio

        Args:
            pair: Trading pair (for future per-pair stake calculations)

        Returns:
            Stake amount for the trade
        """
        if self._stake_amount_unlimited:
            # Unlimited stake - calculate based on available balance
            available = self.get_available_stake_amount()

            # Count open trades and reserve space for remaining trades
            open_trades_count = len(self._open_trades)
            remaining_slots = max(0, self._max_open_trades - open_trades_count - 1)

            if remaining_slots > 0:
                # Reserve some balance for remaining slots
                return available / (remaining_slots + 1)
            else:
                return available
        else:
            # Fixed stake amount
            available = self.get_available_stake_amount()
            return min(self._stake_amount, available)

    def register_trade(self, trade: TradeInfo) -> None:
        """
        Register an open trade for stake tracking.

        Args:
            trade: Trade information
        """
        self._open_trades.append(trade)
        logger.debug(f"Registered trade for {trade.pair}: stake={trade.stake_amount}")

    def unregister_trade(self, pair: str) -> Optional[TradeInfo]:
        """
        Unregister a closed trade.

        Args:
            pair: Trading pair to unregister

        Returns:
            The removed TradeInfo or None if not found
        """
        for i, trade in enumerate(self._open_trades):
            if trade.pair == pair:
                removed = self._open_trades.pop(i)
                logger.debug(f"Unregistered trade for {pair}")
                return removed
        return None

    def get_open_trades(self) -> List[TradeInfo]:
        """
        Get all registered open trades.

        Returns:
            List of TradeInfo objects
        """
        return self._open_trades.copy()

    def get_open_trade_count(self) -> int:
        """
        Get the count of open trades.

        Returns:
            Number of open trades
        """
        return len(self._open_trades)

    def can_open_trade(self) -> bool:
        """
        Check if a new trade can be opened.

        Returns:
            True if max_open_trades not reached
        """
        return len(self._open_trades) < self._max_open_trades

    def update_trade_rate(self, pair: str, current_rate: float) -> None:
        """
        Update the current rate for a tracked trade.

        Args:
            pair: Trading pair
            current_rate: Current market rate
        """
        for trade in self._open_trades:
            if trade.pair == pair:
                trade.current_rate = current_rate
                if trade.open_rate > 0:
                    trade.profit_ratio = (current_rate - trade.open_rate) / trade.open_rate
                break

    # ==================== Utility Methods ====================

    def reset(self, initial_balance: Optional[float] = None) -> None:
        """
        Reset wallet to initial state.

        Args:
            initial_balance: New initial balance (optional)
        """
        self._balances.clear()
        self._open_trades.clear()

        initial = initial_balance or self._config.dry_run_wallet
        self._balances[self._stake_currency] = WalletBalance(
            currency=self._stake_currency,
            total=initial,
            free=initial,
            used=0.0,
        )
        logger.info(f"Wallet reset to {initial} {self._stake_currency}")

    def __repr__(self) -> str:
        balance = self._balances.get(self._stake_currency)
        total = balance.total if balance else 0
        return f"Wallets(stake={self._stake_currency}, total={total}, trades={len(self._open_trades)})"
