"""Performer name normalization and fuzzy matching."""

import re
import unicodedata
from difflib import SequenceMatcher

import jaconv

from performers.models import Performer

FUZZY_MATCH_THRESHOLD = 0.95
TRAILING_PUNCTUATION_PATTERN = re.compile(r"[\[\]()（）{}\s\-/\\、。]+$")
WHITESPACE_PATTERN = re.compile(r"\s+")


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
