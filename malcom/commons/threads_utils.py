"""Threads API utilities.

OAuth flow mirrors instagram_utils.py -- same local HTTPS server pattern.

Token lifetime: long-lived tokens expire after 60 days of non-use.
Refresh any time after 24 hours of issuance and before 60-day expiry.
"""

import logging
import ssl
import threading
import webbrowser
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from django.conf import settings
from pydantic import BaseModel

logger = logging.getLogger(__name__)

THREADS_AUTH_URL = "https://threads.net/oauth/authorize"
THREADS_TOKEN_URL = "https://graph.threads.net/oauth/access_token"  # noqa: S105
THREADS_LONG_LIVED_TOKEN_URL = "https://graph.threads.net/access_token"  # noqa: S105
THREADS_REFRESH_TOKEN_URL = "https://graph.threads.net/refresh_access_token"  # noqa: S105
THREADS_API_BASE = "https://graph.threads.net/v1.0"

THREADS_SCOPES = [
    "threads_basic",
    "threads_content_publish",
]

REDIRECT_URI = "https://localhost:8080/"


class ThreadsToken(BaseModel):
    access_token: str
    user_id: str
    token_type: str = "bearer"  # noqa: S105
    issued_at: datetime
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        return datetime.now(tz=UTC) >= self.expires_at

    @property
    def is_refreshable(self) -> bool:
        min_refresh_age = self.issued_at + timedelta(hours=24)
        return datetime.now(tz=UTC) >= min_refresh_age and not self.is_expired


def _run_local_oauth_server(cert_file: Path, key_file: Path) -> str:
    """Start a local HTTPS server, open the browser, and return the captured auth code."""
    captured: dict[str, str] = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if "code" in params:
                captured["code"] = params["code"][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<html><body><h2>Authorization complete. You can close this tab.</h2></body></html>")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"<html><body><h2>Authorization failed - no code received.</h2></body></html>")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    server = HTTPServer(("localhost", 8080), _Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
    server.socket = context.wrap_socket(server.socket, server_side=True)

    server_thread = threading.Thread(target=server.handle_request)
    server_thread.daemon = True
    server_thread.start()

    auth_params = urlencode(
        {
            "client_id": _get_app_id(),
            "redirect_uri": REDIRECT_URI,
            "scope": ",".join(THREADS_SCOPES),
            "response_type": "code",
        }
    )
    auth_url = f"{THREADS_AUTH_URL}?{auth_params}"
    logger.info(f"Opening browser for Threads authorization: {auth_url}")
    webbrowser.open(auth_url)

    server_thread.join(timeout=120)

    if "code" not in captured:
        raise TimeoutError("Threads OAuth: no auth code received within 120 seconds")

    return captured["code"].split("#")[0]


def _get_app_id() -> str:
    return settings.THREADS_APP_ID


def _get_app_secret() -> str:
    return settings.THREADS_APP_SECRET


def _exchange_code_for_short_lived_token(code: str) -> str:
    response = requests.post(
        THREADS_TOKEN_URL,
        data={
            "client_id": _get_app_id(),
            "client_secret": _get_app_secret(),
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _exchange_for_long_lived_token(short_lived_token: str) -> dict:
    response = requests.get(
        THREADS_LONG_LIVED_TOKEN_URL,
        params={
            "grant_type": "th_exchange_token",
            "client_id": _get_app_id(),
            "client_secret": _get_app_secret(),
            "access_token": short_lived_token,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _refresh_long_lived_token(access_token: str) -> dict:
    response = requests.get(
        THREADS_REFRESH_TOKEN_URL,
        params={
            "grant_type": "th_refresh_token",
            "access_token": access_token,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _fetch_user_id(access_token: str) -> str:
    response = requests.get(
        f"{THREADS_API_BASE}/me",
        params={"fields": "id,username", "access_token": access_token},
        timeout=30,
    )
    response.raise_for_status()
    return str(response.json()["id"])


def _load_token(cache_file: Path) -> ThreadsToken | None:
    if not cache_file.exists():
        return None
    try:
        return ThreadsToken.model_validate_json(cache_file.read_text())
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to load Threads token cache ({type(exc).__name__}): {exc}")
        return None


def _save_token(token: ThreadsToken, cache_file: Path) -> None:
    try:
        cache_file.write_text(token.model_dump_json())
        logger.info(f"Threads token cached to {cache_file}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to save Threads token cache: {exc}")


def get_threads_token(cert_file: Path, key_file: Path, token_cache_file: Path) -> ThreadsToken:
    """Return a valid Threads access token, refreshing or re-authorizing as needed."""
    now = datetime.now(tz=UTC)
    token = _load_token(token_cache_file)

    if token and token.is_expired:
        logger.info("Threads token expired -- re-authorization required")
        token = None

    if token and token.is_refreshable:
        logger.info("Refreshing Threads long-lived token")
        try:
            data = _refresh_long_lived_token(token.access_token)
            token = ThreadsToken(
                access_token=data["access_token"],
                user_id=token.user_id,
                issued_at=now,
                expires_at=now + timedelta(seconds=data["expires_in"]),
            )
            _save_token(token, token_cache_file)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Token refresh failed: {exc} -- re-authorizing")
            token = None
        else:
            return token

    if token and token.access_token:
        return token

    # Full OAuth flow
    logger.info("Running Threads OAuth flow")
    code = _run_local_oauth_server(cert_file, key_file)
    short_lived = _exchange_code_for_short_lived_token(code)
    data = _exchange_for_long_lived_token(short_lived)
    user_id = _fetch_user_id(data["access_token"])
    now = datetime.now(tz=UTC)

    token = ThreadsToken(
        access_token=data["access_token"],
        user_id=user_id,
        issued_at=now,
        expires_at=now + timedelta(seconds=data["expires_in"]),
    )
    _save_token(token, token_cache_file)
    logger.info(f"Threads OAuth complete -- user_id={user_id}")
    return token


THREADS_MAX_CHARS = 500


def _truncate_to_threads_limit(description: str, url: str) -> str:
    """Truncate description at a line boundary so the full URL fits within THREADS_MAX_CHARS."""
    full = f"{description}\n{url}"
    if len(full) <= THREADS_MAX_CHARS:
        return full
    budget = THREADS_MAX_CHARS - len(f"…\n{url}")
    lines = description.splitlines()
    kept: list[str] = []
    total = 0
    for line in lines:
        needed = len(line) + (1 if kept else 0)
        if total + needed > budget:
            break
        kept.append(line)
        total += needed
    return "\n".join(kept) + f"…\n{url}"


def _build_weekly_thread_text(playlist: "object", lineup_lines: list[str]) -> str:
    """Build the Threads post text for a weekly playlist."""
    from houses.formatting import build_playlist_description  # noqa: PLC0415

    lineup_str = "\n".join(lineup_lines)
    period_text = f"week of {playlist.date.strftime('%Y-%m-%d')}"  # type: ignore[attr-defined]
    description = build_playlist_description(period_text, lineup_str)
    url = playlist.youtube_playlist_url or f"https://www.youtube.com/playlist?list={playlist.youtube_playlist_id}"  # type: ignore[attr-defined]
    return _truncate_to_threads_limit(description, url)


def _build_monthly_thread_text(playlist: "object", lineup_lines: list[str]) -> str:
    """Build the Threads post text for a monthly playlist."""
    from houses.formatting import build_playlist_description  # noqa: PLC0415

    lineup_str = "\n".join(lineup_lines)
    period_text = playlist.date.strftime("%B %Y")  # type: ignore[attr-defined]
    description = build_playlist_description(period_text, lineup_str)
    url = playlist.youtube_playlist_url or f"https://www.youtube.com/playlist?list={playlist.youtube_playlist_id}"  # type: ignore[attr-defined]
    return _truncate_to_threads_limit(description, url)


def create_thread_post(user_id: str, access_token: str, text: str) -> str:
    """Publish a text-only Threads post via the two-step create-container/publish flow.

    Returns the published thread ID.
    """
    create_resp = requests.post(
        f"{THREADS_API_BASE}/{user_id}/threads",
        params={
            "media_type": "TEXT",
            "text": text,
            "access_token": access_token,
        },
        timeout=30,
    )
    create_resp.raise_for_status()
    container_id = create_resp.json()["id"]
    logger.info(f"Threads container created: {container_id}")

    publish_resp = requests.post(
        f"{THREADS_API_BASE}/{user_id}/threads_publish",
        params={
            "creation_id": container_id,
            "access_token": access_token,
        },
        timeout=30,
    )
    publish_resp.raise_for_status()
    thread_id = publish_resp.json()["id"]
    logger.info(f"Threads post published: {thread_id}")
    return thread_id
