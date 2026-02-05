import sys

from django.core.management.base import BaseCommand

from performers.models import PerformerSocialLink


class Command(BaseCommand):
    help = "List all PerformerSocialLink entries ordered by performer"

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        """List all PerformerSocialLink entries."""
        links = PerformerSocialLink.objects.select_related("performer").order_by("performer__name", "platform")

        if not links.exists():
            self.stdout.write(self.style.WARNING("No PerformerSocialLink entries found."))
            return

        try:
            self.stdout.write(f"Found {links.count()} PerformerSocialLink entries:\n")

            for link in links:
                verified = link.verified_datetime.strftime("%Y-%m-%d %H:%M") if link.verified_datetime else ""
                verified_indicator = self.style.SUCCESS("✓") if link.verified_datetime else self.style.WARNING("?")

                self.stdout.write(
                    f"{verified_indicator} {link.performer.id} {link.performer.name} "
                    f"{link.platform}({link.platform_id}) {link.url} {verified}"
                )

            self.stdout.write("")
        except BrokenPipeError:
            # Handle pipe being closed early (e.g., when piping to head)
            sys.stderr.close()
            sys.exit(0)
