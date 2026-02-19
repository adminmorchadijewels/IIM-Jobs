#!/usr/bin/env bash
# setup.sh — one-shot environment bootstrap for IIM Jobs Agent
# Works on Debian/Ubuntu-based systems (including GitHub Codespaces).
set -e

echo "==> Installing Python dependencies ..."
pip install -r requirements.txt

echo ""
echo "==> Installing Playwright Chromium browser binary ..."
python -m playwright install chromium

echo ""
echo "==> Installing OS-level libraries required by Chromium ..."
# playwright install-deps uses apt/sudo internally; fall back to manual list
if python -m playwright install-deps chromium 2>/dev/null; then
    echo "    Done via playwright install-deps."
else
    echo "    playwright install-deps failed — trying manual apt install ..."
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
        libpango-1.0-0 \
        libcairo2 \
        libnss3 \
        libnspr4
    echo "    Done via apt."
fi

echo ""
echo "==> Setting up .env file ..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "    Created .env from .env.example"
    echo "    --> Open .env and fill in IIMJOBS_EMAIL and IIMJOBS_PASSWORD"
else
    echo "    .env already exists — skipping."
fi

echo ""
echo "============================================================"
echo "  Setup complete!  Run:  python agent.py"
echo "============================================================"
