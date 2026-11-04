#!/usr/bin/env bash
# Idempotent environment bootstrap (re-run after any sandbox reset).
set -e
cd "$(dirname "$0")/.."
python3 -m pip install -q -r requirements.txt 2>&1 | grep -v "notice" || true
pgrep -f "tools/autocommit.sh" >/dev/null || setsid -f tools/autocommit.sh "$(pwd)" 40 > /tmp/autocommit.out 2>&1 < /dev/null
echo "env ready"
