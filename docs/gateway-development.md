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
  datafeed: baostock          # historical bars fallback (see below)
execution:
  order_timeout: 10
  order_poll_interval: 0.5
```

`_create_gateway()` loads the class dynamically; every key under `custom`
except `gateway` itself is forwarded to `connect(**kwargs)`.

### Market data for execution-only gateways

The `DataProvider` fetches K-lines via `gateway.get_bars()`. Bridges and
app-automation backends usually have no historical data, and CTP only
serves live ticks - so historical bars come from a **fallback datafeed**:

1. Implement `get_bars()` if your bridge can serve history (optional
   `/bars` endpoint - see `TemplateGateway.get_bars`).
2. Otherwise configure `<market>.datafeed` (`baostock` / `tushare` /
   `akshare`). `DataProvider` tries the gateway first and falls back to
   the datafeed when it returns nothing.

Without either, the strategy receives empty dataframes and will not
trade - startup logs a warning.

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

## 6. THS (同花顺) counter gateway — retail accounts without miniQMT

`ths-trade-client` (<https://github.com/lzy1102/ths_rea>, MIT) is a pure-Python
client for the THS counter protocol used by the xiadan client: login → bootstrap
→ precheck → queries → 沪/深 × 买/卖 × 市价/限价. No THS client process, no QR
code, no password; verified on Windows/Linux/Docker. Broker-agnostic: a new
broker only needs a new `local_profile.json` (account, SH/SZ shareholder IDs,
name, `deptid`, `verinfo`, site list).

```bash
pip install "ths-trade-client>=0.13.1"
ths-capture-profile            # with xiadan.exe running -> local_profile.json
```

Pin **>= 0.13.1**: before it, `precheck()` waited for a 0x10 reply that never
comes during trading hours (the 0124 answer arrives on the 0x50 push channel),
so it hung until timeout. `buy_market` / `limit_order` call precheck internally
for the reference price, so an order placed mid-session would block for the
whole timeout. 0.13.1 also cleans the GBK reply text (`clean_text`), which is
what lets `extract_counter_no` read 委托编号 from `reply['text']` instead of
falling back to a reconcile. `tests/test_ths_gateway.py::TestThsClientContract`
pins the version floor and the methods we call.

```yaml
market_type: custom
custom:
  gateway: "bullseye.gateway.stock.ths_gateway.ThsGateway"
  profile: "user_data/local_profile.json"
  heartbeat: 30                  # counter keepalive seconds (0 = off)
  kill_switch_file: "user_data/KILL_TRADING"
  confirm_timeout: 10            # order confirmation budget
  poll_interval: 0.5
  reconcile_grace: 3.0           # reconcile wait before the single resend
  enforce_trading_window: true   # local session guard
  datafeed: baostock             # K-lines still come from baostock
```

Every key under `custom:` except `gateway` is forwarded to `connect()`
(`bot.py::_gateway_connect_kwargs`), so the block above is the full surface.

### Login parameters (`local_profile.json`)

They live in a **file**, not in the YAML: the fund account and shareholder IDs
are credentials. Template: `user_data/local_profile.example.json` (git-ignored
once renamed to `local_profile.json`).

| Field | Required | Meaning |
|---|---|---|
| `zjzh` | ✅ | 资金账号 — the only credential; no QR code, no password |
| `gdzh_sh` | ✅ | 上海股东号, **starts with `A`** (e.g. `A123456789`) |
| `gdzh_sz` | ✅ | 深圳股东号, **digits only** (e.g. `0123456789`) |
| `name` | recommended | 户名, GBK 1–6 bytes (1–3 Chinese chars) |
| `deptid` | optional | 营业部 ID (default `1302`) |
| `verinfo` | optional | 券商标记 (`gtja` = 国泰君安/国泰海通) |
| `host` / `port` | optional | 主柜台 (default `114.141.180.27:8002`) — **change per broker** |
| `hosts` | optional | 站点表 `[{"ip","port","name","area"}]` for failover |
| `machine` | optional | 设备指纹; counter does not validate it, auto-collected when missing |

Fastest path on Windows — double-click:

```
scripts\capture_ths_profile.bat
```

It checks Python, installs `ths-trade-client[capture]`, waits for `xiadan.exe`,
runs the capture straight into `user_data/local_profile.json`, validates the
required fields and prints the next commands. Extra flags pass through
(`--timeout 600`, `--pid 12345`). The `.bat` is deliberately ASCII-only
(`cmd.exe` mis-parses non-ASCII batch files); the Chinese UI lives in
`scripts/capture_ths_profile.py`, which fixes the console code page itself so
the output is readable however it is launched.

Doing it manually is equivalent: run `ths-capture-profile` once with the
broker's xiadan client logged in — it fills every field including the device
fingerprint and the site list. A different broker needs no code change, only a
new profile (the DES key and frame format are client-level constants, identical
across brokers).

`local_profile.json` holds the fund account, shareholder IDs and the device
fingerprint — it is git-ignored and must never be committed.

### Current status: placement implemented but gated; cancel still missing

`bullseye/gateway/stock/ths_gateway.py` implements `connect`, `close`,
`query_account`, `query_position`, `query_order`, `query_contract`, quote
pushes (`on_push` → throttled `on_tick`) and `send_order`.

`send_order` is written for the fact that **order placement is not
idempotent**, so it never trusts a bare retry:

1. guards — `custom.live_trading` (default false), kill-switch file, local
   A-share session window (`enforce_trading_window`);
2. local dedup — the same `client_order_id` is never sent twice;
3. **reconcile before send** — if 当日委托 already holds a live order with the
   same symbol/side/volume, adopt its 委托编号 instead of sending;
4. submit with `TradeClient.auto_reconnect` temporarily disabled (its built-in
   "retry once" is fine for queries and would double-buy for orders);
5. on an ambiguous failure (dropped socket) → reconcile again, and resend **at
   most once**, only if the order is provably absent.

`client_order_id → 委托编号` mapping, `reconcile_orders()` (adopts foreign
orders as `THS-EXT-<no>`), `confirm_order()` (publishes status changes and fill
deltas) and the `Status` mapping round it out. Parsing of the GBK key=value
replies is defensive throughout.

`cancel_order` still raises `NotImplementedError`, and `send_order` is gated
by `custom.live_trading`, which defaults to **false**: without 撤单 an exit that
misses becomes an unmanageable position, so the switch stays off until cancel
lands. The flag is read by `connect()`, and startup logs which mode it is in
(`THS live trading disabled (custom.live_trading=false): read-only`).

As of v0.13.1 the 撤单 command family is identified (XX02: `0222`/`0322`;
`0122`/`0222`/`0322` are refused by the service layer before the body is parsed,
`0220`/`0320`/`0422`/`0224` answer "无效请求", `0212` "验证签名错"), but no capture
with a live cancellable order exists yet — the parameters (most likely `htbh`
合同号) are still unknown. That capture is the remaining input for blocker #1. Everything above is covered offline by `tests/test_ths_gateway.py`
(scripted fake counter - no network, no ths-trade-client).

### Rollout order

1. Read-only: run `trade --dry` and reconcile account/positions against the
   broker app. Confirms login, bootstrap and field semantics.
2. Add cancel (capture the frame with `ths-capture-orders`, implement, cover in
   offline tests).
3. Flip `custom.live_trading` behind the explicit config switch, dry-run
   first against 模拟盘, then a single 100-share order.

## 7. Acceptance checklist

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
