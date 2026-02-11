#!/bin/bash
# Bullseye Framework - Server Deployment Script
# Run this script on your server to deploy Bullseye

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/opt/bullseye"
REPO_URL="https://github.com/your-org/bullseye.git"  # Update with your repo
GIT_BRANCH="main"
USER_DATA_DIR="${INSTALL_DIR}/user_data"

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_banner() {
    echo -e "${BLUE}"
    echo "================================================"
    echo "     Bullseye Framework - Server Deployment     "
    echo "================================================"
    echo -e "${NC}"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "This script must be run as root"
        exit 1
    fi
}

detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        VERSION=$VERSION_ID
    else
        log_error "Cannot detect OS"
        exit 1
    fi
    log_info "Detected OS: $OS $VERSION"
}

install_docker() {
    log_info "Installing Docker..."

    case $OS in
        ubuntu|debian)
            apt-get update
            apt-get install -y ca-certificates curl gnupg lsb-release

            # Add Docker's official GPG key
            mkdir -p /etc/apt/keyrings
            curl -fsSL https://download.docker.com/linux/$OS/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg

            # Set up repository
            echo \
              "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$OS \
              $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

            apt-get update
            apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
            ;;
        centos|rhel|rocky|almalinux)
            yum install -y yum-utils
            yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
            yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
            ;;
        alpine)
            apk add docker docker-cli-compose
            ;;
        *)
            log_error "Unsupported OS: $OS"
            exit 1
            ;;
    esac

    # Start and enable Docker
    systemctl start docker
    systemctl enable docker

    log_info "Docker installed successfully"
    docker --version
    docker compose version
}

install_git() {
    if ! command -v git &> /dev/null; then
        log_info "Installing Git..."
        case $OS in
            ubuntu|debian)
                apt-get install -y git
                ;;
            centos|rhel|rocky|almalinux)
                yum install -y git
                ;;
            alpine)
                apk add git
                ;;
        esac
    fi
    log_info "Git version: $(git --version)"
}

create_bullseye_user() {
    if ! id -u bullseye > /dev/null 2>&1; then
        log_info "Creating bullseye user..."
        useradd -r -s /bin/bash -d $INSTALL_DIR bullseye
        usermod -aG docker bullseye
    else
        log_info "User bullseye already exists"
    fi
}

setup_firewall() {
    log_info "Configuring firewall..."

    if command -v firewall-cmd &> /dev/null; then
        # FirewallD (CentOS/RHEL)
        firewall-cmd --permanent --add-port=8080/tcp  # API
        firewall-cmd --permanent --add-port=8765/tcp  # WebSocket
        firewall-cmd --permanent --add-port=3000/tcp  # Grafana (optional)
        firewall-cmd --reload
    elif command -v ufw &> /dev/null; then
        # UFW (Ubuntu/Debian)
        ufw allow 8080/tcp
        ufw allow 8765/tcp
        ufw allow 3000/tcp
    fi

    log_info "Firewall configured"
}

deploy_from_local() {
    log_info "Deploying from local files..."

    # Create installation directory
    mkdir -p $INSTALL_DIR

    # Copy files if running from the project directory
    if [ -f "./docker-compose.yml" ]; then
        log_info "Copying files to $INSTALL_DIR..."
        cp -r . $INSTALL_DIR/
        chown -R bullseye:bullseye $INSTALL_DIR
    else
        log_error "docker-compose.yml not found. Please run this script from the project directory."
        exit 1
    fi
}

deploy_from_git() {
    log_info "Deploying from Git repository..."

    # Install git if not present
    install_git

    # Clone repository
    if [ -d "$INSTALL_DIR/.git" ]; then
        log_info "Repository already exists, pulling latest..."
        cd $INSTALL_DIR
        sudo -u bullseye git pull
    else
        log_info "Cloning repository..."
        rm -rf $INSTALL_DIR
        sudo -u bullseye git clone -b $GIT_BRANCH $REPO_URL $INSTALL_DIR
    fi
}

setup_directories() {
    log_info "Setting up directories..."

    # Create user_data directories
    sudo -u bullseye mkdir -p $USER_DATA_DIR/{strategies,data,logs,backtest_results}
    sudo -u bullseye mkdir -p $USER_DATA_DIR/data/{crypto,stock,futures}

    # Copy example config if config doesn't exist
    if [ ! -f "$INSTALL_DIR/config.yaml" ]; then
        sudo -u bullseye cp $INSTALL_DIR/config.yaml.example $INSTALL_DIR/config.yaml
        log_warn "Config file created from example. Please edit $INSTALL_DIR/config.yaml with your settings."
    fi
}

build_docker_image() {
    log_info "Building Docker image..."
    cd $INSTALL_DIR
    sudo -u bullseye docker compose build
    log_info "Docker image built successfully"
}

start_services() {
    log_info "Starting Bullseye services..."

    cd $INSTALL_DIR

    # Start with default configuration
    sudo -u bullseye docker compose up -d

    # Wait for services to be healthy
    sleep 5

    log_info "Checking service status..."
    sudo -u bullseye docker compose ps
}

setup_systemd_service() {
    log_info "Setting up systemd service..."

    cat > /etc/systemd/system/bullseye.service << EOF
[Unit]
Description=Bullseye Quantitative Trading Framework
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0
User=bullseye
Group=bullseye

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable bullseye.service

    log_info "Systemd service created and enabled"
}

setup_logrotate() {
    log_info "Setting up log rotation..."

    cat > /etc/logrotate.d/bullseye << EOF
$USER_DATA_DIR/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 bullseye bullseye
    sharedscripts
    postrotate
        docker compose -f $INSTALL_DIR/docker-compose.yml exec bullseye kill -USR1 1 || true
    endscript
}
EOF

    log_info "Log rotation configured"
}

print_summary() {
    echo ""
    echo -e "${GREEN}================================================"
    echo "           Deployment Complete!                        "
    echo "================================================${NC}"
    echo ""
    echo -e "${BLUE}Installation Directory:${NC} $INSTALL_DIR"
    echo -e "${BLUE}User Data Directory:${NC} $USER_DATA_DIR"
    echo ""
    echo -e "${GREEN}Services:${NC}"
    echo -e "  - API Server: ${YELLOW}http://$(hostname -I | awk '{print $1}'):8080${NC}"
    echo -e "  - WebSocket: ${YELLOW}ws://$(hostname -I | awk '{print $1}'):8765${NC}"
    echo ""
    echo -e "${GREEN}Management Commands:${NC}"
    echo -e "  View logs: ${YELLOW}docker compose -f $INSTALL_DIR/docker-compose.yml logs -f${NC}"
    echo -e "  Stop: ${YELLOW}systemctl stop bullseye${NC}"
    echo -e "  Start: ${YELLOW}systemctl start bullseye${NC}"
    echo -e "  Restart: ${YELLOW}systemctl restart bullseye${NC}"
    echo ""
    echo -e "${YELLOW}IMPORTANT:${NC}"
    echo -e "  1. Edit configuration: ${YELLOW}nano $INSTALL_DIR/config.yaml${NC}"
    echo -e "  2. Add your API keys to the config file"
    echo -e "  3. Add your strategies to: ${YELLOW}$USER_DATA_DIR/strategies/${NC}"
    echo -e "  4. Restart service after config changes: ${YELLOW}systemctl restart bullseye${NC}"
    echo ""
}

# Main deployment flow
main() {
    print_banner

    # Check if running as root
    check_root

    # Detect OS
    detect_os

    # Install Docker
    if ! command -v docker &> /dev/null; then
        install_docker
    else
        log_info "Docker already installed: $(docker --version)"
    fi

    # Create user
    create_bullseye_user

    # Setup firewall
    setup_firewall

    # Deploy files
    read -p "Deploy from local files or Git? [local/git]: " deploy_source
    case $deploy_source in
        git|Git|GIT)
            deploy_from_git
            ;;
        *)
            deploy_from_local
            ;;
    esac

    # Setup directories
    setup_directories

    # Build Docker image
    build_docker_image

    # Setup systemd service
    setup_systemd_service

    # Setup logrotate
    setup_logrotate

    # Start services
    start_services

    # Print summary
    print_summary
}

# Run main function
main "$@"
