# Bullseye

[![CI](https://github.com/lzy1102/bullseye/actions/workflows/ci.yml/badge.svg)](https://github.com/lzy1102/bullseye/actions/workflows/ci.yml)

**English** | [中文](README.zh-CN.md)

A quantitative trading framework compatible with [Freqtrade](https://github.com/freqtrade/freqtrade), supporting crypto, stock, and futures trading.

## Features

- **100% Freqtrade Strategy Compatible** - Use your existing Freqtrade strategies without modification
- **Multi-Market Support**:
  - Cryptocurrency (via CCXT): Binance, OKX, Bybit, Gate.io, and 100+ more
  - Chinese Stocks (via miniQMT/xtquant): A-share market (SSE, SZSE, BSE)
  - Futures (via CTP/openctp-ctp): All 6 Chinese futures exchanges (SHFE, DCE, CZCE, CFFEX, INE, GFEX)
  - Dry Run / Paper Trading: Local simulation for strategy testing
- **Unified Interface** - Same strategy can trade across different markets
- **Event-Driven Architecture** - High-performance event engine inspired by VeighNa (vnpy)
- **Backtesting Engine** - Iterative backtesting with stoploss, trailing stop, ROI, and custom exit support
  - T+1/T+N settlement enforcement (A-shares cannot be sold same-day in backtests)
  - Mark-to-market equity curve with curve-based max drawdown (captures intra-trade dips)
  - Configurable fee + adverse-slippage fill model (--slippage / backtest.slippage)
  - Structured A-share fee model: commission with per-order minimum (万2.5, min 5 CNY),
    sell-side stamp duty and transfer fee (backtest.fees)
  - Vectorized signal computation (indicators run once per pair, ~1000x faster on long histories)
  - Accepts in-memory OHLCV data (`run(data={...})`) for programmatic use
  - Startup-candle warmup: bars before the timerange are loaded so long-lookback
    indicators (SMA250, weekly gates) are valid on the first traded bar
  - Optional next-open fills (`backtest.fill_next_open`) for deployable execution
    semantics; same-bar close fills remain the default
  - BaoStock daily files additionally persist liquidity/valuation factor columns
    (`turn`, `peTTM`, `pbMRQ`, `psTTM`, `pcfNcfTTM`, `isST`) for factor research
  - Chinese futures daily backtests: Freqtrade-style sizing (stake x leverage =
    notional, only the exchange margin is locked), per-lot fees (open / close /
    close-today), contract multiplier, tick-grid fills and settlement-price
    price limits, roll-adjusted continuous series with contract-roll costs
    (specs in `user_data/data/futures/contracts.json`, see the "期货线"
    section in [docs/strategies.md](docs/strategies.md))
- **Market-Structure Library** (`user_data/strategies/chan_structure.py`) - Chan-theory
  fractals/strokes/pivots/divergence, lookahead-locked by tests; measured to add no
  edge on top of the candle×indicator setups, so it ships as a charting aid only
- **Hyperparameter Optimization** - Random search optimization with multiple loss functions
- **Flexible Database** - SQLite (default), PostgreSQL, MySQL support
- **Structured Exception Hierarchy** - Clear error handling with specific exception types

## Strategy Portfolio & Backtest Results

Reference strategies live in `user_data/strategies/` (sibling `{Strategy}.json`
parameter files are applied automatically). Unless noted, all results below
are A-share stocks, **initial capital 100,000 CNY, 2023-01-01 → 2026-10-10
(~3.8 years)**, quoted fees, T+1 settlement, 100-share lots and ±10%/20%
price-limit rules enforced. **CAGR = compound annual growth rate.**

### Stable combo — single account, two engines

| Strategy | Universe | Total | CAGR | Max DD | PF | Yearly |
|---|---|---|---|---|---|---|
| **ComboSteady** | Big-4 banks + 27 momentum names | +109.2% | +21.6% | 8.4% | 3.82 | +12.9 / +31.3 / +10.1 / +28.2 |
| TopRot | 27-name cross-sectional momentum rotation | +172.0% | +30.4% | 15.5% | 3.83 | +2.1 / +28.4 / +30.3 / +59.3 |

ComboSteady runs a slow bank trend leg and a monthly momentum-rotation leg in
one account (shared cash): every year positive, 32/45 winning months, worst
month −2.8%. TopRot swaps the pool's top-2 10-day momentum names every ≤30
days with a −10% mistake cut and a long-term filter (only names above a
rising 250-day average are eligible).

### Big-4 banks (601398 / 601288 / 601988 / 601939)

| Strategy | Total | CAGR | Max DD | PF | Trades |
|---|---|---|---|---|---|
| MacdPreGateW | +104.5% | +20.9% | 13.9% | 9.90 | 11 |
| RSIPlainW | +84.7% | +17.7% | 7.4% | 48.0 | 18 |

### Banks (7: big-4 + 600036 / 600016 / 000001)

| Strategy | Total | CAGR | Max DD | PF | Trades | Win |
|---|---|---|---|---|---|---|
| TrendGridTradingStrategySpot | +89.5% | +18.5% | 15.9% | 8.25 | 21 | 67% |
| GridBank10 | +84.7% | +17.7% | 11.3% | 8.34 | 57 | 93% |
| RSIPlainBanks | +57.9% | +12.9% | 6.7% | 7.94 | 32 | 81% |
| MacdDip5 | +54.0% | +12.1% | 12.5% | 1.98 | 212 | 44% |
| VolPriceSpot | +46.1% | +10.6% | 9.7% | 4.96 | 64 | 58% |
| TrendFollowSpot | +41.5% | +9.7% | 15.1% | 1.79 | 352 | 45% |
| DcaFixed | +38.1% | +8.9% | 9.0% | 2.36 | 94 | 61% |
| BaseSpotBanks | +28.1% | +6.8% | 12.4% | 5.46 | 24 | 54% |
| BankMACross (baseline) | +13.0% | +3.3% | 3.6% | 1.84 | 113 | 64% |

### Leaders (18 large caps: 300750 / 002594 / 688981 / 600276 / ...)

| Strategy | Total | CAGR | Max DD | PF | Trades | Win |
|---|---|---|---|---|---|---|
| VolPriceSpot | +43.8% | +10.1% | 18.8% | 1.98 | 117 | 44% |
| BaseSpot | +39.2% | +9.2% | 18.8% | 1.90 | 134 | 39% |
| RSIPlain | +38.3% | +9.0% | 9.7% | 13.3 | 13 | 85% |
| MacdDip5 | +35.2% | +8.3% | 18.4% | 1.28 | 306 | 37% |
| DcaFixed | +25.0% | +6.1% | 13.3% | 1.29 | 203 | 49% |

Benchmarks over the same window: buy & hold 7 banks ≈ +99%, 18 leaders
≈ +58%. Backtest notes: momentum/rotation returns concentrate in the
2024–2026 AI/theme bull; long-lookback strategies (SMA250 filters, weekly
gates) rely on the engine's startup-candle warmup so indicators are valid on
the first traded bar. Past performance does not guarantee future results.

### Wave-capture, defensive & archived experiments (same window, 100k CNY)

| Strategy | Idea | Total | CAGR | Max DD | PF | Verdict |
|---|---|---|---|---|---|---|
| TopRotATR | MA20 exit → 3×ATR chandelier | +118.7% | +23.1% | 22.6% | 2.51 | worse than TopRot (bigger giveback) |
| TopRotPyramid | add on 10-day highs | +14.2% | +3.6% | 14.6% | 1.54 | failed (chases tops, half base size) |
| TurtleATR 20/4 | 20d breakout + 4×ATR chandelier | +65.3% | +14.3% | 12.8% | 3.67 | usable defensive leg, below baseline |
| TurtleATR 55/3 | classic turtle | +39.0% | +9.1% | 11.4% | 2.65 | defensive, low return |
| BasketLowRisk | low-vol top-5 basket (34-stock pool) | +33.6% | +8.0% | 6.5% | 1.88 | low drawdown, low return |
| WideMultiFactor | small-cap + low-turn + reversal (138 stocks) | +46.6% | +10.7% | 20.9% | 1.66 | validates factors; sealed (charter: no small caps) |
| IndustryRot | sector momentum rotation, top-3 sectors (large-cap stats) | +46.1% | +10.6% | 13.1% | 1.66 | real edge but below stock-level rotation |
| PeadDrift | post-earnings drift, YoY ≥ 20%, 60d hold | +23.7% | +5.8% | 7.2% | 1.92 | thin but positive expectancy |
| MacdCandle | 8 candlestick+indicator setups, 3 slots | +233.4% | 37.5% | 8.78% | 3.49 | positive in all 4 sub-periods over 2016-2026 (+413.6%); only works on the hand-picked pool |
| MacdCandle (aggressive) | same setups, 2 slots | +437.6% | 56.0% | 11.9% | 3.92 | higher concentration, same shape |
| Supermarket (hold-through) | retail basket: 1 lot each, +15% sell, no stop | +61.8% | +13.6% | 18.6% | 2.22 | 86% win rate is an illusion |
| SupermarketStop -6% | same + 6% stop | +93.7% | +19.2% | 18.5% | 1.34 | best supermarket variant, still below combo |

> Two intraday research lines are also archived: intraday/overnight signals
> (EodBounce / TrendDayHold) and daily regime × 30m patterns (MTF). Both failed
> on costs and out-of-sample instability; see the "日内/隔夜信号实测" and
> "多时间框架实测" sections in [docs/strategies.md](docs/strategies.md).

**Candlestick × indicators** (see [docs/strategies.md](docs/strategies.md)): a
17-pattern + 26-indicator-state library (`user_data/strategies/candle_patterns.py`),
scored on forward returns and then traded. Volume is the pattern confirmer (three
white soldiers + volume spike, hammer / hanging man + volume dry-up); the best top
call is hanging man inside a Bollinger squeeze; divergence only works on pullbacks
(inverted hammer + MACD top divergence). The single setups earn +25…58%, but **merging
eight of them yields +233% at 8.78% drawdown** — many weak edges stack into one strong
book. Two earlier conclusions flipped once diversification was in place: top-pattern
exits *hurt* a single setup (+185% → +59%) but *help* the merged one (+241% → +305%),
and 60-day holds beat 40. Like TopRot it only works on the curated pool — the 173-stock
pool loses 4.4% — so treat it as a satellite leg, not a core strategy.

> **⚠️ Fill-convention audit (2026-10-18).** House convention is **same-bar close**
> (fee 0.001, T+1); all figures above use it and say so. Measured overnight gap:
> mean entry gap −0.1…+0.1%, gap ≤ −5% on ~2% of entries (0% for MacdCandle), return
> multiplier 0.997–1.002 — the convention is worth <0.3%, so it explains none of the
> headline differences. Two false attributions were ruled out: price-limit locking
> (disabling it changes nothing) and slot contention. One **real** engine/strategy bug
> was found and left documented: under `fill_next_open`, `confirm_trade_entry` reads
> the *execution* bar while the entry signal comes from the *previous* bar, so
> TopRot loses 60% of its entries (117 → 47; with the gate removed it is 806).
> `fill_next_open` is therefore **not** a valid robustness test for TopRot /
> ComboSteady. MacdCandle has no such gate: its honest robustness haircut is
> +413.6% → +314.4% over 2016-2026 (~24%). Ten-year same-bar results:
> MacdCandle +413.6% (DD 13.9%), ComboSteady +364.0% (DD 18.2%), TopRot +356.1%
> (DD 17.2%). `tests/test_candle_patterns.py` locks in no-lookahead correctness.

Wave-capture conclusion: exits widened (chandelier) or adds-on-strength both
degrade TopRot — its 30-day rotation plus MA20 break is already the best
wave-capture for this pool. None of these experiments beats **ComboSteady +
TopRot**, which remain the production pair.

### Factor research (2026-10)

Daily files now carry liquidity/valuation factor columns (`turn`, `peTTM`,
`pbMRQ`, `psTTM`, `pcfNcfTTM`, `isST`) from the BaoStock feed, so strategies
can read them like indicators. Cross-sectional Rank-IC vs 20-day forward
returns (2023-01 ~ 2026-10):

- **Wide universe** (138-stock random sample): small-cap premium confirmed
  (small +1.86% vs large +0.77% per 20d), illiquidity IC +0.067/IR 0.38,
  low turnover and low volatility positive — but **market-wide momentum is
  REVERSED** (mom60 IC −0.075, IR −0.41).
- **Curated pool**: mom10 slightly positive (IC +0.02) — TopRot's edge lives
  in the selected universe (theme beta), not in the broad market. That is
  both the source of its returns and its main risk.
- Factor tilts on TopRot (low-vol/low-turn hard filters or score blends) all
  degrade it (+172% → −3% ~ +30%): momentum and low-risk factors are
  mutually exclusive here.
- Small caps are excluded by charter (liquidity, delisting risk, sample
  survivorship); the 34-stock pool's smallest float is ≈ ¥48B.


## Installation

### Native Installation

```bash
# Clone the repository
git clone https://github.com/your-org/bullseye.git
cd bullseye

# Install dependencies
pip install -r requirements.txt

# Or install in development mode
pip install -e .
```

### Docker Installation

```bash
# Clone the repository
git clone https://github.com/your-org/bullseye.git
cd bullseye

# Build Docker image
docker build -t bullseye:latest .

# Or use Make
make build

# Quick start with Docker
make quickstart
```

#### Docker Compose (Recommended)

```bash
# Start with default configuration (SQLite)
docker-compose up -d

# Start with PostgreSQL database
docker-compose --profile with_db up -d

# Start with all services (database, cache, monitoring)
docker-compose --profile with_db --profile with_cache --profile with_monitoring up -d

# View logs
docker-compose logs -f bullseye

# Stop services
docker-compose down
```

#### Docker Commands

```bash
# Build and run
make build
make up

# Run trading
make trade

# Run backtesting
make backtest

# Open shell in container
make shell

# View logs
make logs

# Stop containers
make down

# Show all available commands
make help
```

#### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BULLSEYE_CONFIG` | `/app/config.yaml` | Path to configuration file |
| `BULLSEYE_USER_DATA` | `/app/user_data` | Path to user data directory |
| `DB_URL` | `sqlite:///user_data/tradesv3.sqlite` | Database connection string |
| `TZ` | `Asia/Shanghai` | Timezone |

#### Volume Mounts

```yaml
volumes:
  # Configuration file
  - ./config.yaml:/app/config.yaml:ro

  # User data directory
  - ./user_data:/app/user_data

  # Optional: Custom strategies
  - ./user_data/strategies:/app/user_data/strategies:ro

  # Optional: Historical data
  - ./user_data/data:/app/user_data/data

  # Optional: Logs
  - ./user_data/logs:/app/user_data/logs
```

## Quick Start

### 1. Create a Strategy

Your Freqtrade strategies work directly with Bullseye:

```python
from bullseye.strategy import IStrategy
from pandas import DataFrame
import talib.abstract as ta

class MyStrategy(IStrategy):
    timeframe = '5m'

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['rsi'] = ta.RSI(dataframe, 14)
        dataframe['ema20'] = ta.EMA(dataframe, 20)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe['rsi'] < 30) & (dataframe['volume'] > 0),
            ['enter_long', 'enter_tag']
        ] = (1, 'rsi_oversold')
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe['rsi'] > 70) & (dataframe['volume'] > 0),
            ['exit_long', 'exit_tag']
        ] = (1, 'rsi_overbought')
        return dataframe
```

> **Note on `@informative`**: multi-timeframe methods are executed and
> merged lookahead-safe in both backtesting and live trading. Backtests
> need the informative timeframe downloaded (e.g. `download-data
> --timeframes 1h,1d`); missing informative data warns and skips that leg,
> so guard optional columns with `if "col_1d" in dataframe.columns`.

### 2. Configure Your Market

```yaml
# config.yaml

# Settlement: ONE global switch (simplest)
#   t0: sell anytime (crypto, US/HK stocks, futures)
#   t1: sell next trading day (Chinese A-shares)
#   t2: sell in 2 trading days (conservative/custom)
# With `exchange-calendars` installed, T+1/T+2 dates skip holidays.
# Advanced per-pair control: make "settlement" a dict with
# mode/overrides/default - see config.yaml.example.
settlement: t1

market_type: crypto  # crypto | stock | future

# For crypto
exchange:
  name: binance
  key: your_api_key
  secret: your_api_secret

# For stock (China A-share via miniQMT)
stock:
  gateway: miniqmt
  qmt_path: "D:\\QMT\\userdata_mini"   # miniQMT client path
  session_id: 123456
  account_id: "your_account_id"

# For futures (China via CTP / SimNow)
future:
  gateway: ctp
  user_id: your_userid
  password: your_password
  broker_id: "9999"                     # SimNow: 9999
  td_address: "tcp://180.168.146.187:10130"
  md_address: "tcp://180.168.146.187:10131"
  auth_code: ""                         # optional, for real trading
  app_id: ""                            # optional
```

### 3. Download Data

```bash
# Download crypto data
bullseye download-data --exchange binance --pairs BTC/USDT ETH/USDT --timeframe 5m

# Download stock data (via AKShare, TuShare, or BaoStock)
bullseye download-data --market stock --pairs 000001.SZ 000002.SZ
```

### 4. Run Backtesting

```bash
# Basic backtesting
bullseye backtesting --strategy MyStrategy

# With time range and options
bullseye backtesting --strategy MyStrategy \
    --timerange 20240101-20241231 \
    --initial-balance 10000 \
    --fee 0.001 \
    --export results.json
```

Backtesting results include comprehensive metrics:
- Win rate, profit factor, Sharpe/Sortino/Calmar ratios
- Maximum drawdown, average trade duration
- Per-pair performance breakdown
- JSON export for further analysis

### 5. Run Hyperparameter Optimization

```bash
# Basic optimization
bullseye hyperopt --strategy MyStrategy --epochs 100

# With specific loss function and constraints
bullseye hyperopt --strategy MyStrategy \
    --loss sharpe \
    --epochs 200 \
    --min-trades 20 \
    --timerange 20240101-20241231 \
    --random-state 42
```

Available loss functions:
- `default` - Maximize total profit
- `sharpe` - Maximize Sharpe ratio
- `winratio` - Maximize win rate (with minimum trade requirement)
- `profit_drawdown` - Maximize profit/drawdown ratio

### 6. Run Live Trading

```bash
# Crypto (dry run)
bullseye trade --strategy MyStrategy --config config.yaml --dry

# A-share stocks (requires miniQMT client running on Windows)
bullseye trade --strategy MyStockStrategy --config config_stock.yaml --live

# Futures (via CTP / SimNow simulation)
bullseye trade --strategy MyFuturesStrategy --config config_futures.yaml --live
```

## Gateway Setup

### Cryptocurrency (CCXT)
```bash
pip install ccxt
```
Supports 100+ exchanges. No additional setup required.

### A-share Stocks (miniQMT)
```bash
pip install xtquant
```
Requires [miniQMT client](https://www.xuntou.net) running on Windows (or [xqshare](https://github.com/jasonhu/xqshare) remote on Linux/Mac).

### Historical Data Feeds & Trading Calendar
```bash
pip install tushare akshare baostock exchange-calendars
```
- **TuShare**: requires free [token](https://tushare.pro/), best data quality (server-side adjustment)
- **AKShare**: registration-free, wide coverage, best for research
- **BaoStock**: registration-free historical K-line data with qfq/hfq adjustment
- **exchange-calendars**: trading-calendar-aware T+1 settlement dates (holidays skipped, e.g. buying before National Day settles after the holiday). Falls back to weekend-skip when not installed.

### Futures (CTP)
```bash
pip install openctp-ctp==6.7.11.*
```
Register free SimNow account at [simnow.com.cn](https://www.simnow.com.cn) for testing. Real trading requires a futures broker account.

All gateways can also be installed together:
```bash
pip install -e ".[stock,future]"
```

## CLI Commands

```bash
# Trading
bullseye trade                    # Start trading
bullseye trade --dry              # Dry run (paper trading)
bullseye trade --live             # Live trading

# Backtesting
bullseye backtesting --strategy MyStrategy
bullseye backtesting --strategy MyStrategy --timerange 20240101-20241231
bullseye backtesting --strategy MyStrategy --initial-balance 10000 --fee 0.001

# Download Data
bullseye download-data            # Download market data
bullseye download-data --exchange binance --pairs BTC/USDT ETH/USDT

# Hyperopt
bullseye hyperopt --strategy MyStrategy --epochs 100
bullseye hyperopt --strategy MyStrategy --loss sharpe --min-trades 20

# Strategy Management
bullseye new-strategy             # Create new strategy template
bullseye list-strategies          # List all strategies

# Configuration
bullseye new-config               # Create new configuration file
bullseye show-config              # Show current configuration

# Information
bullseye info                     # Show system information
bullseye version                  # Show version
bullseye list-exchanges           # List supported exchanges
bullseye list-timeframes          # List supported timeframes
bullseye list-data                # List downloaded data
```

## Architecture

```
bullseye/
├── trader/           # Core trading engine
│   ├── eventengine.py
│   ├── engine.py
│   └── object/        # Data objects (Order, Trade, Tick, Bar, Kline, Position, Account)
├── gateway/          # Trading gateways
│   ├── base.py         # Abstract gateway interface
│   ├── crypto/         # CCXT gateway (Binance, OKX, Bybit, etc.)
│   ├── stock/          # miniQMT (A-share) + XTP (中泰, stub)
│   ├── future/         # CTP gateway (all 6 Chinese futures exchanges)
│   ├── international/  # placeholder
│   └── dryrun/         # Dry run (paper trading) gateway
├── strategy/         # Strategy interface (Freqtrade compatible)
│   ├── interface.py   # IStrategy v3 interface
│   └── template.py    # Strategy templates
├── data/             # Data providers
│   ├── dataprovider.py
│   ├── history/       # Historical data handlers (Parquet, Feather, JSON)
│   └── datafeed/      # External data feeds (AKShare, TuShare, BaoStock)
├── backtesting/      # Backtesting engine
│   ├── engine.py      # BacktestEngine
│   └── result.py      # BacktestResult, BacktestTrade, BacktestMetrics
├── optimize/         # Optimization tools
│   ├── hyperopt.py    # HyperoptEngine with multiple loss functions
│   └── analysis/      # Lookahead and recursive bias analysis
├── order/            # Order management
│   ├── order_executor.py
│   ├── position_manager.py
│   └── settlement.py
├── wallets/          # Wallet management
├── persistence/      # Database models (SQLAlchemy)
├── rpc/              # Remote procedure calls
│   ├── telegram.py    # Telegram notifications
│   ├── webhook.py     # Webhook notifications
│   └── api_server/    # REST API server (FastAPI)
├── configuration/    # Configuration management
├── commands/         # CLI command implementations
└── exceptions.py     # Structured exception hierarchy
```

## Exception Hierarchy

Bullseye provides a structured exception hierarchy for clear error handling:

```
BullseyeError
├── ConfigurationError
├── StrategyError
│   ├── StrategyLoadError
│   └── StrategyValidationError
├── DataError
│   ├── DataNotFoundError
│   └── DataFormatError
├── GatewayError
│   ├── GatewayConnectionError
│   ├── GatewayAuthenticationError
│   └── GatewayRateLimitError
├── OrderError
│   ├── InsufficientFundsError
│   └── OrderExecutionError
├── PositionError
├── BacktestError
├── HyperoptError
├── WalletError
└── PersistenceError
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test modules
pytest tests/test_backtesting/ -v
pytest tests/test_optimize/ -v

# Run with coverage
pytest tests/ --cov=bullseye --cov-report=html
```

Current test status: **409 passed, 9 skipped** (skipped tests require external dependencies like akshare/tushare/baostock or network access; CI runs on Python 3.10/3.12)

## Compatibility with Freqtrade

| Feature | Bullseye | Freqtrade |
|---------|----------|-----------|
| IStrategy Interface | ✅ v3 | v3 |
| @informative Decorator | ✅ (lookahead-safe merge, backtest + live) | ✅ |
| Hyperoptable Parameters | ✅ | ✅ |
| DataProvider | ✅ | ✅ |
| Callbacks | ✅ | ✅ |
| Backtesting | ✅ | ✅ |
| Hyperopt | ✅ | ✅ |
| Crypto Trading | ✅ (CCXT) | ✅ (CCXT) |
| Stock Trading | ✅ (miniQMT) | ❌ |
| Futures Trading | ✅ (CTP, 6 exchanges) | ❌ |
| Event-Driven | ✅ | ❌ |
| Structured Exceptions | ✅ | ❌ |

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgments

- [Freqtrade](https://github.com/freqtrade/freqtrade) - Strategy interface design
- [VeighNa (vnpy)](https://github.com/vnpy/vnpy) - Gateway and event engine architecture
- [CCXT](https://github.com/ccxt/ccxt) - Unified cryptocurrency exchange API
