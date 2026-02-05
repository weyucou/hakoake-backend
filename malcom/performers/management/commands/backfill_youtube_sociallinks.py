import logging
import pickle
from pathlib import Path

import google_auth_oauthlib.flow
import googleapiclient.discovery
from django.core.management.base import BaseCommand, CommandParser
from google.auth.transport.requests import Request

from performers.models import Performer, PerformerSocialLink, PerformerSong

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


def get_youtube_client(client_secrets_file: Path):
    """Get an authorized YouTube API client."""
    api_service_name = "youtube"
    api_version = "v3"

    token_cache_file = client_secrets_file.parent / "token.pickle"

    credentials = None

    if token_cache_file.exists():
        try:
            credentials = pickle.loads(token_cache_file.read_bytes())  # noqa: S301
        except Exception:  # noqa: BLE001
            credentials = None

    if credentials and not credentials.valid and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except Exception:  # noqa: BLE001
            credentials = None

    if not credentials or not credentials.valid:
        flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), SCOPES)
        credentials = flow.run_local_server(port=0)
        token_cache_file.write_bytes(pickle.dumps(credentials))

    return googleapiclient.discovery.build(api_service_name, api_version, credentials=credentials)


class Command(BaseCommand):
    help = "Backfill PerformerSocialLink entries from existing PerformerSong YouTube data"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--secrets-file",
            type=str,
            default="../client_secret.json",
            help="Path to Google OAuth secrets file (default: ../client_secret.json)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without making changes",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit number of performers to process (0 = no limit)",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003, C901, PLR0912, PLR0915
        secrets_file = Path(options["secrets_file"])
        dry_run = options["dry_run"]
        limit = options["limit"]

        if not dry_run and not secrets_file.exists():
            self.stderr.write(self.style.ERROR(f"Secrets file not found: {secrets_file}"))
            return

        # Get performers with YouTube songs but no YouTube social link
        performers_with_songs = (
            Performer.objects.filter(
                songs__youtube_video_id__isnull=False,
            )
            .exclude(songs__youtube_video_id="")
            .distinct()
        )

        # Exclude performers who already have a YouTube social link
        performers_with_youtube_link = PerformerSocialLink.objects.filter(platform="youtube").values_list(
            "performer_id", flat=True
        )

        performers_to_process = performers_with_songs.exclude(id__in=performers_with_youtube_link)

        if limit > 0:
            performers_to_process = performers_to_process[:limit]

        total = performers_to_process.count()
        self.stdout.write(f"Found {total} performers to process")

        if total == 0:
            self.stdout.write(self.style.SUCCESS("No performers need backfilling"))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made\n"))

        youtube = None
        if not dry_run:
            youtube = get_youtube_client(secrets_file)

        created_count = 0
        failed_count = 0
        video_ids_batch = []
        performer_video_map = {}

        # Collect video IDs for batch API calls
        for performer in performers_to_process:
            song = (
                PerformerSong.objects.filter(
                    performer=performer,
                    youtube_video_id__isnull=False,
                )
                .exclude(youtube_video_id="")
                .first()
            )

            if song:
                video_ids_batch.append(song.youtube_video_id)
                performer_video_map[song.youtube_video_id] = performer

        # Process in batches of 50 (YouTube API limit)
        batch_size = 50
        for i in range(0, len(video_ids_batch), batch_size):
            batch = video_ids_batch[i : i + batch_size]

            if dry_run:
                for video_id in batch:
                    performer = performer_video_map[video_id]
                    self.stdout.write(f"  Would fetch channel for: {performer.name} (video: {video_id})")
                continue

            try:
                request = youtube.videos().list(part="snippet", id=",".join(batch))
                response = request.execute()

                for item in response.get("items", []):
                    video_id = item["id"]
                    performer = performer_video_map.get(video_id)

                    if not performer:
                        continue

                    snippet = item.get("snippet", {})
                    channel_id = snippet.get("channelId")
                    channel_title = snippet.get("channelTitle", "")

                    if channel_id:
                        channel_url = f"https://www.youtube.com/channel/{channel_id}"

                        PerformerSocialLink.objects.create(
                            performer=performer,
                            platform="youtube",
                            platform_id=channel_id,
                            url=channel_url,
                        )

                        self.stdout.write(
                            self.style.SUCCESS(f"  Created: {performer.name} -> {channel_title} ({channel_url})")
                        )
                        created_count += 1
                    else:
                        self.stdout.write(self.style.WARNING(f"  No channel found for: {performer.name}"))
                        failed_count += 1

            except Exception as e:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"  API error for batch: {e}"))
                failed_count += len(batch)

        if dry_run:
            self.stdout.write(f"\nDRY RUN: Would process {total} performers")
        else:
            self.stdout.write("\nBackfill complete:")
            self.stdout.write(self.style.SUCCESS(f"  Created: {created_count}"))
            if failed_count:
                self.stdout.write(self.style.WARNING(f"  Failed: {failed_count}"))
