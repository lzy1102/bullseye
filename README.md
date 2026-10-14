# Bullseye

[![CI](https://github.com/lzy1102/bullseye/actions/workflows/ci.yml/badge.svg)](https://github.com/lzy1102/bullseye/actions/workflows/ci.yml)

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
| @informative Decorator | ⚠️ syntax only | ✅ |
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
