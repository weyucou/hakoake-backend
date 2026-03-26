"""Tests for performer name normalization and fuzzy matching."""

from django.test import TestCase

from performers.models import Performer
from performers.normalization import channel_name_matches, find_existing_performer, normalize_performer_name


class TestNormalizePerformerName(TestCase):
    """Unit tests for normalize_performer_name (no DB required)."""

    def test_lowercase(self) -> None:
        self.assertEqual(normalize_performer_name("RAN"), "ran")

    def test_fullwidth_to_halfwidth(self) -> None:
        """NFKC converts full-width ASCII to half-width."""
        self.assertEqual(normalize_performer_name("Ｒａｎ"), "ran")

    def test_fullwidth_slash(self) -> None:
        """Full-width slash normalizes to half-width slash."""
        self.assertEqual(normalize_performer_name("A／B"), "a/b")

    def test_katakana_to_hiragana(self) -> None:
        self.assertEqual(normalize_performer_name("バンド"), normalize_performer_name("ばんど"))

    def test_bom_stripped(self) -> None:
        self.assertEqual(normalize_performer_name("\ufeffRAN"), "ran")

    def test_trailing_brackets_stripped(self) -> None:
        self.assertEqual(normalize_performer_name("Band[]"), "band")

    def test_trailing_parens_stripped(self) -> None:
        self.assertEqual(normalize_performer_name("Band()"), "band")

    def test_trailing_fullwidth_parens_stripped(self) -> None:
        self.assertEqual(normalize_performer_name("Band（）"), "band")

    def test_trailing_whitespace_and_dash(self) -> None:
        self.assertEqual(normalize_performer_name("Band - "), "band")

    def test_whitespace_collapsed(self) -> None:
        self.assertEqual(normalize_performer_name("The   Band"), "the band")

    def test_preserves_internal_punctuation(self) -> None:
        """Internal punctuation that is meaningful should be preserved."""
        result = normalize_performer_name("AC/DC")
        self.assertEqual(result, "ac/dc")

    def test_preserves_internal_dot(self) -> None:
        result = normalize_performer_name("Mr.Children")
        self.assertEqual(result, "mr.children")

    def test_empty_string(self) -> None:
        self.assertEqual(normalize_performer_name(""), "")

    def test_only_punctuation(self) -> None:
        self.assertEqual(normalize_performer_name("[]()"), "")


def _create_performer(name: str) -> Performer:
    """Create a performer with image fetch skipped."""
    performer = Performer(name=name, name_kana=name, name_romaji=name)
    performer._skip_image_fetch = True  # noqa: SLF001
    performer.save()
    return performer


class TestFindExistingPerformer(TestCase):
    """DB tests for find_existing_performer."""

    def test_exact_match(self) -> None:
        p = _create_performer("RAN")
        self.assertEqual(find_existing_performer("RAN"), p)

    def test_case_variant(self) -> None:
        p = _create_performer("RAN")
        self.assertEqual(find_existing_performer("Ran"), p)

    def test_fullwidth_variant(self) -> None:
        p = _create_performer("RAN")
        self.assertEqual(find_existing_performer("ＲＡＮ"), p)

    def test_kana_variant(self) -> None:
        """Katakana matches hiragana via normalization."""
        p = _create_performer("ばんど")
        self.assertEqual(find_existing_performer("バンド"), p)

    def test_trailing_punctuation(self) -> None:
        p = _create_performer("Band")
        self.assertEqual(find_existing_performer("Band[]"), p)

    def test_no_false_positive_for_different_names(self) -> None:
        """RAN and RAM are different enough to not match."""
        _create_performer("RAN")
        self.assertIsNone(find_existing_performer("RAM"))

    def test_returns_none_when_no_match(self) -> None:
        self.assertIsNone(find_existing_performer("Nonexistent Band"))

    def test_bom_variant(self) -> None:
        p = _create_performer("RAN")
        self.assertEqual(find_existing_performer("\ufeffRAN"), p)


class TestChannelNameMatches(TestCase):
    """Unit tests for channel_name_matches (no DB required)."""

    # Tier 1: substring containment
    def test_exact_match(self) -> None:
        self.assertTrue(channel_name_matches("THE MAGNETS", "THE MAGNETS", ""))

    def test_performer_in_channel(self) -> None:
        self.assertTrue(channel_name_matches("AKIARIM", "AKIARIM OFFICIAL CHANNEL", ""))

    def test_channel_in_performer(self) -> None:
        self.assertTrue(channel_name_matches("The R.O.X & GWO", "The R.O.X", ""))

    # Tier 2: fuzzy match with suffix stripping
    def test_fuzzy_spacing(self) -> None:
        """Names differing only by spaces should match."""
        self.assertTrue(channel_name_matches("2ndunite", "2nd unite", ""))

    def test_fuzzy_spacing_cherry(self) -> None:
        self.assertTrue(channel_name_matches("CHERRY NADE 169", "CHERRYNADE169", ""))

    def test_fuzzy_official_suffix(self) -> None:
        """Channel with 'official' suffix should match."""
        self.assertTrue(channel_name_matches("urei", "urei official", ""))

    def test_fuzzy_topic_suffix(self) -> None:
        """YouTube '- Topic' auto-generated channels should match."""
        self.assertTrue(channel_name_matches("Sadamori Kouki Band", "Sadamori Kouki - Topic", ""))

    def test_fuzzy_vevo_suffix(self) -> None:
        self.assertTrue(channel_name_matches("Dope Flamingo", "DopeFlamingo VEVO", ""))

    def test_fuzzy_typo(self) -> None:
        """Minor typo in performer name should still match."""
        self.assertTrue(channel_name_matches("XOXO EXTRIME", "XOXO EXTREME Channnel", ""))

    def test_fuzzy_katakana_spacing(self) -> None:
        """Japanese names with punctuation differences should match."""
        self.assertTrue(channel_name_matches("サムライ・シバ・ロック", "サムライシバロック", ""))

    # Tier 3: description fallback
    def test_description_match(self) -> None:
        self.assertTrue(channel_name_matches("MyBand", "SomeLabel", "Official channel of MyBand"))

    # Negative cases
    def test_unrelated_channel(self) -> None:
        self.assertFalse(channel_name_matches("0mg", "HYBE LABELS", ""))

    def test_unrelated_short_name(self) -> None:
        self.assertFalse(channel_name_matches("CAL", "Vulf", ""))

    def test_unrelated_japanese(self) -> None:
        self.assertFalse(channel_name_matches("ANTENA", "Mrs. GREEN APPLE", ""))

    def test_empty_performer(self) -> None:
        self.assertFalse(channel_name_matches("", "SomeChannel", ""))
