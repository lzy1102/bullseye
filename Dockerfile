# Bullseye Quantitative Trading Framework - Dockerfile
# Multi-stage build for optimal image size

FROM python:3.12-slim AS builder

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    gcc \
    g++ \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Final stage
FROM python:3.12-slim

# Set labels
LABEL maintainer="Bullseye Framework"
LABEL description="Quantitative Trading Framework - Crypto, Stock, Futures"
LABEL version="0.1.0"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/venv/bin:$PATH" \
    BULLSEYE_HOME="/app" \
    BULLSEYE_USER_DATA="/app/user_data" \
    BULLSEYE_CONFIG="/app/user_data/config.yaml"

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN groupadd -r bullseye && useradd -r -g bullseye -G audio,video bullseye \
    && mkdir -p /app /app/user_data /app/user_data/strategies \
    /app/user_data/data /app/user_data/logs /app/user_data/backtest_results

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt pyproject.toml ./

# Optional PyPI mirror (e.g. --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
# on networks where pypi.org is blocked/slow). Defaults to official PyPI.
ARG PIP_INDEX_URL=https://pypi.org/simple

# Install Python dependencies (core + A-share datafeeds + futures;
# xtquant/miniQMT is Windows-only and intentionally excluded — run it
# natively on Windows or via xqshare remote instead)
RUN python -m venv /app/venv && \
    . /app/venv/bin/activate && \
    pip install --index-url ${PIP_INDEX_URL} --retries 10 --timeout 120 -r requirements.txt && \
    pip install --index-url ${PIP_INDEX_URL} --retries 10 --timeout 120 "akshare>=1.12.0" "tushare>=1.4.0" "baostock>=0.8.9" \
        "exchange-calendars>=4.5.0" "openctp-ctp>=6.7.0"

# UTF-8 locale (C++ extensions such as py_mini_racer via akshare abort
# without it: "locale::facet::_S_create_c_locale name not valid")
RUN apt-get update && apt-get install -y --no-install-recommends locales \
    && rm -rf /var/lib/apt/lists/* \
    && sed -i -e 's/# C.UTF-8 UTF-8/C.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen C.UTF-8
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

# Copy application code
COPY bullseye/ ./bullseye/
COPY user_data/strategies/ ./user_data/strategies/

# Copy entrypoint and configuration
COPY docker/entrypoint.sh /entrypoint.sh
COPY config.yaml.example ./config.yaml.example

# Make entrypoint executable
RUN chmod +x /entrypoint.sh

# NOTE: no recursive chown — on some overlayfs/LVM hosts `chown -R` over the
# multi-GB venv stalls for tens of minutes. The image runs as root (batch
# data/backtest worker); user_data is a mounted volume managed on the host.
# To run as non-root instead: create a pre-chowned host dir and add
# `--user $(id -u):$(id -g)` to docker run.

# Expose ports
# 9876: API server
# 8765: WebSocket
EXPOSE 9876 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:9876/api/v1/ping || exit 1

# Set default entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# Default command - can be overridden
CMD ["trade"]
