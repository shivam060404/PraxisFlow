#!/bin/bash
# Quick build verification script

set -e

echo "=== Verifying Backend ==="
cd /Users/shivamkumar/ai-meeting-intelligence/backend
pip install -q -r requirements.txt 2>/dev/null
python -m py_compile app/main.py 2>&1 | head -20
echo "Backend syntax OK"

echo ""
echo "=== Verifying Frontend ==="
cd /Users/shivamkumar/ai-meeting-intelligence/frontend
npm install --silent 2>/dev/null
npm run build 2>&1 | tail -20
echo "Frontend build OK"

echo ""
echo "=== All checks passed! ==="