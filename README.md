# Bullseye

A quantitative trading framework compatible with [Freqtrade](https://github.com/freqtrade/freqtrade), supporting crypto, stock, and futures trading.

## Features

- **100% Freqtrade Strategy Compatible** - Use your existing Freqtrade strategies without modification
- **Multi-Market Support**:
  - Cryptocurrency (via CCXT): Binance, OKX, Bybit, Gate.io, and more
  - Chinese Stocks: XTP, TORA, OST, EMT
  - Futures: CTP (SimNow), MiniCTP, FEMAS
  - International: IB (Interactive Brokers), TAP, DA
- **Unified Interface** - Same strategy can trade across different markets
- **Event-Driven Architecture** - High-performance event engine inspired by VeighNa (vnpy)
- **Multiple Backtesting Modes** - Vectorized backtesting, hyperparameter optimization
- **Flexible Database** - SQLite (default), PostgreSQL, MySQL support

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
from bullseye.strategy import IStrategy, informative
from pandas import DataFrame
import talib.abstract as ta

class MyStrategy(IStrategy):
    timeframe = '5m'

    # Use informative decorator for higher timeframes
    @informative('1h')
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['rsi'] = ta.RSI(dataframe, 14)
        return dataframe

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

### 2. Configure Your Market

```yaml
# config.yaml
market_type: crypto  # crypto | stock | future

# For crypto
exchange:
  name: binance
  key: your_api_key
  secret: your_api_secret

# For stock (China)
stock:
  gateway: xtp
  userid: your_userid
  password: your_password
  client_id: 1

# For futures (China)
future:
  gateway: ctp
  userid: your_userid
  password: your_password
  brokerid: "9999"
  td_address: "tcp://180.168.146.187:10130"
  md_address: "tcp://180.168.146.187:10131"
```

### 3. Run Backtesting

```bash
bullseye backtesting --strategy MyStrategy --config config.yaml
```

### 4. Run Live Trading

```bash
bullseye trade --strategy MyStrategy --config config.yaml --dry
```

## CLI Commands

```bash
# Trading
bullseye trade                    # Start trading
bullseye trade --dry              # Dry run (paper trading)
bullseye trade --live             # Live trading

# Backtesting
bullseye backtesting              # Run backtest
bullseye backtesting --strategy MyStrategy
bullseye backtesting --timerange 20240101-20241231

# Download Data
bullseye download-data            # Download market data
bullseye download-data --exchange binance --pairs BTC/USDT ETH/USDT

# Hyperopt
bullseye hyperopt                 # Hyperparameter optimization
bullseye hyperopt --epochs 100

# Strategy Management
bullseye new-strategy             # Create new strategy template
bullseye list-strategies          # List all strategies

# Analysis
bullseye plot-dataframe           # Plot analysis
bullseye plot-profit              # Plot profit curve
```

## Architecture

```
bullseye/
├── trader/           # Core trading engine
│   ├── eventengine.py
│   ├── engine.py
│   └── object/        # Data objects
├── gateway/          # Trading gateways
│   ├── base.py
│   ├── crypto/        # CCXT gateways
│   ├── stock/         # Stock gateways (XTP, TORA, OST, EMT)
│   └── future/        # Future gateways (CTP, MiniCTP, FEMAS)
├── strategy/         # Strategy interface (Freqtrade compatible)
├── data/             # Data providers
├── backtesting/      # Backtesting engine
└── persistence/      # Database models
```

## Compatibility with Freqtrade

| Feature | Bullseye | Freqtrade |
|---------|----------|-----------|
| IStrategy Interface | ✅ v3 | v3 |
| @informative Decorator | ✅ | ✅ |
| Hyperoptable Parameters | ✅ | ✅ |
| DataProvider | ✅ | ✅ |
| Callbacks | ✅ | ✅ |
| Crypto Trading | ✅ (CCXT) | ✅ (CCXT) |
| Stock Trading | ✅ | ❌ |
| Futures Trading | ✅ | ❌ |
| Event-Driven | ✅ | ❌ |

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgments

- [Freqtrade](https://github.com/freqtrade/freqtrade) - Strategy interface design
- [VeighNa (vnpy)](https://github.com/vnpy/vnpy) - Gateway and event engine architecture
- [CCXT](https://github.com/ccxt/ccxt) - Unified cryptocurrency exchange API
