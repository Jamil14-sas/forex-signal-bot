#!/usr/bin/env bash
# Manual deploy: tar the project, scp it, extract and run on VPS
# Usage: ./deploy-manual.sh user@vps-ip
set -euo pipefail

VPS="${1:?Usage: ./deploy-manual.sh user@vps-ip}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
TARBALL="/tmp/${PROJECT_NAME}.tar.gz"

echo "Packaging project..."
cd "$(dirname "$PROJECT_DIR")"
tar czf "$TARBALL" \
    --exclude='__pycache__' \
    --exclude='*.egg-info' \
    --exclude='.git' \
    --exclude='*.db' \
    "$PROJECT_NAME"

echo "Copying to VPS..."
scp "$TARBALL" "$VPS:/tmp/"

echo "Extracting and starting on VPS..."
ssh "$VPS" "
    cd /root
    tar xzf /tmp/${PROJECT_NAME}.tar.gz
    cd ${PROJECT_NAME}
    chmod +x run.sh
    if ! command -v docker &>/dev/null; then
        curl -fsSL https://get.docker.com | sh
    fi
    docker compose up -d --build
    echo 'Done! Check: docker compose logs -f'
"

rm -f "$TARBALL"
echo "Deployed!"
