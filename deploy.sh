#!/usr/bin/env bash
# Deploy forex-signal-bot to a VPS
# Usage: ./deploy.sh user@your-vps-ip [remote_path]
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: ./deploy.sh user@vps-ip [/path/on/vps]"
    echo "Example: ./deploy.sh root@123.45.67.89"
    echo "         ./deploy.sh ubuntu@myserver.com /home/ubuntu/bots"
    exit 1
fi

VPS="$1"
REMOTE_PATH="${2:-/root/forex-signal-bot}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo " Deploying Forex Signal Bot to $VPS"
echo " Remote path: $REMOTE_PATH"
echo "============================================"
echo ""

# Step 1: Sync files (exclude unnecessary dirs)
echo "[1/3] Syncing files..."
rsync -avz --delete \
    --exclude '__pycache__' \
    --exclude '*.egg-info' \
    --exclude '.git' \
    --exclude '*.db' \
    "$PROJECT_DIR/" "$VPS:$REMOTE_PATH/"

# Step 2: Install Docker if needed
echo ""
echo "[2/3] Ensuring Docker is installed..."
ssh "$VPS" 'bash -s' << 'DOCKER_SETUP'
    if ! command -v docker &>/dev/null; then
        echo "Installing Docker..."
        curl -fsSL https://get.docker.com | sh
        systemctl enable docker --now
    fi
    if ! command -v docker &>/dev/null; then
        echo "ERROR: Docker installation failed. Install manually: https://docs.docker.com/engine/install/"
        exit 1
    fi
    echo "Docker: $(docker --version)"
DOCKER_SETUP

# Step 3: Build and start
echo ""
echo "[3/3] Starting bot..."
ssh "$VPS" "cd $REMOTE_PATH && docker compose up -d --build"

echo ""
echo "============================================"
echo " Deploy complete!"
echo "============================================"
echo ""
echo "Check logs:    ssh $VPS 'cd $REMOTE_PATH && docker compose logs -f'"
echo "Restart bot:   ssh $VPS 'cd $REMOTE_PATH && docker compose restart'"
echo "Stop bot:      ssh $VPS 'cd $REMOTE_PATH && docker compose down'"
echo ""
