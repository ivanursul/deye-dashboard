#!/bin/bash
set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

LINES=200

usage() {
    echo "Usage: ./download_logs.sh [-n LINES]"
    echo ""
    echo "Download service logs from the remote server."
    echo ""
    echo "Options:"
    echo "  -n LINES   Number of lines to fetch (default: $LINES)"
    echo "  -h         Show this help"
    echo ""
    echo "Reads DEPLOY_HOST, DEPLOY_USER, and DEPLOY_SERVICE_NAME from .env"
}

while getopts "n:h" opt; do
    case "$opt" in
        n) LINES="$OPTARG" ;;
        h) usage; exit 0 ;;
        *) usage; exit 1 ;;
    esac
done

# Load .env
if [ ! -f .env ]; then
    echo -e "${RED}Error: No .env file found. Run ./deploy.sh first to generate one.${NC}"
    exit 1
fi

set -a
source .env
set +a

REMOTE_USER="${DEPLOY_USER:-}"
REMOTE_HOST="${DEPLOY_HOST:-}"
SERVICE_NAME="${DEPLOY_SERVICE_NAME:-deye-dashboard}"

if [ -z "$REMOTE_HOST" ] || [ -z "$REMOTE_USER" ]; then
    echo -e "${RED}Error: DEPLOY_HOST and DEPLOY_USER must be set in .env${NC}"
    exit 1
fi

# Create logs directory
mkdir -p logs

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTFILE="logs/${SERVICE_NAME}_${TIMESTAMP}.log"

echo -e "${YELLOW}Fetching last ${LINES} lines from ${SERVICE_NAME} on ${REMOTE_HOST}...${NC}"

ssh "${REMOTE_USER}@${REMOTE_HOST}" \
    "sudo journalctl -u ${SERVICE_NAME} --no-pager -n ${LINES}" \
    > "$OUTFILE"

LINE_COUNT=$(wc -l < "$OUTFILE")
echo -e "${GREEN}Saved ${LINE_COUNT} lines to ${OUTFILE}${NC}"
