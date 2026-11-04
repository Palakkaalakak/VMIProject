#!/usr/bin/env bash
# Immediate commit + push (used after every significant write, in addition to the watchdog).
cd "$(dirname "$0")/.." || exit 1
rm -f .git/index.lock 2>/dev/null
git add -A && git commit -q -m "${1:-save: $(date -u +%H:%M:%S)}" 2>/dev/null
timeout 60 git push -q origin main 2>&1 | tail -1
pgrep -f "tools/autocommit.sh" >/dev/null || setsid -f tools/autocommit.sh "$(pwd)" 30 > /dev/null 2>&1 < /dev/null
echo "saved $(git log --oneline -1)"
