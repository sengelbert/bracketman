#!/usr/bin/env bash
# ==============================================================================
# Bracketman - macOS Automated Setup Script
# Configures Python virtual environment, dependencies, and verifies localhost readiness.
# Supports both Apple Silicon (/opt/homebrew) and Intel (/usr/local) Macs.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

echo "=========================================================="
echo "   Bracketman - macOS Localhost Deployment Setup          "
echo "=========================================================="

# 1. Locate Python 3.10+ (prefer Homebrew or python.org over macOS system Xcode Python 3.9)
PYTHON_BIN=""
for candidate in \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3" \
    "$(command -v python3 || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
        if "$candidate" -c 'import sys; assert sys.version_info >= (3, 10)' &> /dev/null; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Python 3.10+ not found (macOS default Xcode Python is 3.9, which is too old)."
    echo "👉 Install Python 3.10+ via Homebrew:"
    echo "   brew install python"
    echo "   OR download the macOS installer from https://www.python.org/downloads/macos/"
    exit 1
fi

PY_VER="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "✔ Found Python $PY_VER ($PYTHON_BIN)"

# 2. Create virtual environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment at .venv..."
    "$PYTHON_BIN" -m venv .venv
else
    echo "✔ Existing .venv directory found."
fi

# 3. Upgrade pip and install package
echo "⬇ Installing Bracketman and dependencies..."
.venv/bin/pip install --upgrade pip setuptools
.venv/bin/pip install -e ".[dev]"

# 4. Ensure runtime directories exist
mkdir -p data/tournaments output .streamlit

# 5. Verify or generate example tournament
if [ ! -f "data/example_tournament.xlsx" ]; then
    echo "📝 Generating default synthetic tournament spreadsheet..."
    .venv/bin/python scripts/generate_example_tournament.py
fi

# 6. Run automated test suite
echo "🧪 Running pytest suite to verify installation..."
.venv/bin/pytest -v

echo ""
echo "=========================================================="
echo "✔ Setup complete! Bracketman is ready to run on macOS."
echo "=========================================================="
echo ""
echo "To start Bracketman:"
echo "  Double-click 'run_bracketman.command' in Finder"
echo "  OR run in Terminal:"
echo "  source .venv/bin/activate"
echo "  bracketman ui"
echo ""
echo "Browser will open automatically to: http://127.0.0.1:8503"
echo "=========================================================="
