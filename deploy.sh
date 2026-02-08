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
    echo ""
    echo -e "${CYAN}${BOLD}========================================${NC}"
    echo -e "${CYAN}${BOLD}  Deye Dashboard — First-Time Setup${NC}"
    echo -e "${CYAN}${BOLD}========================================${NC}"
    echo ""
    echo "No .env file found. Let's configure your deployment."
    echo "Press Enter to accept defaults shown in [brackets]."
    echo ""

    # --- Inverter ---
    echo -e "${YELLOW}Inverter Settings${NC}"
    ask INVERTER_IP "Inverter IP address" ""
    ask LOGGER_SERIAL "Logger serial number" ""
    echo ""

    # --- Deployment ---
    echo -e "${YELLOW}Deployment Settings${NC}"
    ask DEPLOY_HOST "Remote host (IP or hostname)" ""
    ask DEPLOY_USER "Remote SSH user" ""
    ask DEPLOY_DIR "Remote install directory" "/home/${DEPLOY_USER}/deye-dashboard"
    ask DEPLOY_SERVICE_NAME "Systemd service name" "deye-dashboard"
    echo ""

    # --- Weather ---
    echo -e "${YELLOW}Weather Settings (Open-Meteo API)${NC}"
    ask WEATHER_LATITUDE "Latitude" "50.4501"
    ask WEATHER_LONGITUDE "Longitude" "30.5234"
    echo ""

    # --- Outage Provider ---
    echo -e "${YELLOW}Outage Schedule Provider${NC}"
    echo "  1) lvivoblenergo"
    echo "  2) yasno"
    echo "  3) none (disable)"
    read -rp "  Choose [1]: " OUTAGE_CHOICE
    OUTAGE_CHOICE="${OUTAGE_CHOICE:-1}"

    case "$OUTAGE_CHOICE" in
        1)
            OUTAGE_PROVIDER="lvivoblenergo"
            ask OUTAGE_GROUP "Outage group (e.g. 1.1)" "1.1"
            ;;
        2)
            OUTAGE_PROVIDER="yasno"
            ask OUTAGE_REGION_ID "YASNO region ID (e.g. 25 = Kyiv)" "25"
            ask OUTAGE_DSO_ID "YASNO DSO ID (e.g. 902 = DTEK Kyiv)" "902"
            ask OUTAGE_GROUP "Queue/group number (e.g. 2.1)" "2.1"
            ;;
        3)
            OUTAGE_PROVIDER="none"
            ;;
        *)
            echo -e "${RED}Invalid choice, defaulting to lvivoblenergo${NC}"
            OUTAGE_PROVIDER="lvivoblenergo"
            ask OUTAGE_GROUP "Outage group (e.g. 1.1)" "1.1"
            ;;
    esac
    echo ""

    # --- Telegram ---
    echo -e "${YELLOW}Telegram Bot (optional)${NC}"
    read -rp "  Enable Telegram bot? (y/n) [n]: " TELEGRAM_CHOICE
    TELEGRAM_CHOICE="${TELEGRAM_CHOICE:-n}"

    if [[ "$TELEGRAM_CHOICE" =~ ^[Yy]$ ]]; then
        TELEGRAM_ENABLED="true"
        ask TELEGRAM_BOT_TOKEN "Bot token" ""
        ask TELEGRAM_ALLOWED_USERS "Allowed user IDs (comma-separated)" ""
    else
        TELEGRAM_ENABLED="false"
    fi
    echo ""

    # --- Write .env ---
    echo -e "${YELLOW}Writing .env file...${NC}"
    cat > .env << EOF
# Deye Inverter Configuration
INVERTER_IP=${INVERTER_IP}
LOGGER_SERIAL=${LOGGER_SERIAL}

# Weather (coordinates for Open-Meteo API)
WEATHER_LATITUDE=${WEATHER_LATITUDE}
WEATHER_LONGITUDE=${WEATHER_LONGITUDE}

# Outage Schedule Provider
OUTAGE_PROVIDER=${OUTAGE_PROVIDER}
EOF

    # Add provider-specific vars
    if [ "$OUTAGE_PROVIDER" = "yasno" ]; then
        cat >> .env << EOF
OUTAGE_REGION_ID=${OUTAGE_REGION_ID}
OUTAGE_DSO_ID=${OUTAGE_DSO_ID}
OUTAGE_GROUP=${OUTAGE_GROUP}
EOF
    elif [ "$OUTAGE_PROVIDER" = "lvivoblenergo" ]; then
        cat >> .env << EOF
OUTAGE_GROUP=${OUTAGE_GROUP}
EOF
    fi

    cat >> .env << EOF

# Telegram Bot
TELEGRAM_ENABLED=${TELEGRAM_ENABLED}
EOF

    if [ "$TELEGRAM_ENABLED" = "true" ]; then
        cat >> .env << EOF
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
TELEGRAM_ALLOWED_USERS=${TELEGRAM_ALLOWED_USERS}
EOF
    fi

    cat >> .env << EOF

# Deployment (used by deploy.sh)
DEPLOY_HOST=${DEPLOY_HOST}
DEPLOY_USER=${DEPLOY_USER}
DEPLOY_DIR=${DEPLOY_DIR}
DEPLOY_SERVICE_NAME=${DEPLOY_SERVICE_NAME}
EOF

    echo -e "${GREEN}.env file created successfully!${NC}"
    echo ""
    echo -e "${CYAN}Summary:${NC}"
    echo "  Inverter:  ${INVERTER_IP} (serial: ${LOGGER_SERIAL})"
    echo "  Deploy to: ${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_DIR}"
    echo "  Weather:   ${WEATHER_LATITUDE}, ${WEATHER_LONGITUDE}"
    echo "  Outage:    ${OUTAGE_PROVIDER}"
    echo "  Telegram:  ${TELEGRAM_ENABLED}"
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
    [ -z "$TELEGRAM_ALLOWED_USERS" ] && MISSING+=("TELEGRAM_ALLOWED_USERS")
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
    "requirements.txt"
    "templates"
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
