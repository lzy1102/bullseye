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

# Install TA-Lib (technical analysis library)
WORKDIR /tmp
RUN wget -q https://github.com/TA-Lib/ta-lib/archive/refs/tags/ta-lib-0.4.0.tar.gz \
    && tar -xzf ta-lib-0.4.0.tar.gz \
    && cd ta-lib \
    && ./configure --prefix=/usr \
    && make \
    && make install \
    && cd .. \
    && rm -rf ta-lib ta-lib-0.4.0.tar.gz

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
    BULLSEYE_CONFIG="/app/config.yaml"

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ta-lib \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN groupadd -r bullseye && useradd -r -g bullseye -G audio,video bullseye \
    && mkdir -p /app /app/user_data /app/user_data/strategies \
    /app/user_data/data /app/user_data/logs /app/user_data/backtest_results

# Copy TA-Lib from builder
COPY --from=builder /usr/lib/libta*.* /usr/lib/
COPY --from=builder /usr/include/ta-lib/ /usr/include/ta-lib/
COPY --from=builder /usr/local/lib/libta*.* /usr/local/lib/

# Update library cache
RUN ldconfig

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt pyproject.toml ./

# Install Python dependencies
RUN python -m venv /app/venv && \
    . /app/venv/bin/activate && \
    pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# Copy application code
COPY bullseye/ ./bullseye/
COPY user_data/strategies/ ./user_data/strategies/

# Copy entrypoint and configuration
COPY docker/entrypoint.sh /entrypoint.sh
COPY config.yaml.example ./config.yaml.example

# Make entrypoint executable
RUN chmod +x /entrypoint.sh

# Change ownership
RUN chown -R bullseye:bullseye /app

# Switch to non-root user
USER bullseye

# Expose ports
# 8080: API server
# 8765: WebSocket
EXPOSE 8080 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/v1/ping || exit 1

# Set default entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# Default command - can be overridden
CMD ["trade"]
