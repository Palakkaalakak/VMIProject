#!/usr/bin/env bash
# Autocommit watchdog: commits + pushes every INTERVAL seconds.
# If push fails (e.g. GitHub disconnected), keeps committing locally and retries push each cycle.
REPO_DIR="${1:-/home/user/webapp}"
INTERVAL="${2:-45}"
cd "$REPO_DIR" || exit 1
while true; do
  if [ -n "$(git status --porcelain)" ]; then
    git add -A >/dev/null 2>&1
    git commit -q -m "autosave: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null 2>&1
  fi
  if [ -n "$(git log origin/main..main --oneline 2>/dev/null)" ] || ! git rev-parse origin/main >/dev/null 2>&1; then
    timeout 60 git push -q origin main >/dev/null 2>&1 || echo "$(date -u) push failed, will retry" >> /tmp/autocommit.log
  fi
  sleep "$INTERVAL"
done
