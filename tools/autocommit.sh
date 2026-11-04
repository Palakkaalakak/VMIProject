#!/usr/bin/env bash
# Autocommit watchdog: commits + pushes every INTERVAL seconds. Survives git lock files and push failures.
# Keeps committing locally and retries push each cycle (e.g. while GitHub is disconnected).
REPO_DIR="${1:-/home/user/webapp}"
INTERVAL="${2:-30}"
LOG=/home/user/autocommit.log
cd "$REPO_DIR" || exit 1
# Singleton: a second copy exits immediately (flock on a lock file held for the process lifetime).
exec 9>/home/user/.autocommit.lock
flock -n 9 || { echo "autocommit already running"; exit 0; }
while true; do
  # stale lock from a killed git process blocks every future commit — clear it if older than 60s
  if [ -f .git/index.lock ] && [ $(( $(date +%s) - $(stat -c %Y .git/index.lock) )) -gt 60 ]; then rm -f .git/index.lock; fi
  if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    git add -A >/dev/null 2>&1 && git commit -q -m "autosave: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null 2>&1
  fi
  if [ -n "$(git log origin/main..main --oneline 2>/dev/null)" ]; then
    timeout 60 git push -q origin main >/dev/null 2>&1 || echo "$(date -u) push failed, will retry" >> "$LOG"
  fi
  sleep "$INTERVAL"
done
