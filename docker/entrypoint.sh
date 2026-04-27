#!/bin/bash
# Bullseye Framework - Docker Entrypoint Script
# Compatible with Freqtrade command style

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
CONFIG_FILE="${BULLSEYE_CONFIG:-/app/user_data/config.yaml}"
USER_DATA_DIR="${BULLSEYE_USER_DATA:-/app/user_data}"
BULLSEYE_HOME="${BULLSEYE_HOME:-/app}"

# Print banner
echo -e "${GREEN}"
echo "================================================"
echo "     Bullseye Quantitative Trading Framework     "
echo "================================================"
echo -e "${NC}"
echo "Version: 0.1.0"
echo "Python: $(python --version)"
echo "Working Directory: ${BULLSEYE_HOME}"
echo "Config File: ${CONFIG_FILE}"
echo "User Data: ${USER_DATA_DIR}"
echo ""

# Function to log messages
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to create necessary directories
create_directories() {
    log_info "Creating necessary directories..."
    mkdir -p "${USER_DATA_DIR}"/{strategies,data,logs,backtest_results,hyperopt}
    mkdir -p "${USER_DATA_DIR}/data"/{crypto,stock,futures}
}

# Function to verify Python installation
verify_python() {
    log_info "Verifying Python installation..."

    # Verify key modules
    local modules=("pandas" "numpy" "ccxt" "sqlalchemy" "pydantic" "click" "rich")
    for module in "${modules[@]}"; do
        if python -c "import $module" 2>/dev/null; then
            echo -n "  ✓ $module"
        else
            echo -n "  ✗ $module (MISSING)"
        fi
    done
    echo ""
}

# Function to show usage
show_usage() {
    cat << EOF
Usage: docker-compose run --rm bullseye [COMMAND] [ARGS]

Commands:
  download-data      Download historical data
    --exchange NAME  Exchange name (binance, okx, etc.)
    --pairs PAIRS    Trading pairs (comma or space separated)
    --timeframes TF  Timeframes (comma separated)
    --timerange RANGE Time range (YYYYMMDD-YYYYMMDD)
    --prepend        Prepend to existing data

  backtesting        Run backtesting
    --strategy NAME  Strategy name to use
    --timerange RANGE Time range for backtesting
    --timeframe TF   Timeframe

  hyperopt           Run hyperparameter optimization
    --strategy NAME  Strategy name
    --hyperopt-loss NAME  Loss function (SharpeHyperOptLoss, etc.)
    --epochs N       Number of epochs
    --spaces SPACES  Spaces to optimize (buy, sell, roi, stoploss, trailing, all)

  hyperopt-list      List hyperopt results
    --best           Show only best results

  hyperopt-show      Show hyperopt result details
    --index N        Result index

  new-strategy       Create a new strategy
    --strategy NAME  Strategy name

  list-strategies    List available strategies

  list-exchanges     List supported exchanges

  list-timeframes    List supported timeframes

  trade              Start trading bot
    --dry            Dry-run mode
    --live           Live trading mode

Examples:
  docker-compose run --rm bullseye download-data --exchange okx --pairs BTC/USDT --timeframes 30m
  docker-compose run --rm bullseye backtesting --strategy MyStrategy --timerange 20240101-20241231
  docker-compose run --rm bullseye hyperopt --strategy MyStrategy --hyperopt-loss SharpeHyperOptLoss --epochs 1000

For more information, see: https://github.com/yourusername/bullseye
EOF
}

# Main setup
setup() {
    create_directories
    verify_python
}

# Run setup
setup

# Execute command
if [ $# -eq 0 ]; then
    log_info "No command specified. Showing usage..."
    show_usage
    exit 0
else
    case "$1" in
        shell|bash)
            log_info "Starting interactive shell..."
            exec /bin/bash
            ;;
        help|--help|-h)
            show_usage
            exit 0
            ;;
        *)
            log_info "Starting Bullseye with command: $@"
            exec python -m bullseye "$@"
            ;;
    esac
fi
