"""Generate playlist introduction video for a given WeeklyPlaylist."""

from pathlib import Path

from commons.instagram_post import post_story
from commons.instagram_utils import get_instagram_token
from commons.youtube_utils import insert_video_at_position, post_video_comment, upload_video_to_youtube
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone
from houses.functions import (
    generate_weekly_playlist_video,
    generate_weekly_playlist_video_shorts,
    generate_weekly_playlist_video_story,
)
from houses.models import PerformanceSchedule, WeeklyPlaylist

VIDEO_FORMAT_STANDARD = "standard"
VIDEO_FORMAT_SHORTS = "shorts"
VIDEO_FORMAT_STORY = "story"


class Command(BaseCommand):
    help = "Generate introduction video for a weekly playlist using AI"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "playlist_id",
            type=int,
            help="ID of the WeeklyPlaylist to generate video for",
        )
        parser.add_argument(
            "--intro-text-file",
            type=str,
            help="Path to UTF-8 text file containing pre-written introduction text",
        )
        parser.add_argument(
            "--secrets-file",
            type=str,
            default="../client_secret.json",
            help="Path to Google OAuth secrets file (default: ../client_secret.json)",
        )
        parser.add_argument(
            "--skip-update-playlist",
            action="store_true",
            help="Skip uploading the video to YouTube and inserting it into the playlist",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Bypass idempotency guards and re-render/re-upload/re-insert the intro video",
        )
        parser.add_argument(
            "--format",
            choices=[VIDEO_FORMAT_STANDARD, VIDEO_FORMAT_SHORTS, VIDEO_FORMAT_STORY],
            default=VIDEO_FORMAT_STANDARD,
            dest="video_format",
            help=(
                "Output format: 'standard' for 1920x1080 long-form, "
                "'shorts' for 1080x1920 9:16 ≤60s YouTube Shorts, "
                "'story' for 1080x1920 9:16 ≤55s Instagram Story (5 performers, no closing)"
            ),
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003, C901, PLR0911, PLR0912, PLR0915
        """Generate and save playlist introduction video."""
        playlist_id = options["playlist_id"]
        intro_text_file = options.get("intro_text_file")
        secrets_file = Path(options["secrets_file"])
        skip_update_playlist = options["skip_update_playlist"]
        force = options["force"]
        video_format = options["video_format"]

        try:
            playlist = WeeklyPlaylist.objects.get(id=playlist_id)
        except WeeklyPlaylist.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"WeeklyPlaylist with id={playlist_id} not found"))
            return

        self.stdout.write(f"Generating video for playlist: week of {playlist.date.strftime('%Y-%m-%d')}")
        self.stdout.write(f"Playlist URL: {playlist.youtube_playlist_url}")

        if video_format == VIDEO_FORMAT_SHORTS:
            self.stdout.write("Format: shorts (9:16, ≤60s)")

            if not skip_update_playlist and not force and playlist.shorts_youtube_video_id:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Shorts video already uploaded (video_id={playlist.shorts_youtube_video_id}); skipping. "
                        f"Pass --force to re-render."
                    )
                )
                return

            if force and playlist.shorts_youtube_video_id:
                self.stdout.write(
                    self.style.WARNING(
                        f"--force: clearing previously stored shorts video state "
                        f"(previous video_id={playlist.shorts_youtube_video_id!r})."
                    )
                )
                playlist.shorts_youtube_video_id = ""
                playlist.save(update_fields=["shorts_youtube_video_id"])

            shorts_filepath = generate_weekly_playlist_video_shorts(playlist)
            self.stdout.write(self.style.SUCCESS("\n=== Shorts Video Generated ===\n"))
            self.stdout.write(f"Video saved to: {shorts_filepath}")

            if skip_update_playlist:
                self.stdout.write("Skipping YouTube upload (--skip-update-playlist)")
                return

            if not secrets_file.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"Secrets file not found: {secrets_file} — skipping upload. Upload manually to YouTube Shorts."
                    )
                )
                return

            week_str = playlist.date.strftime("%Y-%m-%d")
            shorts_title = f"HAKKO-AKKEI WEEK {week_str} TOKYO Shorts"
            shorts_description = f"Weekly lineup for the week of {week_str}."
            if playlist.youtube_playlist_url:
                shorts_description += f"\nPlaylist: {playlist.youtube_playlist_url}"

            self.stdout.write(f"Uploading shorts to YouTube: {shorts_title}")
            try:
                shorts_video_id = upload_video_to_youtube(
                    shorts_filepath, shorts_title, shorts_description, secrets_file
                )
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"Failed to upload shorts: {exc}"))
                return

            playlist.shorts_youtube_video_id = shorts_video_id
            playlist.save(update_fields=["shorts_youtube_video_id"])
            self.stdout.write(self.style.SUCCESS(f"Uploaded shorts: https://youtu.be/{shorts_video_id}"))

            # Post playlist description as a comment on the shorts video
            entries = list(playlist.weeklyplaylistentry_set.select_related("song__performer").order_by("position"))
            date_start = playlist.date
            date_end = date_start + timezone.timedelta(days=7)
            performer_ids = [e.song.performer_id for e in entries]
            schedules = (
                PerformanceSchedule.objects.filter(
                    performers__in=performer_ids,
                    performance_date__gte=date_start,
                    performance_date__lt=date_end,
                )
                .select_related("live_house")
                .prefetch_related("performers")
            )
            schedule_by_performer: dict[int, PerformanceSchedule] = {}
            for s in schedules:
                for p in s.performers.all():
                    schedule_by_performer.setdefault(p.pk, s)
            lineup_lines = []
            for e in entries:
                performer = e.song.performer
                performance = schedule_by_performer.get(performer.pk)
                line = f"{e.position}. {performer.name}"
                if performance:
                    date_label = performance.performance_date.strftime("%b %-d")
                    line += f" @ {performance.live_house.name} — {date_label}"
                lineup_lines.append(line)
            comment_text = f"Bands playing the week of {week_str}\n\n" + "\n".join(lineup_lines)
            if playlist.youtube_playlist_url:
                comment_text += f"\n\nPlaylist: {playlist.youtube_playlist_url}"

            comment_ok = post_video_comment(shorts_video_id, comment_text, secrets_file)
            if comment_ok:
                self.stdout.write(self.style.SUCCESS("Posted playlist description as comment."))
            else:
                self.stderr.write(self.style.WARNING("Failed to post comment — manual comment may be needed."))
            return

        if video_format == VIDEO_FORMAT_STORY:
            self.stdout.write("Format: story (9:16, ≤55s, Instagram Story)")

            if not force and playlist.instagram_story_id:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Story already posted (story_id={playlist.instagram_story_id}); skipping. "
                        f"Pass --force to re-post."
                    )
                )
                return

            if force and playlist.instagram_story_id:
                self.stdout.write(
                    self.style.WARNING(
                        f"--force: clearing previously stored story state "
                        f"(previous story_id={playlist.instagram_story_id!r})."
                    )
                )
                playlist.instagram_story_id = ""
                playlist.save(update_fields=["instagram_story_id"])

            story_filepath = generate_weekly_playlist_video_story(playlist)
            self.stdout.write(self.style.SUCCESS("\n=== Story Video Generated ===\n"))
            self.stdout.write(f"Video saved to: {story_filepath}")

            if skip_update_playlist:
                self.stdout.write("Skipping Instagram Story post (--skip-update-playlist)")
                return

            self.stdout.write("Posting to Instagram Story...")
            if not settings.INSTAGRAM_USER_ID:
                self.stderr.write(self.style.ERROR("INSTAGRAM_USER_ID not set in .env"))
                return

            cert_file = settings.OAUTH_LOCALHOST_CERT
            key_file = settings.OAUTH_LOCALHOST_KEY
            token_cache = cert_file.parent / "instagram_token.json"
            try:
                token = get_instagram_token(cert_file, key_file, token_cache)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"Failed to obtain Instagram token: {exc}"))
                return
            user_id = settings.INSTAGRAM_USER_ID
            access_token = token.access_token

            week_str = playlist.date.strftime("%Y%m%d")
            story_filename = f"story_{week_str}.mp4"
            video_bytes = story_filepath.read_bytes()
            try:
                story_id = post_story(user_id, access_token, video_bytes, story_filename)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"Failed to post Instagram Story: {exc}"))
                return

            playlist.instagram_story_id = story_id
            playlist.save(update_fields=["instagram_story_id"])
            self.stdout.write(self.style.SUCCESS(f"Instagram Story posted: {story_id}"))
            return

        # Idempotency branches — only relevant when we would otherwise upload/insert.
        if not skip_update_playlist and not force:
            if playlist.intro_youtube_video_id and playlist.intro_video_inserted_datetime:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Intro video already uploaded and inserted "
                        f"(video_id={playlist.intro_youtube_video_id}); skipping. "
                        f"Pass --force to re-render."
                    )
                )
                return

            if playlist.intro_youtube_video_id and not playlist.intro_video_inserted_datetime:
                if not playlist.youtube_playlist_id:
                    self.stderr.write(self.style.ERROR("Playlist has no youtube_playlist_id — cannot insert"))
                    return
                if not secrets_file.exists():
                    self.stderr.write(self.style.ERROR(f"Secrets file not found: {secrets_file}"))
                    return
                self.stdout.write(
                    f"Intro video already uploaded (video_id={playlist.intro_youtube_video_id}); "
                    f"retrying insert at position 0 only."
                )
                success = insert_video_at_position(
                    playlist.youtube_playlist_id, playlist.intro_youtube_video_id, 0, secrets_file
                )
                if success:
                    playlist.intro_video_inserted_datetime = timezone.now()
                    playlist.save(update_fields=["intro_video_inserted_datetime"])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Inserted intro video as first playlist entry: "
                            f"https://youtu.be/{playlist.intro_youtube_video_id}"
                        )
                    )
                else:
                    self.stderr.write(self.style.ERROR("Failed to insert video into playlist"))
                return

        # --force: clear previously persisted intro state before re-rendering.
        if force and (playlist.intro_youtube_video_id or playlist.intro_video_inserted_datetime):
            self.stdout.write(
                self.style.WARNING(
                    f"--force: clearing previously stored intro video state "
                    f"(previous video_id={playlist.intro_youtube_video_id!r}). "
                    f"The old YouTube video is not deleted automatically."
                )
            )
            playlist.intro_youtube_video_id = ""
            playlist.intro_video_inserted_datetime = None
            playlist.save(update_fields=["intro_youtube_video_id", "intro_video_inserted_datetime"])

        # Load introduction text from file if provided
        intro_text = None
        if intro_text_file:
            intro_path = Path(intro_text_file)
            if not intro_path.exists():
                self.stderr.write(self.style.ERROR(f"Introduction text file not found: {intro_text_file}"))
                return
            try:
                intro_text = intro_path.read_text(encoding="utf-8")
                self.stdout.write(f"Using introduction text from: {intro_text_file}")
            except Exception as e:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"Failed to read introduction text file: {e}"))
                return
        else:
            self.stdout.write("Generating introduction text with AI...")

        self.stdout.write("")

        # Generate video
        video_filepath = generate_weekly_playlist_video(playlist, intro_text=intro_text)

        self.stdout.write(self.style.SUCCESS("\n=== Video Generated ===\n"))
        self.stdout.write(f"Video saved to: {video_filepath}")

        if skip_update_playlist:
            self.stdout.write("Skipping YouTube upload (--skip-update-playlist)")
            return

        if not playlist.youtube_playlist_id:
            self.stderr.write(self.style.ERROR("Playlist has no youtube_playlist_id — cannot upload"))
            return

        if not secrets_file.exists():
            self.stderr.write(self.style.ERROR(f"Secrets file not found: {secrets_file}"))
            return

        # Upload video to YouTube
        week_str = playlist.date.strftime("%Y-%m-%d")
        video_title = f"HAKKO-AKKEI WEEK {week_str} TOKYO Playlist Introduction"
        video_description = (
            f"Weekly playlist introduction for the week of {week_str}.\nPlaylist: {playlist.youtube_playlist_url}"
        )

        self.stdout.write(f"Uploading video to YouTube: {video_title}")
        try:
            video_id = upload_video_to_youtube(video_filepath, video_title, video_description, secrets_file)
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(self.style.ERROR(f"Failed to upload video: {exc}"))
            return

        # Persist upload result immediately so a later crash cannot cause a re-upload.
        playlist.intro_youtube_video_id = video_id
        playlist.save(update_fields=["intro_youtube_video_id"])

        self.stdout.write(f"Uploaded video ID: {video_id}")

        # Insert as first entry in the playlist
        self.stdout.write(f"Inserting video at position 0 in playlist {playlist.youtube_playlist_id}...")
        success = insert_video_at_position(playlist.youtube_playlist_id, video_id, 0, secrets_file)
        if success:
            playlist.intro_video_inserted_datetime = timezone.now()
            playlist.save(update_fields=["intro_video_inserted_datetime"])
            self.stdout.write(
                self.style.SUCCESS(f"Inserted intro video as first playlist entry: https://youtu.be/{video_id}")
            )
        else:
            self.stderr.write(self.style.ERROR("Failed to insert video into playlist"))
