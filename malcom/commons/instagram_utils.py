"""Instagram Graph API utilities (Instagram Login path).

OAuth flow:
  1. Open browser to authorization URL -> user grants access -> redirect to https://localhost:8080/?code=...
  2. Local HTTPS server captures the code
  3. Exchange code for short-lived token (POST api.instagram.com/oauth/access_token)
  4. Exchange short-lived for long-lived token (GET graph.instagram.com/access_token)
  5. Cache token and user_id to pickle file

Token lifetime: long-lived tokens expire after 60 days of non-use.
Refresh any time after 24 hours of issuance and before 60-day expiry.
"""

import logging
import pickle
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

INSTAGRAM_AUTH_URL = "https://api.instagram.com/oauth/authorize"
INSTAGRAM_TOKEN_URL = "https://api.instagram.com/oauth/access_token"  # noqa: S105
INSTAGRAM_LONG_LIVED_TOKEN_URL = "https://graph.instagram.com/access_token"  # noqa: S105
INSTAGRAM_REFRESH_TOKEN_URL = "https://graph.instagram.com/refresh_access_token"  # noqa: S105
INSTAGRAM_API_BASE = "https://graph.instagram.com/v22.0"

INSTAGRAM_SCOPES = [
    "instagram_business_basic",
    "instagram_business_content_publish",
]

REDIRECT_URI = "https://localhost:8080/"


class InstagramToken(BaseModel):
    access_token: str
    user_id: str
    token_type: str = "bearer"  # noqa: S105
    issued_at: datetime
    expires_at: datetime  # long-lived tokens: 60 days from issued_at

    @property
    def is_expired(self) -> bool:
        return datetime.now(tz=UTC) >= self.expires_at

    @property
    def is_refreshable(self) -> bool:
        """Tokens are refreshable after 24 hours and before expiry."""
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
            pass  # suppress request logging

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
            "scope": ",".join(INSTAGRAM_SCOPES),
            "response_type": "code",
        }
    )
    auth_url = f"{INSTAGRAM_AUTH_URL}?{auth_params}"
    logger.info(f"Opening browser for Instagram authorization: {auth_url}")
    webbrowser.open(auth_url)

    server_thread.join(timeout=120)

    if "code" not in captured:
        raise TimeoutError("Instagram OAuth: no auth code received within 120 seconds")

    # Meta appends #_ to the code -- strip it
    return captured["code"].split("#")[0]


def _get_app_id() -> str:
    return settings.INSTAGRAM_APP_ID


def _get_app_secret() -> str:
    return settings.INSTAGRAM_APP_SECRET


def _exchange_code_for_short_lived_token(code: str) -> str:
    response = requests.post(
        INSTAGRAM_TOKEN_URL,
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
        INSTAGRAM_LONG_LIVED_TOKEN_URL,
        params={
            "grant_type": "ig_exchange_token",
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
        INSTAGRAM_REFRESH_TOKEN_URL,
        params={
            "grant_type": "ig_refresh_token",
            "access_token": access_token,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _fetch_user_id(access_token: str) -> str:
    response = requests.get(
        f"{INSTAGRAM_API_BASE}/me",
        params={"fields": "user_id,username", "access_token": access_token},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return str(data["user_id"])


def _load_token(cache_file: Path) -> InstagramToken | None:
    if not cache_file.exists():
        return None
    try:
        return pickle.loads(cache_file.read_bytes())  # noqa: S301
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to load Instagram token cache: {exc}")
        return None


def _save_token(token: InstagramToken, cache_file: Path) -> None:
    try:
        cache_file.write_bytes(pickle.dumps(token))
        logger.info(f"Instagram token cached to {cache_file}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to save Instagram token cache: {exc}")


def get_instagram_token(cert_file: Path, key_file: Path, token_cache_file: Path) -> InstagramToken:
    """Return a valid Instagram access token, refreshing or re-authorizing as needed."""
    now = datetime.now(tz=UTC)
    token = _load_token(token_cache_file)

    if token and token.is_expired:
        logger.info("Instagram token expired -- re-authorization required")
        token = None

    if token and token.is_refreshable:
        logger.info("Refreshing Instagram long-lived token")
        try:
            data = _refresh_long_lived_token(token.access_token)
            token = InstagramToken(
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
    logger.info("Running Instagram OAuth flow")
    code = _run_local_oauth_server(cert_file, key_file)
    short_lived = _exchange_code_for_short_lived_token(code)
    data = _exchange_for_long_lived_token(short_lived)
    user_id = _fetch_user_id(data["access_token"])
    now = datetime.now(tz=UTC)

    token = InstagramToken(
        access_token=data["access_token"],
        user_id=user_id,
        issued_at=now,
        expires_at=now + timedelta(seconds=data["expires_in"]),
    )
    _save_token(token, token_cache_file)
    logger.info(f"Instagram OAuth complete -- user_id={user_id}")
    return token
