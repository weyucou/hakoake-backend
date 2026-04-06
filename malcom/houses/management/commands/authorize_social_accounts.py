"""Run OAuth authorization flow for Instagram and/or Threads.

Usage:
    uv run python manage.py authorize_social_accounts --instagram
    uv run python manage.py authorize_social_accounts --threads
    uv run python manage.py authorize_social_accounts --instagram --threads
"""

import logging

from commons.instagram_utils import get_instagram_token
from commons.threads_utils import get_threads_token
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Authorize Instagram and/or Threads accounts via OAuth and cache tokens locally"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--instagram", action="store_true", help="Authorize Instagram account")
        parser.add_argument("--threads", action="store_true", help="Authorize Threads account")

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        if not options["instagram"] and not options["threads"]:
            self.stderr.write("Specify --instagram and/or --threads")
            return

        cert_file = settings.OAUTH_LOCALHOST_CERT
        key_file = settings.OAUTH_LOCALHOST_KEY

        if not cert_file.exists() or not key_file.exists():
            self.stderr.write(
                f"TLS cert not found at {cert_file} / {key_file}\nRun: mkcert localhost  (from the project root)"
            )
            return

        if options["instagram"]:
            if not settings.INSTAGRAM_APP_ID or not settings.INSTAGRAM_APP_SECRET:
                self.stderr.write("INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET must be set in .env")
                return
            token_cache = cert_file.parent / "instagram_token.json"
            self.stdout.write("Starting Instagram OAuth flow — a browser window will open...")
            try:
                token = get_instagram_token(cert_file, key_file, token_cache)
                self.stdout.write(self.style.SUCCESS(f"Instagram authorized — user_id={token.user_id}"))
                self.stdout.write(f"Add to .env:  INSTAGRAM_USER_ID={token.user_id}")
                self.stdout.write(f"Token expires: {token.expires_at.date()}")
            except Exception as exc:
                logger.exception("Instagram authorization failed")
                self.stderr.write(f"Instagram authorization failed: {exc}")

        if options["threads"]:
            if not settings.THREADS_APP_ID or not settings.THREADS_APP_SECRET:
                self.stderr.write("THREADS_APP_ID and THREADS_APP_SECRET must be set in .env")
                return
            token_cache = cert_file.parent / "threads_token.json"
            self.stdout.write("Starting Threads OAuth flow — a browser window will open...")
            try:
                token = get_threads_token(cert_file, key_file, token_cache)
                self.stdout.write(self.style.SUCCESS(f"Threads authorized — user_id={token.user_id}"))
                self.stdout.write(f"Add to .env:  THREADS_USER_ID={token.user_id}")
                self.stdout.write(f"Token expires: {token.expires_at.date()}")
            except Exception as exc:
                logger.exception("Threads authorization failed")
                self.stderr.write(f"Threads authorization failed: {exc}")
