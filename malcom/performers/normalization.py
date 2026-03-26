"""Performer name normalization and fuzzy matching."""

import re
import unicodedata
from difflib import SequenceMatcher

import jaconv

from performers.models import Performer

FUZZY_MATCH_THRESHOLD = 0.95
CHANNEL_MATCH_THRESHOLD = 0.8
TRAILING_PUNCTUATION_PATTERN = re.compile(r"[\[\]()（）{}\s\-/\\、。]+$")
WHITESPACE_PATTERN = re.compile(r"\s+")
# Suffixes commonly appended to channel names that should be stripped before comparison
CHANNEL_SUFFIX_PATTERN = re.compile(
    r"\s*[-–—]\s*topic$"
    r"|\s+official(?:\s+(?:youtube\s+)?channel)?$"
    r"|\s+公式(?:チャンネル|ちゃんねる)?$"
    r"|\s+ch(?:annel|annnel)?\.?$"
    r"|\bvevo$",
    re.IGNORECASE,
)


def normalize_performer_name(name: str) -> str:
    """Produce a canonical form for comparison (never stored).

    Steps:
    1. Strip BOM and whitespace
    2. NFKC normalize (full-width -> half-width)
    3. Katakana -> hiragana
    4. Lowercase
    5. Strip trailing punctuation
    6. Collapse whitespace
    """
    name = name.strip("\ufeff").strip()
    name = unicodedata.normalize("NFKC", name)
    name = jaconv.kata2hira(name)
    name = name.lower()
    name = TRAILING_PUNCTUATION_PATTERN.sub("", name)
    name = WHITESPACE_PATTERN.sub(" ", name).strip()
    return name


def _strip_channel_suffixes(name: str) -> str:
    """Remove common YouTube channel suffixes (official, topic, VEVO, etc.)."""
    return CHANNEL_SUFFIX_PATTERN.sub("", name).strip()


def channel_name_matches(
    performer_name: str,
    channel_title: str,
    channel_description: str = "",
) -> bool:
    """Check if a YouTube channel belongs to a performer.

    Three-tier matching on normalized names:
    1. Substring containment (either direction) on channel title
    2. Fuzzy match (SequenceMatcher >= CHANNEL_MATCH_THRESHOLD) on channel title,
       after stripping common suffixes like "Official", "- Topic", "VEVO"
    3. Substring containment on channel description (fallback)
    """
    norm_performer = normalize_performer_name(performer_name)
    if not norm_performer:
        return False

    norm_title = normalize_performer_name(channel_title)

    # Tier 1: substring containment (bidirectional)
    if norm_performer in norm_title or norm_title in norm_performer:
        return True

    # Tier 2: fuzzy match on title with suffixes stripped
    stripped_title = _strip_channel_suffixes(norm_title)
    stripped_performer = _strip_channel_suffixes(norm_performer)
    ratio = SequenceMatcher(None, stripped_performer, stripped_title).ratio()
    if ratio >= CHANNEL_MATCH_THRESHOLD:
        return True

    # Tier 3: substring check on description
    if channel_description:
        norm_desc = normalize_performer_name(channel_description)
        if norm_performer in norm_desc:
            return True

    return False


def find_existing_performer(name: str) -> Performer | None:
    """Three-tier lookup for an existing performer.

    1. Exact match on Performer.name (fast path)
    2. Normalized exact match across all performers
    3. Fuzzy match (SequenceMatcher >= 0.95) on normalized forms
    """
    # Tier 1: exact match
    exact = Performer.objects.filter(name=name).first()
    if exact:
        return exact

    # Precompute normalized target
    target_normalized = normalize_performer_name(name)
    if not target_normalized:
        return None

    # Tier 2 & 3: iterate all performers once
    best_match: Performer | None = None
    best_ratio: float = 0.0

    for performer in Performer.objects.all():
        candidate_normalized = normalize_performer_name(performer.name)
        if candidate_normalized == target_normalized:
            return performer
        ratio = SequenceMatcher(None, target_normalized, candidate_normalized).ratio()
        if ratio >= FUZZY_MATCH_THRESHOLD and ratio > best_ratio:
            best_match = performer
            best_ratio = ratio

    return best_match
