#!/usr/bin/env bash
# ==============================================================================
# Bracketman - 1-Click macOS / Linux Launcher
# Double-clickable in macOS Finder (.command) or runnable from Terminal.
# Automatically sets up .venv on first run and starts Bracketman on localhost.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================================"
echo "  Bracketman - Wrestling Tournament Manager (Localhost)"
echo "========================================================"
echo ""

# Bootstrap virtual environment if missing
if [ ! -x ".venv/bin/python" ]; then
    echo "[INFO] Virtual environment not found. Running first-time setup..."
    if [ "$(uname -s)" = "Darwin" ]; then
        ./scripts/setup_macos.sh
    else
        ./scripts/setup_fedora.sh
    fi
fi

echo "Starting Bracketman on http://localhost:8503 ..."
echo "(Keep this terminal window open while using Bracketman)"
echo ""

.venv/bin/python -m bracketman ui
