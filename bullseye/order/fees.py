"""
Fee Model - Transaction cost calculation for different markets.

A-share (China) fee structure:
    - Commission: rate (e.g. 万2.5 = 0.00025), minimum per order (5 CNY)
    - Stamp duty: sell side only (e.g. 0.05% since 2023-08-28)
    - Transfer fee: both sides (e.g. 0.001%)

Zero-config default keeps the flat-rate behavior (commission only, no
minimum, no stamp duty, no transfer fee).

Config (backtest.fees or top-level fees):
    fees:
      commission_rate: 0.00025   # 万2.5
      commission_min: 5.0        # 不足5元按5元
      stamp_duty_rate: 0.0005    # 印花税,卖出单边 0.05%
      transfer_fee_rate: 0.00001 # 过户费,双边 0.001%
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class FeeModel:
    """Transaction fee calculator with per-side semantics."""

    commission_rate: float = 0.001
    commission_min: float = 0.0
    stamp_duty_rate: float = 0.0    # charged on sells only
    transfer_fee_rate: float = 0.0  # charged on both sides

    def fee(self, value: float, is_sell: bool) -> float:
        """
        Total fee for a transaction.

        Args:
            value: Transaction value (price * quantity) in stake currency
            is_sell: True for sell-side transactions (stamp duty applies)

        Returns:
            Total fee amount (>= 0)
        """
        if value <= 0:
            return 0.0

        commission = value * self.commission_rate
        if self.commission_min > 0:
            commission = max(commission, self.commission_min)

        total = commission + value * self.transfer_fee_rate
        if is_sell:
            total += value * self.stamp_duty_rate
        return total

    @classmethod
    def from_config(cls, config: Any) -> Optional["FeeModel"]:
        """
        Build a structured fee model from configuration.

        Looks for a `fees` dict under the backtest section first, then
        top-level. Returns None when not configured (callers fall back to
        their flat fee rate).
        """
        section: Dict = {}
        try:
            section = config.get("backtest.fees", {}) or {}
        except Exception:
            section = {}
        if not section:
            try:
                section = config.get("fees", {}) or {}
            except Exception:
                section = {}
        if not section:
            return None

        return cls(
            commission_rate=float(section.get("commission_rate", 0.001)),
            commission_min=float(section.get("commission_min", 0.0)),
            stamp_duty_rate=float(section.get("stamp_duty_rate", 0.0)),
            transfer_fee_rate=float(section.get("transfer_fee_rate", 0.0)),
        )
