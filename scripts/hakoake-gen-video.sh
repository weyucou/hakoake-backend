#!/usr/bin/env bash
# hakoake-gen-video.sh — Generate weekly playlist video for hakoake.
# Runs every Monday at 22:00 JST.
# 1. Creates the weekly playlist for the current Monday
# 2. Looks up the created playlist's DB id
# 3. Generates the playlist video
set -euo pipefail

export PATH="/home/monkut/.local/bin:$PATH"

HAKOAKE_DIR="$HOME/projects/hakoake-backend/malcom"
LOG_DIR="$HOME/projects/hakoake-backend/logs"
mkdir -p "$LOG_DIR"

# Get Monday date in JST (the day this script runs)
MONDAY=$(TZ=Asia/Tokyo date +%Y-%m-%d)
LOGFILE="$LOG_DIR/hakoake-gen-video-${MONDAY}.log"

# Tee all output (stdout + stderr) to a dated log file
exec > >(tee "$LOGFILE") 2>&1

echo "Creating weekly playlist for week starting ${MONDAY}..."
cd "$HAKOAKE_DIR"
uv run python manage.py create_weekly_playlist "$MONDAY"

echo "Looking up playlist DB id for ${MONDAY}..."
playlist_db_id=$(uv run python manage.py list_weekly_playlist "$MONDAY" --json | jq -r '.id')

echo "Generating weekly playlist video for playlist id=${playlist_db_id}..."
uv run python manage.py generate_weekly_playlist_video "$playlist_db_id"

echo "Done."
