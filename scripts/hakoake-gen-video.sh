#!/usr/bin/env bash
# hakoake-gen-video.sh — Generate weekly playlist video for hakoake.
# Runs every Monday at 22:00 JST, targeting next Monday's week.
# 1. Creates the weekly playlist for next Monday
# 2. Looks up the created playlist's DB id
# 3. Generates the playlist video
# 4. Posts the Instagram carousel announcement
set -euo pipefail

export PATH="/home/monkut/.local/bin:$PATH"

HAKOAKE_DIR="$HOME/projects/hakoake-backend/malcom"
LOG_DIR="$HOME/projects/hakoake-backend/logs"
mkdir -p "$LOG_DIR"

# Get next Monday's date in JST (today + 7 days) — target the upcoming week
MONDAY=$(TZ=Asia/Tokyo date -d '+7 days' +%Y-%m-%d)
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

echo "Posting weekly playlist announcement to Instagram..."
uv run python manage.py post_weekly_playlist --playlist-id="$playlist_db_id"

echo "Done."
