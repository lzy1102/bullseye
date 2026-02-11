# Bullseye Quantitative Trading Framework - Makefile
# Provides convenient commands for Docker-based development and deployment

.PHONY: help build up down restart logs shell test clean

# Default target
.DEFAULT_GOAL := help

# Docker configuration
IMAGE_NAME := bullseye
CONTAINER_NAME := bullseye_trading
COMPOSE_FILE := docker-compose.yml

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(BLUE)Bullseye Quantitative Trading Framework$(NC)"
	@echo ""
	@echo "$(GREEN)Usage:$(NC) make [target]"
	@echo ""
	@echo "$(GREEN)Available targets:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'

build: ## Build Docker image
	@echo "$(BLUE)Building Docker image...$(NC)"
	docker build -t $(IMAGE_NAME):latest .
	@echo "$(GREEN)Build complete!$(NC)"

build-no-cache: ## Build Docker image without cache
	@echo "$(BLUE)Building Docker image (no cache)...$(NC)"
	docker build --no-cache -t $(IMAGE_NAME):latest .
	@echo "$(GREEN)Build complete!$(NC)"

up: ## Start containers (default mode: dry-run)
	@echo "$(BLUE)Starting Bullseye in dry-run mode...$(NC)"
	docker-compose -f $(COMPOSE_FILE) up -d bullseye
	@echo "$(GREEN)Bullseye started!$(NC)"
	@echo "$(YELLOW)View logs: make logs$(NC)"

up-live: ## Start live trading (USE WITH CAUTION!)
	@echo "$(YELLOW)WARNING: Starting LIVE trading mode!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker-compose -f $(COMPOSE_FILE) run --rm bullseye trade --live; \
	fi

down: ## Stop containers
	@echo "$(BLUE)Stopping containers...$(NC)"
	docker-compose -f $(COMPOSE_FILE) down
	@echo "$(GREEN)Containers stopped!$(NC)"

restart: ## Restart containers
	@echo "$(BLUE)Restarting containers...$(NC)"
	docker-compose -f $(COMPOSE_FILE) restart bullseye
	@echo "$(GREEN)Containers restarted!$(NC)"

logs: ## Show logs from running containers
	docker-compose -f $(COMPOSE_FILE) logs -f bullseye

logs-all: ## Show logs from all containers
	docker-compose -f $(COMPOSE_FILE) logs -f

ps: ## Show running containers
	docker-compose -f $(COMPOSE_FILE) ps

shell: ## Open shell in running container
	docker-compose -f $(COMPOSE_FILE) exec bullseye /bin/bash

shell-root: ## Open shell as root user
	docker-compose -f $(COMPOSE_FILE) exec --user root bullseye /bin/bash

# Trading commands
trade: ## Start trading (default: dry-run)
	docker-compose -f $(COMPOSE_FILE) run --rm bullseye trade --dry

backtest: ## Run backtesting
	docker-compose -f $(COMPOSE_FILE) run --rm bullseye backtesting

download-data: ## Download market data
	docker-compose -f $(COMPOSE_FILE) run --rm bullseye download-data

hyperopt: ## Run hyperparameter optimization
	docker-compose -f $(COMPOSE_FILE) run --rm bullseye hyperopt

new-strategy: ## Create new strategy
	@read -p "Strategy name: " STRATEGY_NAME; \
	docker-compose -f $(COMPOSE_FILE) run --rm bullseye new-strategy --strategy $$STRATEGY_NAME

list-strategies: ## List available strategies
	docker-compose -f $(COMPOSE_FILE) run --rm bullseye list-strategies

# Database commands
up-db: ## Start with PostgreSQL database
	docker-compose -f $(COMPOSE_FILE) --profile with_db up -d bullseye postgres

up-all: ## Start with all services (database, cache, monitoring)
	docker-compose -f $(COMPOSE_FILE) --profile with_db --profile with_cache --profile with_monitoring up -d

# Development commands
dev-jupyter: ## Start Jupyter notebook for strategy development
	docker-compose -f $(COMPOSE_FILE) --profile with_dev up -d jupyter
	@echo "$(GREEN)Jupyter started at http://localhost:8888$(NC)"

dev-grafana: ## Start Grafana for monitoring
	docker-compose -f $(COMPOSE_FILE) --profile with_monitoring up -d grafana prometheus
	@echo "$(GREEN)Grafana started at http://localhost:3000$(NC)"
	@echo "$(YELLOW)Username: admin$(NC)"
	@echo "$(YELLOW)Password: admin$(NC)"

# Testing
test: ## Run tests in Docker
	docker-compose -f $(COMPOSE_FILE) run --rm bullseye python -m pytest tests/

test-unit: ## Run unit tests only
	docker-compose -f $(COMPOSE_FILE) run --rm bullseye python -m pytest tests/unit/

test-integration: ## Run integration tests only
	docker-compose -f $(COMPOSE_FILE) run --rm bullseye python -m pytest tests/integration/

# Utility commands
clean: ## Remove containers, volumes, and images
	@echo "$(YELLOW)This will remove all containers, volumes, and images!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker-compose -f $(COMPOSE_FILE) down -v --remove-orphans; \
		docker rmi $(IMAGE_NAME):latest 2>/dev/null || true; \
		echo "$(GREEN)Cleanup complete!$(NC)"; \
	fi

prune: ## Remove unused Docker resources
	docker system prune -f
	@echo "$(GREEN)Docker pruned!$(NC)"

status: ## Show container status
	@echo "$(BLUE)Container Status:$(NC)"
	@docker-compose -f $(COMPOSE_FILE) ps
	@echo ""
	@echo "$(BLUE)Resource Usage:$(NC)"
	@docker stats --no-stream $(CONTAINER_NAME) 2>/dev/null || echo "Container not running"

info: ## Show system information
	docker-compose -f $(COMPOSE_FILE) run --rm bullseye info

version: ## Show version
	docker-compose -f $(COMPOSE_FILE) run --rm bullseye version

# Configuration commands
config-validate: ## Validate configuration file
	docker-compose -f $(COMPOSE_FILE) run --rm bullseye python -c \
		"from bullseye.configuration import Configuration; import yaml; config = yaml.safe_load(open('/app/config.yaml.example')); print('Config OK')"

# Quick start
quickstart: build ## Quick start: build and run
	@echo "$(BLUE)Creating config from example...$(NC)"
	@if [ ! -f config.yaml ]; then \
		cp config.yaml.example config.yaml; \
		echo "$(GREEN)Config created at config.yaml$(NC)"; \
		echo "$(YELLOW)Please edit config.yaml with your API keys!$(NC)"; \
	fi
	@echo "$(BLUE)Starting Bullseye...$(NC)"
	$(MAKE) up
	@echo ""
	@echo "$(GREEN)Bullseye is running!$(NC)"
	@echo "$(YELLOW)Next steps:$(NC)"
	@echo "  1. Edit config.yaml with your API keys"
	@echo "  2. Create or place your strategies in user_data/strategies/"
	@echo "  3. Run 'make logs' to see output"
	@echo "  4. Run 'make down' to stop"
