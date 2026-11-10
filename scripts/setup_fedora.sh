#!/usr/bin/env bash
# ==============================================================================
# Bracketman - Fedora Linux Automated Setup Script
# Configures Python virtual environment, dependencies, and verifies localhost readiness.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

echo "=========================================================="
echo "  Bracketman - Fedora Linux Localhost Deployment Setup   "
echo "=========================================================="

# 1. Check OS
if [ -f /etc/fedora-release ]; then
    echo "✔ Detected Fedora: $(cat /etc/fedora-release)"
elif [ -f /etc/os-release ]; then
    echo "ℹ OS: $(grep -E '^PRETTY_NAME=' /etc/os-release | cut -d= -f2 | tr -d '\"')"
fi

# 2. Check for python3
if ! command -v python3 &> /dev/null; then
    echo "❌ python3 not found."
    echo "👉 Please run: sudo dnf install -y python3 python3-pip git curl"
    exit 1
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "✔ Found Python $PY_VER"

python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"' || {
    echo "❌ Python 3.10 or higher is required. Found Python $PY_VER."
    exit 1
}

# 3. Create virtual environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment at .venv..."
    python3 -m venv .venv
else
    echo "✔ Existing .venv directory found."
fi

# 4. Activate and install dependencies
echo "⬇ Installing Bracketman and dependencies..."
.venv/bin/pip install --upgrade pip setuptools
.venv/bin/pip install -e ".[dev]"

# 5. Ensure required runtime directories exist
mkdir -p data/tournaments output .streamlit

# 6. Verify or generate example tournament
if [ ! -f "data/example_tournament.xlsx" ]; then
    echo "📝 Generating default synthetic tournament spreadsheet..."
    .venv/bin/python scripts/generate_example_tournament.py
fi

# 7. Run automated test suite
echo "🧪 Running pytest suite to verify installation..."
.venv/bin/pytest -v

echo ""
echo "=========================================================="
echo "✔ Setup complete! Bracketman is ready to run on localhost."
echo "=========================================================="
echo ""
echo "To start Bracketman immediately:"
echo "  source .venv/bin/activate"
echo "  bracketman ui"
echo ""
echo "Then navigate to: http://127.0.0.1:8503 (or http://localhost:8503)"
echo ""
echo "To run in the background as a systemd user service (no sudo required):"
echo "  mkdir -p ~/.config/systemd/user"
echo "  cp systemd/bracketman.service ~/.config/systemd/user/"
echo "  systemctl --user daemon-reload"
echo "  systemctl --user enable --now bracketman"
echo "=========================================================="
