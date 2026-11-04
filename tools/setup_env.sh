#!/usr/bin/env bash
# Idempotent bootstrap — safe to re-run any time (after a sandbox reset: `bash tools/setup_env.sh`).
#   1. Python deps (skipped when already importable)
#   2. autocommit watchdog (singleton via flock inside autocommit.sh)
#   3. API server under PM2 (started if not online)
set -e
cd "$(dirname "$0")/.."
python3 -c "import fastapi, pydantic_settings, ib_async, yfinance, sqlalchemy" 2>/dev/null \
  || python3 -m pip install -q -r requirements.txt 2>&1 | grep -v notice || true
setsid -f bash tools/autocommit.sh "$(pwd)" 30 > /home/user/autocommit.out 2>&1 < /dev/null
pm2 describe vmi 2>/dev/null | grep -q "online" || pm2 start ecosystem.config.cjs >/dev/null 2>&1 || true
echo "env ready"
