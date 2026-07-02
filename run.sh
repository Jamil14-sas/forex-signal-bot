#!/usr/bin/env bash
set -euo pipefail

echo "========================================="
echo "  Forex Signal Bot — Setup & Run"
echo "========================================="
echo ""

cd "$(dirname "$0")"

# Check for Docker
if command -v docker &>/dev/null; then
    echo "[✓] Docker found"
    echo ""
    echo "Starting bot with Docker..."
    docker compose up -d --build
    echo ""
    echo "Bot is running! Check logs with: docker compose logs -f"
    exit 0
fi

# Fallback: Python 3.12 local install
PYTHON=$(command -v python3.12 || command -v python3 || echo "")
if [ -z "$PYTHON" ]; then
    echo "[✗] Neither Docker nor Python 3.12 found."
    echo "    Install Docker: https://docs.docker.com/get-docker/"
    echo "    Or Python 3.12: https://www.python.org/downloads/"
    exit 1
fi

PYVER=$("$PYTHON" --version 2>&1 | awk '{print $2}')
echo "[✓] Using $PYTHON ($PYVER)"

if [ ! -f .env ]; then
    echo "[✗] .env file not found. Copy .env.example to .env and fill in your tokens."
    exit 1
fi

echo "Installing dependencies..."
"$PYTHON" -m pip install -e . -q

echo ""
echo "Starting bot..."
"$PYTHON" -m forex_signal.main
