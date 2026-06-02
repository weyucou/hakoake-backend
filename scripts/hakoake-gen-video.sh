#!/usr/bin/env bash
# hakoake-gen-video.sh — Generate weekly playlist video for hakoake.
# Runs every Monday at 22:00 JST, targeting next Monday's week.
# 1. Creates the weekly playlist for next Monday
# 2. Looks up the created playlist's DB id
# 3. Generates the playlist video
# 4. Generates and uploads the YouTube Shorts version
# 5. Posts the Instagram carousel announcement
#
# Manual recovery: FORCE_DATE=2026-06-08 bash scripts/hakoake-gen-video.sh
set -euo pipefail

export PATH="/home/monkut/.local/bin:$PATH"

HAKOAKE_DIR="$HOME/projects/hakoake-backend/malcom"
LOG_DIR="$HOME/projects/hakoake-backend/logs"
mkdir -p "$LOG_DIR"

# Allow manual date override for recovery runs; default to next Monday (+7 days in JST).
if [[ -n "${FORCE_DATE:-}" ]]; then
    MONDAY="$FORCE_DATE"
else
    MONDAY=$(TZ=Asia/Tokyo date -d '+7 days' +%Y-%m-%d)
fi
LOGFILE="$LOG_DIR/hakoake-gen-video-${MONDAY}.log"

# Tee all output (stdout + stderr) to a dated log file
exec > >(tee "$LOGFILE") 2>&1

echo "Creating weekly playlist for week starting ${MONDAY}..."
cd "$HAKOAKE_DIR"
uv run python manage.py create_weekly_playlist "$MONDAY"

echo "Looking up playlist DB id for ${MONDAY}..."
playlist_db_id=$(uv run python manage.py list_weekly_playlist "$MONDAY" --json | jq -r '.id')

# Guard: skip the expensive video generation and Instagram post if this playlist was
# already announced. post_weekly_playlist has its own idempotency guard (instagram_post_id)
# but checking here avoids re-running the slow video-generation steps unnecessarily.
already_posted=$(uv run python manage.py list_weekly_playlist "$MONDAY" --json | jq -r '.instagram_post_id // empty')
if [[ -n "$already_posted" ]]; then
    echo "Playlist ${playlist_db_id} (${MONDAY}) already posted to Instagram (post_id=${already_posted}); skipping."
    exit 0
fi

echo "Generating weekly playlist video for playlist id=${playlist_db_id}..."
uv run python manage.py generate_weekly_playlist_video "$playlist_db_id"

echo "Generating and uploading YouTube Shorts for playlist id=${playlist_db_id}..."
uv run python manage.py generate_weekly_playlist_video "$playlist_db_id" --format shorts

echo "Posting Instagram Story for playlist id=${playlist_db_id}..."
uv run python manage.py generate_weekly_playlist_video "$playlist_db_id" --format story

echo "Posting weekly playlist announcement to Instagram..."
uv run python manage.py post_weekly_playlist --playlist-id="$playlist_db_id"

echo "Done."
