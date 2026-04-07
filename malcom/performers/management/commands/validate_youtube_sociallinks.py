import datetime
import logging
import time
from pathlib import Path

from commons.youtube_utils import get_authorized_youtube_client, parse_iso8601_duration
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from performers.models import PerformerSocialLink
from performers.normalization import channel_name_matches

logger = logging.getLogger(__name__)

YOUTUBE_READONLY_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
BATCH_SIZE = 50
VIDEO_COUNT_THRESHOLD = 10


def name_matches(performer_name: str, channel_title: str, channel_description: str) -> bool:
    """Check if performer name matches channel title or description."""
    return channel_name_matches(performer_name, channel_title, channel_description)


class Command(BaseCommand):
    help = "Validate unverified YouTube social links by checking channel name match and video count"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--secrets-file",
            type=str,
            default="../client_secret.json",
            help="Path to Google OAuth secrets file",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show validation results without verifying",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit number of links to process (0 = no limit)",
        )
        parser.add_argument(
            "--min-videos",
            type=int,
            default=3,
            help="Minimum number of videos over 1 minute (default: 3)",
        )
        parser.add_argument(
            "--re-verify",
            action="store_true",
            help="Re-validate already verified links (default: only unverified)",
        )
        parser.add_argument(
            "--created-before",
            type=str,
            default=None,
            help="Only process links created before this date (YYYY-MM-DD or YYYY-MM)",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003, C901, PLR0912, PLR0915
        secrets_file = Path(options["secrets_file"])
        dry_run = options["dry_run"]
        limit = options["limit"]
        min_videos = options["min_videos"]
        re_verify = options["re_verify"]
        created_before = options["created_before"]

        if not secrets_file.exists():
            self.stderr.write(self.style.ERROR(f"Secrets file not found: {secrets_file}"))
            return

        # Build queryset
        qs = PerformerSocialLink.objects.filter(platform="youtube")
        if not re_verify:
            qs = qs.filter(verified_datetime__isnull=True)

        if created_before:
            try:
                if len(created_before) == len("YYYY-MM"):  # noqa: PLR2004
                    cutoff = datetime.datetime.strptime(created_before, "%Y-%m").replace(  # noqa: DTZ007
                        day=1, tzinfo=datetime.UTC
                    )
                else:
                    cutoff = datetime.datetime.strptime(created_before, "%Y-%m-%d").replace(  # noqa: DTZ007
                        tzinfo=datetime.UTC
                    )
            except ValueError:
                self.stderr.write(self.style.ERROR("Invalid date format. Use YYYY-MM-DD or YYYY-MM"))
                return
            qs = qs.filter(created_datetime__lt=cutoff)
            self.stdout.write(f"Filtering links created before {cutoff.strftime('%Y-%m-%d')}")

        unverified = qs.select_related("performer").order_by("performer__name")

        if limit > 0:
            unverified = unverified[:limit]

        links = list(unverified)
        total = len(links)
        label = "YouTube links" if re_verify else "unverified YouTube links"
        self.stdout.write(f"Found {total} {label} to validate")

        if total == 0:
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made\n"))

        youtube = get_authorized_youtube_client(secrets_file, scopes=YOUTUBE_READONLY_SCOPES)

        # Separate links by platform_id type
        uc_links = []  # (link, channel_id) for UC* channel IDs
        handle_links = []  # (link, handle) for @ handles
        unknown_links = []

        for link in links:
            pid = link.platform_id
            if pid.startswith("UC"):
                uc_links.append((link, pid))
            elif pid.startswith("@"):
                handle_links.append((link, pid))
            else:
                unknown_links.append(link)

        if unknown_links:
            self.stdout.write(
                self.style.WARNING(f"Skipping {len(unknown_links)} links with unknown platform_id format")
            )

        # Phase 1: Batch fetch channel info for UC* IDs
        self.stdout.write(f"\nFetching channel info for {len(uc_links)} UC channels...")
        channel_info = self._batch_fetch_channels(youtube, [cid for _, cid in uc_links])

        # Phase 1b: Resolve @ handles to channel IDs
        if handle_links:
            self.stdout.write(f"Resolving {len(handle_links)} @ handles...")
            for link, handle in handle_links:
                info = self._fetch_handle_channel(youtube, handle)
                if info:
                    channel_id = info.pop("_channel_id")
                    channel_info[channel_id] = info
                    uc_links.append((link, channel_id))
                else:
                    unknown_links.append(link)
                time.sleep(0.2)

        # Phase 2: Validate each link
        valid = []
        invalid_name = []
        invalid_videos = []
        not_found = []

        self.stdout.write(f"\nValidating {len(uc_links)} links...")
        for link, channel_id in uc_links:
            performer_name = link.performer.name
            info = channel_info.get(channel_id)

            if not info:
                not_found.append((link, "Channel not found via API"))
                continue

            # Check name match
            if not name_matches(performer_name, info["title"], info["description"]):
                invalid_name.append((link, info["title"], info["description"][:80]))
                continue

            # Quick video count check
            if info["video_count"] < min_videos:
                invalid_videos.append((link, info["title"], info["video_count"], info["video_count"]))
                continue

            # For channels with fewer total videos, verify durations
            if info["video_count"] < VIDEO_COUNT_THRESHOLD:
                long_count = self._count_long_videos(youtube, info["uploads_playlist_id"], min_count=min_videos)
                if long_count < min_videos:
                    invalid_videos.append((link, info["title"], info["video_count"], long_count))
                    continue

            valid.append((link, info["title"]))

        # Phase 3: Report results
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write("VALIDATION RESULTS")
        self.stdout.write(f"{'=' * 60}")

        self.stdout.write(self.style.SUCCESS(f"\nVALID ({len(valid)}):"))
        for link, title in valid:
            self.stdout.write(f"  ✓ {link.performer.id} {link.performer.name} -> {title}")

        if invalid_name:
            self.stdout.write(self.style.ERROR(f"\nNAME MISMATCH ({len(invalid_name)}):"))
            for link, title, _desc in invalid_name:
                self.stdout.write(f"  ✗ {link.performer.id} {link.performer.name} -> channel: {title}")

        if invalid_videos:
            self.stdout.write(self.style.WARNING(f"\nINSUFFICIENT VIDEOS ({len(invalid_videos)}):"))
            for link, title, total_count, long_count in invalid_videos:
                self.stdout.write(
                    f"  ! {link.performer.id} {link.performer.name} -> {title}"
                    f" (total: {total_count}, >1min: {long_count})"
                )

        if not_found:
            self.stdout.write(self.style.ERROR(f"\nNOT FOUND ({len(not_found)}):"))
            for link, reason in not_found:
                self.stdout.write(f"  ? {link.performer.id} {link.performer.name} ({link.platform_id}): {reason}")

        if unknown_links:
            self.stdout.write(self.style.WARNING(f"\nUNKNOWN FORMAT ({len(unknown_links)}):"))
            for link in unknown_links:
                self.stdout.write(f"  ? {link.performer.id} {link.performer.name} ({link.platform_id})")

        # Phase 4: Auto-verify valid links and unverify failed ones
        failed_links = [link for link, *_ in invalid_name + invalid_videos + not_found]
        if not dry_run and valid:
            now = timezone.now()
            for link, _ in valid:
                link.verified_datetime = now
                link.save()
            self.stdout.write(self.style.SUCCESS(f"\nVerified {len(valid)} links"))
        elif dry_run and valid:
            self.stdout.write(f"\nDRY RUN: Would verify {len(valid)} links")

        if re_verify and failed_links:
            previously_verified = [link for link in failed_links if link.verified_datetime is not None]
            if not dry_run and previously_verified:
                for link in previously_verified:
                    link.verified_datetime = None
                    link.save()
                self.stdout.write(
                    self.style.WARNING(f"Unverified {len(previously_verified)} previously verified links")
                )
            elif dry_run and previously_verified:
                self.stdout.write(f"DRY RUN: Would unverify {len(previously_verified)} previously verified links")

        self.stdout.write(
            f"\nSummary: {len(valid)} valid, {len(invalid_name)} name mismatch, "
            f"{len(invalid_videos)} insufficient videos, {len(not_found)} not found, "
            f"{len(unknown_links)} unknown format"
        )

    def _batch_fetch_channels(self, youtube, channel_ids: list[str]) -> dict:  # noqa: ANN001
        """Batch fetch channel info for UC* channel IDs."""
        channel_info = {}

        for i in range(0, len(channel_ids), BATCH_SIZE):
            batch = channel_ids[i : i + BATCH_SIZE]
            try:
                response = (
                    youtube.channels()
                    .list(
                        part="snippet,statistics,contentDetails",
                        id=",".join(batch),
                    )
                    .execute()
                )

                for item in response.get("items", []):
                    cid = item["id"]
                    snippet = item.get("snippet", {})
                    stats = item.get("statistics", {})
                    content = item.get("contentDetails", {})
                    channel_info[cid] = {
                        "title": snippet.get("title", ""),
                        "description": snippet.get("description", ""),
                        "video_count": int(stats.get("videoCount", 0)),
                        "uploads_playlist_id": content.get("relatedPlaylists", {}).get("uploads", ""),
                    }
            except Exception as e:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"  API error for batch {i // BATCH_SIZE + 1}: {e}"))

            if i + BATCH_SIZE < len(channel_ids):
                time.sleep(0.5)

            self.stdout.write(f"  Fetched {min(i + BATCH_SIZE, len(channel_ids))}/{len(channel_ids)} channels")

        return channel_info

    def _fetch_handle_channel(self, youtube, handle: str) -> dict | None:  # noqa: ANN001
        """Fetch channel info for an @ handle."""
        try:
            response = (
                youtube.channels()
                .list(
                    part="snippet,statistics,contentDetails",
                    forHandle=handle.lstrip("@"),
                )
                .execute()
            )

            items = response.get("items", [])
            if not items:
                return None

            item = items[0]
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})
            return {
                "_channel_id": item["id"],
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "video_count": int(stats.get("videoCount", 0)),
                "uploads_playlist_id": content.get("relatedPlaylists", {}).get("uploads", ""),
            }
        except Exception as e:  # noqa: BLE001
            self.stderr.write(self.style.ERROR(f"  API error for handle {handle}: {e}"))
            return None

    def _count_long_videos(self, youtube, uploads_playlist_id: str, min_count: int = 3) -> int:  # noqa: ANN001
        """Count videos over 60 seconds in the uploads playlist."""
        if not uploads_playlist_id:
            return 0

        try:
            response = (
                youtube.playlistItems()
                .list(
                    part="contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=20,
                )
                .execute()
            )

            video_ids = [item["contentDetails"]["videoId"] for item in response.get("items", [])]
            if not video_ids:
                return 0

            vid_response = (
                youtube.videos()
                .list(
                    part="contentDetails",
                    id=",".join(video_ids),
                )
                .execute()
            )

            long_count = 0
            for item in vid_response.get("items", []):
                duration = item.get("contentDetails", {}).get("duration", "PT0S")
                seconds = parse_iso8601_duration(duration)
                if seconds > 60:  # noqa: PLR2004
                    long_count += 1
                    if long_count >= min_count:
                        return long_count
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Error checking videos for playlist {uploads_playlist_id}: {e}")
            return 0
        else:
            return long_count
