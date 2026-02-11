#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Helper: prompt for a value with optional default
ask() {
    local var_name="$1"
    local prompt="$2"
    local default="$3"
    local value
    if [ -n "$default" ]; then
        read -rp "  $prompt [$default]: " value
        value="${value:-$default}"
    else
        read -rp "  $prompt: " value
    fi
    eval "$var_name=\"$value\""
}

# Interactive setup when .env doesn't exist
if [ ! -f .env ]; then
    python3 setup.py
    if [ $? -ne 0 ] || [ ! -f .env ]; then
        echo -e "${RED}Setup cancelled or failed.${NC}"
        exit 1
    fi

    # Ask deployment-specific questions and append to .env
    echo -e "${YELLOW}Deployment Settings${NC}"
    ask DEPLOY_HOST "Remote host (IP or hostname)" ""
    ask DEPLOY_USER "Remote SSH user" ""
    ask DEPLOY_DIR "Remote install directory" "/home/${DEPLOY_USER}/deye-dashboard"
    ask DEPLOY_SERVICE_NAME "Systemd service name" "deye-dashboard"
    echo ""

    cat >> .env << EOF

# Deployment (used by deploy.sh)
DEPLOY_HOST=${DEPLOY_HOST}
DEPLOY_USER=${DEPLOY_USER}
DEPLOY_DIR=${DEPLOY_DIR}
DEPLOY_SERVICE_NAME=${DEPLOY_SERVICE_NAME}
EOF

    echo -e "${GREEN}Deployment settings added to .env${NC}"
    echo ""
    read -rp "Proceed with deployment? (y/n) [y]: " PROCEED
    PROCEED="${PROCEED:-y}"
    if [[ ! "$PROCEED" =~ ^[Yy]$ ]]; then
        echo "Deployment cancelled. You can edit .env and re-run ./deploy.sh"
        exit 0
    fi
    echo ""
fi

# Load configuration from .env
set -a
source .env
set +a

# Read deploy vars from environment
REMOTE_USER="${DEPLOY_USER:-}"
REMOTE_HOST="${DEPLOY_HOST:-}"
REMOTE_DIR="${DEPLOY_DIR:-/home/${REMOTE_USER}/deye-dashboard}"
SERVICE_NAME="${DEPLOY_SERVICE_NAME:-deye-dashboard}"

# Validation
MISSING=()
[ -z "$REMOTE_HOST" ] && MISSING+=("DEPLOY_HOST")
[ -z "$REMOTE_USER" ] && MISSING+=("DEPLOY_USER")
[ -z "$INVERTER_IP" ] && MISSING+=("INVERTER_IP")
[ -z "$LOGGER_SERIAL" ] && MISSING+=("LOGGER_SERIAL")

if [ "${TELEGRAM_ENABLED:-false}" = "true" ]; then
    [ -z "$TELEGRAM_BOT_TOKEN" ] && MISSING+=("TELEGRAM_BOT_TOKEN")
    if [ "${TELEGRAM_PUBLIC:-false}" != "true" ]; then
        [ -z "$TELEGRAM_ALLOWED_USERS" ] && MISSING+=("TELEGRAM_ALLOWED_USERS")
    fi
fi

if [ ${#MISSING[@]} -gt 0 ]; then
    echo -e "${RED}Error: Missing required environment variables:${NC}"
    for var in "${MISSING[@]}"; do
        echo "  - $var"
    done
    echo ""
    echo "Set them in your .env file or export them before running deploy.sh"
    echo "See .env.example for reference."
    exit 1
fi

echo -e "${GREEN}Deploying Deye Dashboard to ${REMOTE_HOST}...${NC}"

# Files to deploy
FILES=(
    "app.py"
    "inverter.py"
    "telegram_bot.py"
    "poems.py"
    "outage_providers"
    "update_manager.py"
    "requirements.txt"
    "templates"
    "discover_inverter.py"
    "check_inverter.py"
    "setup.py"
    ".env"
)

# Create remote directory if it doesn't exist
echo -e "${YELLOW}Creating remote directory...${NC}"
ssh ${REMOTE_USER}@${REMOTE_HOST} "mkdir -p ${REMOTE_DIR}"

# Copy files using rsync
echo -e "${YELLOW}Copying files...${NC}"
for file in "${FILES[@]}"; do
    if [ -e "$file" ]; then
        rsync -avz --progress "$file" ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/
    else
        echo "Warning: $file not found, skipping..."
    fi
done

# Setup git repository for OTA updates
echo -e "${YELLOW}Setting up git for OTA updates...${NC}"
ssh ${REMOTE_USER}@${REMOTE_HOST} << ENDSSH
cd ${REMOTE_DIR}

# Install git if not present
if ! command -v git &> /dev/null; then
    echo "Installing git..."
    sudo apt-get update -qq && sudo apt-get install -y -qq git
fi

# Initialize git repo if not present
if [ ! -d ".git" ]; then
    echo "Initializing git repository..."
    git init
    git remote add origin https://github.com/${GITHUB_REPO:-ivanursul/deye-dashboard}.git
    git fetch --tags
    LATEST_TAG=\$(git tag --sort=-v:refname | head -1)
    if [ -n "\$LATEST_TAG" ]; then
        echo "Checking out \$LATEST_TAG..."
        git checkout "\$LATEST_TAG"
    fi
else
    echo "Fetching latest tags..."
    git fetch --tags
fi
ENDSSH

# Setup sudoers for passwordless systemctl restart
echo -e "${YELLOW}Setting up sudoers for OTA restart...${NC}"
ssh ${REMOTE_USER}@${REMOTE_HOST} << ENDSSH
SUDOERS_FILE="/etc/sudoers.d/deye-dashboard"
if [ ! -f "\$SUDOERS_FILE" ]; then
    echo "${REMOTE_USER} ALL=(ALL) NOPASSWD: /bin/systemctl restart ${SERVICE_NAME}, /bin/systemctl is-active ${SERVICE_NAME}" | sudo tee "\$SUDOERS_FILE" > /dev/null
    sudo chmod 440 "\$SUDOERS_FILE"
    echo "Sudoers entry created for passwordless service restart"
else
    echo "Sudoers entry already exists"
fi
ENDSSH

# Setup Python environment and install dependencies
echo -e "${YELLOW}Setting up Python environment...${NC}"
ssh ${REMOTE_USER}@${REMOTE_HOST} << ENDSSH
cd ${REMOTE_DIR}

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activate and install dependencies
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
ENDSSH

# Create systemd service file
echo -e "${YELLOW}Setting up systemd service...${NC}"
ssh ${REMOTE_USER}@${REMOTE_HOST} << ENDSSH
cat > /tmp/${SERVICE_NAME}.service << EOF
[Unit]
Description=Deye Solar Dashboard
After=network.target

[Service]
Type=simple
User=${REMOTE_USER}
WorkingDirectory=${REMOTE_DIR}
Environment="PATH=${REMOTE_DIR}/venv/bin"
EnvironmentFile=${REMOTE_DIR}/.env
ExecStart=${REMOTE_DIR}/venv/bin/python app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Install service (requires sudo)
sudo mv /tmp/${SERVICE_NAME}.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl restart ${SERVICE_NAME}
ENDSSH

echo -e "${GREEN}Deployment complete!${NC}"
echo -e "Dashboard should be available at: http://${REMOTE_HOST}:8080"
echo ""
echo "Useful commands:"
echo "  Check status:  ssh ${REMOTE_USER}@${REMOTE_HOST} 'sudo systemctl status ${SERVICE_NAME}'"
echo "  View logs:     ssh ${REMOTE_USER}@${REMOTE_HOST} 'sudo journalctl -u ${SERVICE_NAME} -f'"
echo "  Restart:       ssh ${REMOTE_USER}@${REMOTE_HOST} 'sudo systemctl restart ${SERVICE_NAME}'"
