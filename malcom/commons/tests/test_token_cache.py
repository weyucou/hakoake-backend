"""Regression tests for JSON-based token cache serialization.

Covers the round-trip for InstagramToken and ThreadsToken to ensure
module renames cannot break deserialization (the pickle path was fragile).
"""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from django.test import TestCase

from commons.instagram_utils import (
    InstagramToken,
    _load_token as _load_instagram_token,
    _save_token as _save_instagram_token,
)
from commons.threads_utils import ThreadsToken, _load_token as _load_threads_token, _save_token as _save_threads_token


def _make_instagram_token() -> InstagramToken:
    now = datetime.now(tz=UTC)
    return InstagramToken(
        access_token="test-access-token",  # noqa: S106
        user_id="123456789",
        issued_at=now,
        expires_at=now + timedelta(days=60),
    )


def _make_threads_token() -> ThreadsToken:
    now = datetime.now(tz=UTC)
    return ThreadsToken(
        access_token="test-threads-token",  # noqa: S106
        user_id="987654321",
        issued_at=now,
        expires_at=now + timedelta(days=60),
    )


class TestInstagramTokenCache(TestCase):
    def test_save_and_load_roundtrip(self) -> None:
        token = _make_instagram_token()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            cache_file = Path(f.name)

        try:
            _save_instagram_token(token, cache_file)
            loaded = _load_instagram_token(cache_file)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.access_token, token.access_token)
            self.assertEqual(loaded.user_id, token.user_id)
            self.assertEqual(loaded.issued_at, token.issued_at)
            self.assertEqual(loaded.expires_at, token.expires_at)
        finally:
            cache_file.unlink(missing_ok=True)

    def test_load_returns_none_when_file_missing(self) -> None:
        result = _load_instagram_token(Path("/tmp/nonexistent_instagram_token.json"))  # noqa: S108
        self.assertIsNone(result)

    def test_load_returns_none_on_invalid_json(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("not valid json {{{")
            cache_file = Path(f.name)

        try:
            result = _load_instagram_token(cache_file)
            self.assertIsNone(result)
        finally:
            cache_file.unlink(missing_ok=True)

    def test_cache_file_is_json_not_pickle(self) -> None:
        token = _make_instagram_token()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            cache_file = Path(f.name)

        try:
            _save_instagram_token(token, cache_file)
            content = cache_file.read_text()
            # JSON starts with '{', pickle starts with b'\x80'
            self.assertTrue(content.startswith("{"))
            self.assertIn("access_token", content)
        finally:
            cache_file.unlink(missing_ok=True)


class TestThreadsTokenCache(TestCase):
    def test_save_and_load_roundtrip(self) -> None:
        token = _make_threads_token()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            cache_file = Path(f.name)

        try:
            _save_threads_token(token, cache_file)
            loaded = _load_threads_token(cache_file)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.access_token, token.access_token)
            self.assertEqual(loaded.user_id, token.user_id)
            self.assertEqual(loaded.issued_at, token.issued_at)
            self.assertEqual(loaded.expires_at, token.expires_at)
        finally:
            cache_file.unlink(missing_ok=True)

    def test_load_returns_none_when_file_missing(self) -> None:
        result = _load_threads_token(Path("/tmp/nonexistent_threads_token.json"))  # noqa: S108
        self.assertIsNone(result)

    def test_load_returns_none_on_invalid_json(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("not valid json {{{")
            cache_file = Path(f.name)

        try:
            result = _load_threads_token(cache_file)
            self.assertIsNone(result)
        finally:
            cache_file.unlink(missing_ok=True)

    def test_cache_file_is_json_not_pickle(self) -> None:
        token = _make_threads_token()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            cache_file = Path(f.name)

        try:
            _save_threads_token(token, cache_file)
            content = cache_file.read_text()
            self.assertTrue(content.startswith("{"))
            self.assertIn("access_token", content)
        finally:
            cache_file.unlink(missing_ok=True)
