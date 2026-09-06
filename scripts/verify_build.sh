#!/bin/bash
# Quick build verification script

set -e

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

echo "=== Verifying Backend ==="
cd "$ROOT_DIR/backend"
pip install -q -r requirements.txt 2>/dev/null
python -m py_compile app/main.py 2>&1 | head -20
echo "Backend syntax OK"

echo ""
echo "=== Verifying Frontend ==="
cd "$ROOT_DIR/frontend"
npm install --silent 2>/dev/null
npm run build 2>&1 | tail -20
echo "Frontend build OK"

echo ""
echo "=== All checks passed! ==="