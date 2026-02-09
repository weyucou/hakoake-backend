import re

from django.core.management.base import BaseCommand, CommandParser

from performers.models import Performer, PerformerSocialLink


def extract_platform_id_from_url(url: str, platform: str) -> str | None:
    """Extract platform-specific ID from URL."""
    if platform == "youtube":
        # Match channel ID: /channel/UC..., /@username, /c/customname, /user/username
        if match := re.search(r"youtube\.com/channel/([^/?]+)", url):
            return match.group(1)
        if match := re.search(r"youtube\.com/@([^/?]+)", url):
            return f"@{match.group(1)}"
        if match := re.search(r"youtube\.com/(?:c|user)/([^/?]+)", url):
            return match.group(1)
    elif platform == "twitter":
        if match := re.search(r"(?:twitter\.com|x\.com)/([^/?]+)", url):
            return match.group(1)
    elif platform == "instagram":
        if match := re.search(r"instagram\.com/([^/?]+)", url):
            return match.group(1)
    return None


class Command(BaseCommand):
    help = "Update a PerformerSocialLink URL for a given performer and platform"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--performer-id",
            type=int,
            required=True,
            help="ID of the Performer",
        )
        parser.add_argument(
            "--platform",
            type=str,
            required=True,
            help="Platform name (e.g., youtube, twitter, instagram)",
        )
        parser.add_argument(
            "url",
            type=str,
            help="New URL to set for the PerformerSocialLink",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        """Update the PerformerSocialLink URL and platform_id."""
        performer_id = options["performer_id"]
        platform = options["platform"]
        url = options["url"]

        try:
            performer = Performer.objects.get(id=performer_id)
        except Performer.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Performer with id={performer_id} not found"))
            return

        try:
            link = PerformerSocialLink.objects.get(performer=performer, platform=platform)
        except PerformerSocialLink.DoesNotExist:
            self.stderr.write(
                self.style.ERROR(
                    f"PerformerSocialLink for performer '{performer.name}' with platform '{platform}' not found"
                )
            )
            return

        old_url = link.url
        old_platform_id = link.platform_id

        # Extract new platform_id from URL
        new_platform_id = extract_platform_id_from_url(url, platform)

        link.url = url
        if new_platform_id:
            link.platform_id = new_platform_id
        link.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated PerformerSocialLink for '{performer.name}' ({platform}):\n"
                f"  Old URL: {old_url}\n"
                f"  New URL: {url}\n"
                f"  Old platform_id: {old_platform_id}\n"
                f"  New platform_id: {link.platform_id}"
            )
        )
