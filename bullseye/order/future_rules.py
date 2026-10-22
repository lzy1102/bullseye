"""
Contract specifications, margin and fee math for Chinese futures.

The backtest engine prices stocks in shares with a flat notional debit. Futures
need three extra facts per contract:

* contract multiplier (合约乘数) - 1 lot of RB is 10 tonnes, of IF is 300 index points
* margin rate (保证金率) - only margin is locked, the notional is the exposure
* per-lot fees (手续费) - a fixed part plus a rate on the traded notional, and
  close-today (平今) usually costs several times close (平仓)

Specs are loaded from ``user_data/data/futures/contracts.json`` (see
``scripts/research/futures_daily_data.py``) or from a live CTP contract query.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_CONTRACTS_FILE = "user_data/data/futures/contracts.json"

#: Side of an order as used by the fee helpers.
SIDE_OPEN = "open"
SIDE_CLOSE = "close"


@dataclass
class FutureContract:
    """Static specification of one futures contract."""

    pair: str = ""
    symbol: str = ""
    product: str = ""
    exchange: str = ""
    multiplier: float = 1.0
    tick_size: float = 0.01
    lot: int = 1
    margin_rate: float = 0.1
    short_margin_rate: Optional[float] = None
    open_fee_fixed_per_lot: float = 0.0
    close_fee_fixed_per_lot: float = 0.0
    close_today_fee_fixed_per_lot: float = 0.0
    open_fee_rate: float = 0.0
    close_fee_rate: float = 0.0
    close_today_fee_rate: float = 0.0
    limit_ratio: float = 0.08
    extra: Dict[str, object] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # notional / margin
    # ------------------------------------------------------------------
    def notional(self, price: float, contracts: float = 1.0) -> float:
        """Traded value of ``contracts`` lots at ``price``."""
        return float(price) * float(contracts) * float(self.multiplier or 1.0)

    def margin(self, price: float, contracts: float = 1.0,
               is_short: bool = False) -> float:
        """Margin locked for ``contracts`` lots at ``price``."""
        rate = self.margin_rate
        if is_short and self.short_margin_rate:
            rate = self.short_margin_rate
        return self.notional(price, contracts) * float(rate or 0.0)

    def contracts_for_margin(self, margin_budget: float, price: float) -> float:
        """Whole lots whose margin fits ``margin_budget``.

        The stake for a futures position is a *margin* budget (capital
        committed), not a notional: the notional follows from the margin rate.
        """
        if price <= 0 or margin_budget <= 0:
            return 0.0
        rate = float(self.margin_rate or 0.0)
        if rate <= 0:
            return 0.0
        per_contract = float(price) * float(self.multiplier or 1.0) * rate
        if per_contract <= 0:
            return 0.0
        return math.floor(margin_budget / per_contract)

    @property
    def leverage_from_margin(self) -> float:
        """The broker's leverage cap: 1 / margin rate.

        This is the most exposure the contract allows with the margin the
        exchange demands. Strategies may ask for it explicitly (Freqtrade
        passes it as ``max_leverage``); the default stays 1x notional.
        """
        rate = float(self.margin_rate or 0.0)
        if rate <= 0:
            return 1.0
        return 1.0 / rate

    # ------------------------------------------------------------------
    # fees
    # ------------------------------------------------------------------
    def fee(self, price: float, contracts: float, side: str = SIDE_OPEN,
            close_today: bool = False) -> float:
        """Commission for ``contracts`` lots at ``price``.

        Chinese futures charge a fixed amount per lot plus a rate on the
        traded notional. Closing a position opened on the same trading day
        (平今) is priced separately and is typically much more expensive.
        """
        contracts = float(contracts or 0)
        if contracts <= 0:
            return 0.0
        if side == SIDE_OPEN:
            fixed = self.open_fee_fixed_per_lot
            rate = self.open_fee_rate
        elif close_today:
            fixed = self.close_today_fee_fixed_per_lot
            rate = self.close_today_fee_rate
        else:
            fixed = self.close_fee_fixed_per_lot
            rate = self.close_fee_rate
        per_lot = float(fixed or 0.0) + float(rate or 0.0) * self.notional(price, 1.0)
        return contracts * per_lot

    # ------------------------------------------------------------------
    # prices
    # ------------------------------------------------------------------
    def round_to_tick(self, price: float) -> float:
        """Round a price onto the contract's tick grid."""
        tick = float(self.tick_size or 0.0)
        if tick <= 0:
            return float(price)
        return round(round(float(price) / tick) * tick, 6)

    def limit_prices(self, pre_settle: float) -> tuple:
        """(limit_up, limit_down) for a given previous settlement price."""
        base = float(pre_settle or 0.0)
        if base <= 0:
            return (0.0, 0.0)
        ratio = float(self.limit_ratio or 0.0)
        return (base * (1 + ratio), base * (1 - ratio))

    @classmethod
    def from_dict(cls, payload: Dict) -> "FutureContract":
        known = {
            "pair", "symbol", "product", "exchange", "multiplier", "tick_size",
            "lot", "margin_rate", "short_margin_rate", "open_fee_fixed_per_lot",
            "close_fee_fixed_per_lot", "close_today_fee_fixed_per_lot",
            "open_fee_rate", "close_fee_rate", "close_today_fee_rate",
            "limit_ratio",
        }
        kwargs = {k: v for k, v in payload.items() if k in known}
        extra = {k: v for k, v in payload.items() if k not in known}
        contract = cls(**kwargs)
        contract.extra = extra
        return contract


class ContractRegistry:
    """Lookup of futures contract specs by pair (e.g. ``RB0@SHFE``)."""

    def __init__(self, contracts: Optional[Dict[str, FutureContract]] = None):
        self._contracts: Dict[str, FutureContract] = dict(contracts or {})

    def __len__(self) -> int:
        return len(self._contracts)

    def __contains__(self, pair: str) -> bool:
        return pair in self._contracts

    def get(self, pair: str) -> Optional[FutureContract]:
        """Contract spec for ``pair`` (None when unknown).

        Exact match first ("RB0@SHFE"), then a product-level fallback so a
        real contract code ("rb2601", "rb2601@SHFE") resolves to the spec of
        its product ("RB0@SHFE").
        """
        spec = self._contracts.get(pair)
        if spec is not None:
            return spec
        return self._by_product(pair)

    def _by_product(self, pair: str) -> Optional[FutureContract]:
        """Resolve a contract code to the spec of its product."""
        if not pair:
            return None
        symbol = pair.split("@", 1)[0].strip()
        product = "".join(ch for ch in symbol if ch.isalpha()).upper()
        if not product:
            return None
        exchange = pair.split("@", 1)[1].strip().upper() if "@" in pair else None
        candidates = [
            c for c in self._contracts.values()
            if c.product.upper() == product
            and (not exchange or c.exchange.upper() == exchange)
        ]
        if not candidates:
            return None
        # Prefer the main-continuous entry of that product.
        for candidate in candidates:
            if candidate.symbol.upper().endswith("0"):
                return candidate
        return candidates[0]

    def pairs(self):
        return list(self._contracts.keys())

    @classmethod
    def load(cls, path) -> "ContractRegistry":
        """Load a contracts.json file (missing/broken file -> empty registry)."""
        file_path = Path(path)
        if not file_path.exists():
            logger.info("Futures contract specs not found at %s", file_path)
            return cls()
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Cannot read futures contract specs %s: %s", file_path, exc)
            return cls()
        raw = payload.get("contracts", payload) if isinstance(payload, dict) else {}
        contracts = {}
        for pair, spec in (raw or {}).items():
            if not isinstance(spec, dict):
                continue
            contracts[pair] = FutureContract.from_dict({"pair": pair, **spec})
        logger.info("Loaded %d futures contract specs from %s", len(contracts), file_path)
        return cls(contracts)

    @classmethod
    def from_config(cls, config) -> "ContractRegistry":
        """Resolve the contracts file from configuration and load it.

        Looks at ``future.contracts_file`` first, then ``futures.contracts_file``,
        then ``<datadir>/futures/contracts.json``.
        """
        candidates = []
        for key in ("future.contracts_file", "futures.contracts_file"):
            try:
                value = config.get(key, None)
            except Exception:
                value = None
            if value:
                candidates.append(Path(str(value)))
        try:
            datadir = config.get("datadir", "user_data/data")
        except Exception:
            datadir = "user_data/data"
        candidates.append(Path(str(datadir)) / "futures" / "contracts.json")
        candidates.append(Path(DEFAULT_CONTRACTS_FILE))

        for candidate in candidates:
            if candidate.exists():
                return cls.load(candidate)
        return cls()
