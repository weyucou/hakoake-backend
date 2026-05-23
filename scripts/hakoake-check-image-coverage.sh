#!/usr/bin/env bash
# hakoake-check-image-coverage.sh — Alert when performer/event image coverage
# drops below threshold. Runs after the nightly fetch_performer_images backfill
# so missing coverage indicates the scraper itself is failing rather than a
# normal nightly catch-up window. Exit code 2 (EXIT_BELOW_THRESHOLD) triggers
# cron's mail-on-failure (or any wrapping alerting hook).
set -euo pipefail

export PATH="/home/monkut/.local/bin:$PATH"

HAKOAKE_DIR="$HOME/projects/hakoake-backend/malcom"
LOG_DIR="$HOME/projects/hakoake-backend/logs"
mkdir -p "$LOG_DIR"

TODAY=$(TZ=Asia/Tokyo date +%Y-%m-%d)
LOGFILE="$LOG_DIR/hakoake-check-image-coverage-${TODAY}.log"

exec > >(tee "$LOGFILE") 2>&1

cd "$HAKOAKE_DIR"

echo "Checking image coverage for the upcoming week..."
uv run python manage.py check_image_coverage --format text
