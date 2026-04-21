#!/usr/bin/env bash
# hakoake-fetch-performer-images.sh — Backfill missing performer images nightly.
# Runs fetch_performer_images --missing-only so new performers have artwork
# before the Monday post_weekly_playlist run (hakoake-gen-video.sh, 22:00 JST).
set -euo pipefail

export PATH="/home/monkut/.local/bin:$PATH"

HAKOAKE_DIR="$HOME/projects/hakoake-backend/malcom"
LOG_DIR="$HOME/projects/hakoake-backend/logs"
mkdir -p "$LOG_DIR"

TODAY=$(TZ=Asia/Tokyo date +%Y-%m-%d)
LOGFILE="$LOG_DIR/hakoake-fetch-performer-images-${TODAY}.log"

# Tee all output (stdout + stderr) to a dated log file
exec > >(tee "$LOGFILE") 2>&1

cd "$HAKOAKE_DIR"

echo "Fetching missing performer images..."
uv run python manage.py fetch_performer_images --missing-only

echo "Done."
