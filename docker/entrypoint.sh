#!/bin/bash
# Bullseye Framework - Docker Entrypoint Script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
CONFIG_FILE="${BULLSEYE_CONFIG:-/app/config.yaml}"
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

# Function to create default config if not exists
create_default_config() {
    if [ ! -f "${CONFIG_FILE}" ]; then
        if [ -f "${BULLSEYE_HOME}/config.yaml.example" ]; then
            log_warn "Config file not found. Creating from example..."
            cp "${BULLSEYE_HOME}/config.yaml.example" "${CONFIG_FILE}"
            log_info "Default config created at: ${CONFIG_FILE}"
            log_warn "Please edit the config file and restart the container."
        else
            log_error "No config file or example found!"
            exit 1
        fi
    fi
}

# Function to create necessary directories
create_directories() {
    log_info "Creating necessary directories..."
    mkdir -p "${USER_DATA_DIR}"/{strategies,data,logs,backtest_results}
    mkdir -p "${USER_DATA_DIR}/data"/{crypto,stock,futures}
}

# Function to verify Python installation
verify_python() {
    log_info "Verifying Python installation..."

    if ! python -c "import pandas" 2>/dev/null; then
        log_error "pandas not installed. Installing dependencies..."
        pip install -q -r "${BULLSEYE_HOME}/requirements.txt"
    fi

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

# Function to wait for database (if using PostgreSQL)
wait_for_db() {
    if [[ "${DB_URL:-}" == postgresql://* ]]; then
        log_info "Waiting for PostgreSQL database..."

        local db_host=$(echo "$DB_URL" | awk -F[@/] '{print $4}')
        local db_port=$(echo "$DB_URL" | awk -F[@:] '{print $5}' | cut -d'/' -f1)

        timeout=30
        while ! nc -z "$db_host" "${db_port:-5432}" 2>/dev/null; do
            timeout=$((timeout - 1))
            if [ $timeout -le 0 ]; then
                log_error "Database connection timeout!"
                exit 1
            fi
            echo -n "."
            sleep 1
        done
        echo ""
        log_info "Database is ready!"
    fi
}

# Function to show usage
show_usage() {
    cat << EOF
Usage: docker run [OPTIONS] bullseye [COMMAND] [ARGS]

Commands:
  trade              Start trading bot (default)
    --dry            Run in dry-run (paper trading) mode
    --live           Run in live trading mode

  backtesting        Run backtesting
    --strategy NAME  Strategy name to use
    --timerange RANGE Time range for backtesting

  download-data      Download historical data
    --exchange NAME  Exchange name (binance, okx, etc.)
    --pairs PAIRS    Trading pairs

  hyperopt           Run hyperparameter optimization
    --epochs N       Number of epochs
    --spaces SPACES  Spaces to optimize

  new-strategy       Create a new strategy
    --strategy NAME  Strategy name

  list-strategies    List available strategies

  list-exchanges     List supported exchanges

  list-timeframes    List supported timeframes

  version            Show version info

  info               Show system info

  shell              Start interactive shell

Examples:
  docker run bullseye trade --dry
  docker run bullseye backtesting --strategy SampleStrategy --timerange 20240101-20241231
  docker run -v ./user_data:/app/user_data bullseye download-data --exchange binance

For more information, see: https://github.com/yourusername/bullseye
EOF
}

# Main setup
setup() {
    create_directories
    create_default_config
    verify_python
    wait_for_db
}

# Run setup
setup

# Execute command
if [ $# -eq 0 ]; then
    log_info "No command specified. Starting default: trade --dry"
    exec python -m bullseye trade --dry
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
