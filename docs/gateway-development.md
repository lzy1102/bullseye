# Gateway Development Standard

How to plug a custom execution backend (broker API, personal order bridge,
automation service) into Bullseye for **live trading**.

A reference implementation lives in
[`bullseye/gateway/template/gateway_template.py`](../bullseye/gateway/template/gateway_template.py)
(the HTTP order-bridge pattern). Copy and adapt it.

---

## 1. Required interface (`BaseGateway`)

Subclass `BaseGateway` (see `bullseye/gateway/base.py`) and implement:

| Method | Contract |
|--------|----------|
| `connect(**kwargs)` | Establish the connection. Set `self._connected = True`. Raise on failure (startup aborts loudly). |
| `close()` | Disconnect. Must be **idempotent**. |
| `send_order(req) -> str \| None` | Submit an order, return a **stable order id**. `None`/exception = rejected. Never invent an id you cannot query later. |
| `cancel_order(req) -> bool` | Cancel by `orderid`. |
| `query_account() -> AccountData` | Balance snapshot. |
| `query_position() -> list[PositionData]` | Current positions. |
| `query_order(req) -> OrderData` | **Order state read-back** - the confirmation loop depends on this. |
| `query_contract() -> list[ContractData]` | Instruments; may return `[]`. |

Optional: `subscribe_quote`, `get_bars`, `get_tick`, `get_order_book`.

## 2. Order lifecycle events (the real quality bar)

Submitting is not success - **report the lifecycle** via the inherited
`on_order` / `on_trade` publishers:

```
send_order() returns orderid
  │  on_order: NOTTRADED            "accepted" - only after the backend confirms
  │  on_order: PARTTRADED           partial fills
  │  on_trade: TradeData            one event per NEW fill delta
  └─ on_order: ALLTRADED / CANCELLED / REJECTED   terminal state
```

Hard rules:

1. **Never trust the submission click/tap.** Poll `query_order` (or consume
   callbacks) and publish only what the backend reports.
2. **orderid is stable and re-queryable** across process restarts. If the
   backend supports a client order id field (remarks/memo), echo the
   framework id into it for reconciliation.
3. **Trade events are the source of truth for position changes** - one
   `TradeData` per fill delta, `tradeid` unique, linked by `orderid`.
4. **Status is monotonic.** No terminal -> non-terminal transitions.
5. Repeated identical statuses are idempotent but should be de-duplicated
   (see `_emit_order_if_changed` in the template).
6. Publishing is thread-safe; keep callbacks non-blocking.

## 3. Reliability requirements

| Requirement | Why |
|-------------|-----|
| **Polling confirmation loop** | The executor waits for a terminal status after every order; a backend without it cannot be routed live. |
| **Reconciliation** (`reconcile_open_orders` in the template) | On startup and periodically, pull open orders/positions from the backend and publish them - the backend is the source of truth. |
| **Kill switch** | A marker file (or config flag) that blocks NEW orders instantly. Cancels stay allowed. |
| **Idempotency** | Retries must not double-submit: key on the framework orderid / client order id. |
| **Uncertainty = failure** | Timeout or unreadable state: return `None` / log an error; never book a guessed fill. Missing a trade beats booking a wrong one. |
| **Rate limits** | Stay within backend limits; log throttling. |

## 4. How the framework uses your gateway

```
                       ┌────────────────────────────┐
  strategy signal ──►  │ OrderExecutor              │
                       │  is_live = gateway and     │
                       │            not dry_run     │
                       └─────────┬──────────────────┘
                                 │ send_order(req)
                                 ▼
                       ┌────────────────────────────┐
                       │ YourGateway                │
                       │  poll query_order until    │
                       │  terminal (or timeout)     │
                       └─────────┬──────────────────┘
                                 │ fill confirmed
                                 ▼
                       LocalTrade booked at ACTUAL
                       fill price / quantity; wallet
                       updated; T+1 gate enforced
```

Key facts:

- The T+1/T+N availability gate runs **before** any order is sent
  (`OrderExecutor.execute_exit`), so un-sellable positions never reach
  your backend.
- Live entries book the **filled** quantity/price; a fill of `0` after
  timeout is not booked at all.
- Partial **exits** are treated conservatively: remainder is cancelled,
  the trade stays open, an error is logged for manual reconciliation.
- Timeouts / polling are configured via
  `execution.order_timeout` (default 10s) and
  `execution.order_poll_interval` (default 0.5s).

## 5. Wiring it in

### Configuration

```yaml
market_type: custom
custom:
  gateway: "my_package.my_module.MyBrokerGateway"   # module.ClassName
  base_url: "http://127.0.0.1:8000"                  # -> connect(**kwargs)
  token: ""
  kill_switch_file: ".trading_disabled"
execution:
  order_timeout: 10
  order_poll_interval: 0.5
```

`_create_gateway()` loads the class dynamically; every key under `custom`
except `gateway` itself is forwarded to `connect(**kwargs)`.

### Minimal class skeleton

```python
from bullseye.gateway.base import BaseGateway

class MyBrokerGateway(BaseGateway):
    def connect(self, **kwargs):
        self._base_url = kwargs["base_url"]
        self._connected = True

    def close(self):
        self._connected = False

    def send_order(self, req):
        orderid = self._submit(req)      # your transport
        return orderid

    def query_order(self, req):
        raw = self._get(f"/orders/{req['orderid']}")
        return self._to_order_data(raw)  # map to OrderData + Status
```

## 6. Acceptance checklist

- [ ] All 8 required methods implemented; `close()` idempotent
- [ ] `send_order` returns a queryable, stable id (never `None` on success)
- [ ] Confirmation loop publishes the full lifecycle incl. `on_trade` deltas
- [ ] Kill switch blocks new orders, allows cancels
- [ ] Reconciliation restores open-order state after restart
- [ ] Timeouts surface as failures, never as guessed fills
- [ ] Unit tests with a scripted/fake transport cover: full fill, rejection,
      timeout, partial fill, kill switch
- [ ] Tested against the real backend with **dry-run first**, then minimal
      size orders

> **Honest warning about UI-automation backends** (Android automation,
> screen-scraping apps): "the tap succeeded" is not order confirmation and
> the automation can break silently on any app update. If you go this route,
> treat the read-back loop, reconciliation and kill switch above as
> mandatory - and start with tiny order sizes.
