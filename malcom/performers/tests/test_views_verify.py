"""Tests for the PerformerSocialLink verification view."""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from performers.models import Performer, PerformerSocialLink, PerformerSong

User = get_user_model()

VERIFY_URL = reverse("performers:verify_social_link")
ACTION_URL = reverse("performers:verify_social_link_action")


def _create_performer(name: str) -> Performer:
    """Create a performer with youtube search and image fetch skipped."""
    performer = Performer(name=name, name_kana=name, name_romaji=name)
    performer._skip_image_fetch = True
    performer.save()
    return performer


class VerifySocialLinkAuthTestCase(TestCase):
    """Authentication requirements for the verify view."""

    def test_verify_view_redirects_anonymous_user(self) -> None:
        """Anonymous users are redirected to login."""
        response = self.client.get(VERIFY_URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_action_view_redirects_anonymous_user(self) -> None:
        """Anonymous POST to action endpoint redirects to login."""
        response = self.client.post(ACTION_URL, {"action": "verify", "link_id": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)


class VerifySocialLinkEmptyTestCase(TestCase):
    """Behaviour when no unverified links exist."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="testuser")
        self.client.force_login(self.user)

    def test_empty_state_when_no_links_exist(self) -> None:
        """Shows 'all verified' message when no PerformerSocialLinks exist."""
        response = self.client.get(VERIFY_URL)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["link"])
        self.assertContains(response, "All links verified")

    def test_empty_state_when_all_links_verified(self) -> None:
        """Shows 'all verified' when every link has verified_datetime set."""
        performer = _create_performer("AllVerifiedBand")
        PerformerSocialLink.objects.create(
            performer=performer,
            platform="youtube",
            url="https://youtube.com/@allverified",
            verified_datetime=timezone.now(),
        )

        response = self.client.get(VERIFY_URL)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["link"])


class VerifySocialLinkDisplayTestCase(TestCase):
    """Rendering of unverified link data on the page."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="testuser")
        self.client.force_login(self.user)

        self.performer = _create_performer("DisplayBand")
        self.link = PerformerSocialLink.objects.create(
            performer=self.performer,
            platform="youtube",
            url="https://youtube.com/@displayband",
        )

    def test_displays_performer_id(self) -> None:
        response = self.client.get(VERIFY_URL)
        self.assertContains(response, str(self.performer.id))

    def test_displays_performer_name(self) -> None:
        response = self.client.get(VERIFY_URL)
        self.assertContains(response, self.performer.name)

    def test_displays_platform(self) -> None:
        response = self.client.get(VERIFY_URL)
        self.assertContains(response, "youtube")

    def test_displays_url_as_clickable_link(self) -> None:
        response = self.client.get(VERIFY_URL)
        self.assertContains(response, 'href="https://youtube.com/@displayband"')
        self.assertContains(response, 'target="_blank"')
        self.assertContains(response, 'class="url-open-link"')

    def test_displays_copy_name_button(self) -> None:
        response = self.client.get(VERIFY_URL)
        self.assertContains(response, 'id="copy-name-btn"')

    def test_displays_editable_url_input(self) -> None:
        response = self.client.get(VERIFY_URL)
        self.assertContains(response, 'name="platform_url"')
        self.assertContains(response, 'value="https://youtube.com/@displayband"')

    def test_displays_verify_button(self) -> None:
        response = self.client.get(VERIFY_URL)
        self.assertContains(response, 'value="verify"')
        self.assertContains(response, "Verify")

    def test_no_clickable_link_when_url_empty(self) -> None:
        self.link.url = ""
        self.link.save()

        response = self.client.get(VERIFY_URL)
        self.assertNotContains(response, 'href="https://youtube.com/@displayband"')

    def test_displays_youtube_search_link(self) -> None:
        response = self.client.get(VERIFY_URL)
        self.assertContains(response, "search_query=%22DisplayBand%22+%E3%83%90%E3%83%B3%E3%83%89")

    def test_no_youtube_search_link_for_other_platforms(self) -> None:
        self.link.platform = "twitter"
        self.link.save()

        response = self.client.get(VERIFY_URL)
        self.assertNotContains(response, "search_query=")

    def test_displays_progress_counter(self) -> None:
        response = self.client.get(VERIFY_URL)
        self.assertContains(response, "1 / 1 unverified")


class VerifySocialLinkOrderingTestCase(TestCase):
    """Links are displayed in performer name + platform order."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="testuser")
        self.client.force_login(self.user)

        # Create performers in non-alphabetical order
        self.performer_b = _create_performer("BetaBand")
        self.performer_a = _create_performer("AlphaBand")

        # Create links: AlphaBand-instagram, AlphaBand-youtube, BetaBand-twitter
        self.link_a_instagram = PerformerSocialLink.objects.create(
            performer=self.performer_a,
            platform="instagram",
            url="https://instagram.com/alpha",
        )
        self.link_a_youtube = PerformerSocialLink.objects.create(
            performer=self.performer_a,
            platform="youtube",
            url="https://youtube.com/@alpha",
        )
        self.link_b_twitter = PerformerSocialLink.objects.create(
            performer=self.performer_b,
            platform="twitter",
            url="https://twitter.com/beta",
        )

    def test_first_item_is_alphabetically_first(self) -> None:
        """Index 0 shows AlphaBand instagram (first by name, then platform)."""
        response = self.client.get(VERIFY_URL)

        self.assertEqual(response.context["link"].id, self.link_a_instagram.id)

    def test_second_item_is_same_performer_next_platform(self) -> None:
        """Index 1 shows AlphaBand youtube."""
        response = self.client.get(f"{VERIFY_URL}?index=1")

        self.assertEqual(response.context["link"].id, self.link_a_youtube.id)

    def test_third_item_is_next_performer(self) -> None:
        """Index 2 shows BetaBand twitter."""
        response = self.client.get(f"{VERIFY_URL}?index=2")

        self.assertEqual(response.context["link"].id, self.link_b_twitter.id)

    def test_progress_counter_reflects_total(self) -> None:
        response = self.client.get(VERIFY_URL)
        self.assertContains(response, "1 / 3 unverified")


class VerifySocialLinkSkipTestCase(TestCase):
    """Skip button navigation behaviour."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="testuser")
        self.client.force_login(self.user)

        self.performer = _create_performer("NavBand")

    def test_skip_button_shown_when_next_exists(self) -> None:
        """Skip button is rendered when there is a next unverified link."""
        PerformerSocialLink.objects.create(performer=self.performer, platform="twitter", url="https://twitter.com/nav")
        PerformerSocialLink.objects.create(performer=self.performer, platform="youtube", url="https://youtube.com/@nav")

        response = self.client.get(VERIFY_URL)
        self.assertContains(response, 'class="btn-skip"')
        self.assertContains(response, "?index=1")

    def test_skip_button_hidden_on_last_item(self) -> None:
        """Skip button is not rendered on the last unverified link."""
        PerformerSocialLink.objects.create(
            performer=self.performer, platform="youtube", url="https://youtube.com/@only"
        )

        response = self.client.get(VERIFY_URL)
        self.assertNotContains(response, 'class="btn-skip"')

    def test_skip_button_hidden_when_on_last_index(self) -> None:
        """Skip button hidden when viewing the last item via index param."""
        PerformerSocialLink.objects.create(performer=self.performer, platform="twitter", url="https://twitter.com/a")
        PerformerSocialLink.objects.create(performer=self.performer, platform="youtube", url="https://youtube.com/@b")

        response = self.client.get(f"{VERIFY_URL}?index=1")
        self.assertNotContains(response, 'class="btn-skip"')


class VerifySocialLinkIndexTestCase(TestCase):
    """Index query parameter edge cases."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="testuser")
        self.client.force_login(self.user)

        self.performer = _create_performer("IndexBand")
        self.link = PerformerSocialLink.objects.create(
            performer=self.performer, platform="youtube", url="https://youtube.com/@index"
        )

    def test_negative_index_clamps_to_zero(self) -> None:
        response = self.client.get(f"{VERIFY_URL}?index=-5")
        self.assertEqual(response.context["current_index"], 0)
        self.assertEqual(response.context["link"].id, self.link.id)

    def test_out_of_range_index_clamps_to_last(self) -> None:
        response = self.client.get(f"{VERIFY_URL}?index=999")
        self.assertEqual(response.context["current_index"], 0)  # only 1 item, so max is 0

    def test_non_numeric_index_defaults_to_zero(self) -> None:
        response = self.client.get(f"{VERIFY_URL}?index=abc")
        self.assertEqual(response.context["current_index"], 0)

    def test_missing_index_defaults_to_zero(self) -> None:
        response = self.client.get(VERIFY_URL)
        self.assertEqual(response.context["current_index"], 0)


class VerifyActionTestCase(TestCase):
    """Verify action saves URL and sets verified_datetime."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="testuser")
        self.client.force_login(self.user)

        self.performer = _create_performer("VerifyBand")
        self.link = PerformerSocialLink.objects.create(
            performer=self.performer,
            platform="youtube",
            url="https://youtube.com/@original",
        )

    def test_verify_sets_verified_datetime(self) -> None:
        """Clicking verify sets verified_datetime to a non-null value."""
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "verify",
                "platform_url": self.link.url,
                "current_index": "0",
            },
        )

        self.link.refresh_from_db()
        self.assertIsNotNone(self.link.verified_datetime)

    def test_verify_saves_edited_url(self) -> None:
        """Verify saves the user-edited URL value."""
        new_url = "https://youtube.com/@edited"
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "verify",
                "platform_url": new_url,
                "current_index": "0",
            },
        )

        self.link.refresh_from_db()
        self.assertEqual(self.link.url, new_url)
        self.assertIsNotNone(self.link.verified_datetime)

    def test_verify_preserves_original_url_when_field_unchanged(self) -> None:
        """URL stays the same when user submits without editing."""
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "verify",
                "platform_url": "https://youtube.com/@original",
                "current_index": "0",
            },
        )

        self.link.refresh_from_db()
        self.assertEqual(self.link.url, "https://youtube.com/@original")
        self.assertIsNotNone(self.link.verified_datetime)

    def test_verify_redirects_to_same_index(self) -> None:
        """After verify, redirects to same index so next item shifts in."""
        response = self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "verify",
                "platform_url": self.link.url,
                "current_index": "3",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("index=3", response.url)

    def test_verify_removes_link_from_unverified_list(self) -> None:
        """After verification, the link no longer appears in the unverified queue."""
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "verify",
                "platform_url": self.link.url,
                "current_index": "0",
            },
        )

        response = self.client.get(VERIFY_URL)
        self.assertIsNone(response.context["link"])

    def test_verify_with_empty_url_keeps_existing(self) -> None:
        """If the URL field is submitted empty, the original URL is preserved."""
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "verify",
                "platform_url": "",
                "current_index": "0",
            },
        )

        self.link.refresh_from_db()
        self.assertEqual(self.link.url, "https://youtube.com/@original")
        self.assertIsNotNone(self.link.verified_datetime)

    def test_verify_nonexistent_link_redirects(self) -> None:
        """Verify with an invalid link_id redirects without error."""
        response = self.client.post(
            ACTION_URL,
            {
                "link_id": "99999",
                "action": "verify",
                "platform_url": "https://example.com",
                "current_index": "0",
            },
        )

        self.assertEqual(response.status_code, 302)

    def test_get_request_to_action_redirects(self) -> None:
        """GET request to the action endpoint redirects to the verify view."""
        response = self.client.get(ACTION_URL)

        self.assertEqual(response.status_code, 302)
        self.assertIn(VERIFY_URL, response.url)

    def test_unknown_action_redirects(self) -> None:
        """Unknown action value redirects back to verify view."""
        response = self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "unknown",
                "current_index": "0",
            },
        )

        self.assertEqual(response.status_code, 302)


class DeletePerformerTestCase(TestCase):
    """Delete performer action from the verify page."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="testuser")
        self.client.force_login(self.user)

        self.performer = _create_performer("DeleteMe")
        self.link = PerformerSocialLink.objects.create(
            performer=self.performer,
            platform="youtube",
            url="https://youtube.com/@deleteme",
        )

    def test_delete_removes_performer(self) -> None:
        """Delete action removes the performer from the database."""
        performer_id = self.performer.id
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "delete_performer",
                "current_index": "0",
            },
        )

        self.assertFalse(Performer.objects.filter(id=performer_id).exists())

    def test_delete_cascades_to_social_links(self) -> None:
        """Deleting performer also removes its social links."""
        link_id = self.link.id
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "delete_performer",
                "current_index": "0",
            },
        )

        self.assertFalse(PerformerSocialLink.objects.filter(id=link_id).exists())

    def test_delete_redirects_to_same_index(self) -> None:
        """After delete, redirects to same index so next item shifts in."""
        response = self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "delete_performer",
                "current_index": "2",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("index=2", response.url)

    def test_delete_button_displayed(self) -> None:
        """Delete performer button is rendered on the page."""
        response = self.client.get(VERIFY_URL)
        self.assertContains(response, 'value="delete_performer"')
        self.assertContains(response, "Delete Performer")

    def test_delete_shows_empty_state_when_last(self) -> None:
        """Deleting the only performer shows empty state."""
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "delete_performer",
                "current_index": "0",
            },
        )

        response = self.client.get(VERIFY_URL)
        self.assertIsNone(response.context["link"])

    def test_delete_does_not_affect_other_performers(self) -> None:
        """Deleting one performer leaves others intact."""
        other = _create_performer("KeepMe")
        PerformerSocialLink.objects.create(performer=other, platform="twitter", url="https://twitter.com/keepme")

        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "delete_performer",
                "current_index": "0",
            },
        )

        self.assertTrue(Performer.objects.filter(id=other.id).exists())

        response = self.client.get(VERIFY_URL)
        self.assertEqual(response.context["link"].performer.id, other.id)


class DeleteSocialLinkTestCase(TestCase):
    """Delete social link action from the verify page."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="testuser")
        self.client.force_login(self.user)

        self.performer = _create_performer("LinkDeleteBand")
        self.link = PerformerSocialLink.objects.create(
            performer=self.performer,
            platform="youtube",
            url="https://youtube.com/@linkdelete",
        )

    def test_delete_removes_social_link(self) -> None:
        """Delete action removes the social link from the database."""
        link_id = self.link.id
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "delete_social_link",
                "current_index": "0",
            },
        )

        self.assertFalse(PerformerSocialLink.objects.filter(id=link_id).exists())

    def test_delete_preserves_performer(self) -> None:
        """Deleting a social link does not delete the performer."""
        performer_id = self.performer.id
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "delete_social_link",
                "current_index": "0",
            },
        )

        self.assertTrue(Performer.objects.filter(id=performer_id).exists())

    def test_delete_redirects_to_same_index(self) -> None:
        """After delete, redirects to same index so next item shifts in."""
        response = self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "delete_social_link",
                "current_index": "2",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("index=2", response.url)

    def test_delete_button_displayed(self) -> None:
        """Delete social link button is rendered on the page."""
        response = self.client.get(VERIFY_URL)
        self.assertContains(response, 'value="delete_social_link"')
        self.assertContains(response, "Delete Social Link")

    def test_delete_does_not_affect_other_links(self) -> None:
        """Deleting one social link leaves the performer's other links intact."""
        other_link = PerformerSocialLink.objects.create(
            performer=self.performer, platform="twitter", url="https://twitter.com/linkdelete"
        )

        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "delete_social_link",
                "current_index": "0",
            },
        )

        self.assertTrue(PerformerSocialLink.objects.filter(id=other_link.id).exists())

    def test_delete_removes_performer_songs(self) -> None:
        """Deleting a social link also removes the performer's songs."""
        song = PerformerSong.objects.create(
            performer=self.performer,
            title="Delete Me Song",
            youtube_video_id="del123",
            youtube_url="https://youtube.com/watch?v=del123",
        )

        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link.id,
                "action": "delete_social_link",
                "current_index": "0",
            },
        )

        self.assertFalse(PerformerSong.objects.filter(id=song.id).exists())


class VerifyMultipleLinksTestCase(TestCase):
    """Workflow with multiple unverified links."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="testuser")
        self.client.force_login(self.user)

        self.performer_a = _create_performer("AlphaMulti")
        self.performer_b = _create_performer("BetaMulti")

        self.link1 = PerformerSocialLink.objects.create(
            performer=self.performer_a,
            platform="youtube",
            url="https://youtube.com/@alpha",
        )
        self.link2 = PerformerSocialLink.objects.create(
            performer=self.performer_b,
            platform="youtube",
            url="https://youtube.com/@beta",
        )

    def test_verifying_first_shows_second_at_same_index(self) -> None:
        """After verifying the first link, index 0 now shows the second."""
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link1.id,
                "action": "verify",
                "platform_url": self.link1.url,
                "current_index": "0",
            },
        )

        response = self.client.get(f"{VERIFY_URL}?index=0")
        self.assertEqual(response.context["link"].id, self.link2.id)

    def test_verifying_all_links_shows_empty_state(self) -> None:
        """After verifying all links, page shows all-verified message."""
        for link in [self.link1, self.link2]:
            self.client.post(
                ACTION_URL,
                {
                    "link_id": link.id,
                    "action": "verify",
                    "platform_url": link.url,
                    "current_index": "0",
                },
            )

        response = self.client.get(VERIFY_URL)
        self.assertIsNone(response.context["link"])
        self.assertContains(response, "All links verified")

    def test_progress_counter_decreases_after_verify(self) -> None:
        """Total count decreases as links are verified."""
        response = self.client.get(VERIFY_URL)
        self.assertContains(response, "1 / 2 unverified")

        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link1.id,
                "action": "verify",
                "platform_url": self.link1.url,
                "current_index": "0",
            },
        )

        response = self.client.get(VERIFY_URL)
        self.assertContains(response, "1 / 1 unverified")

    def test_skip_then_verify_second(self) -> None:
        """Skip first link, verify second, first still shows as unverified."""
        # Skip to index 1 and verify
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.link2.id,
                "action": "verify",
                "platform_url": self.link2.url,
                "current_index": "1",
            },
        )

        # First link should still be unverified
        self.link1.refresh_from_db()
        self.assertIsNone(self.link1.verified_datetime)

        # Page should now show only the first link
        response = self.client.get(VERIFY_URL)
        self.assertEqual(response.context["link"].id, self.link1.id)
        self.assertContains(response, "1 / 1 unverified")


class VerifyTriggersYouTubeSearchTestCase(TestCase):
    """YouTube video search is triggered when a YouTube link is verified."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="testuser")
        self.client.force_login(self.user)

        self.performer = _create_performer("SearchBand")
        self.youtube_link = PerformerSocialLink.objects.create(
            performer=self.performer,
            platform="youtube",
            url="https://youtube.com/@searchband",
        )
        self.twitter_link = PerformerSocialLink.objects.create(
            performer=self.performer,
            platform="twitter",
            url="https://twitter.com/searchband",
        )

    @patch("performers.views.search_and_create_performer_songs")
    def test_verify_youtube_triggers_video_search(self, mock_search: MagicMock) -> None:
        """Verifying a YouTube link triggers search_and_create_performer_songs."""
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.youtube_link.id,
                "action": "verify",
                "platform_url": self.youtube_link.url,
                "current_index": "0",
            },
        )

        mock_search.assert_called_once_with(self.performer)

    @patch("performers.views.search_and_create_performer_songs")
    def test_verify_non_youtube_does_not_trigger_search(self, mock_search: MagicMock) -> None:
        """Verifying a non-YouTube link does not trigger video search."""
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.twitter_link.id,
                "action": "verify",
                "platform_url": self.twitter_link.url,
                "current_index": "0",
            },
        )

        mock_search.assert_not_called()

    @patch("performers.views.search_and_create_performer_songs", side_effect=Exception("API error"))
    def test_youtube_search_failure_does_not_block_verification(self, mock_search: MagicMock) -> None:
        """Verification succeeds even if YouTube search raises an exception."""
        self.client.post(
            ACTION_URL,
            {
                "link_id": self.youtube_link.id,
                "action": "verify",
                "platform_url": self.youtube_link.url,
                "current_index": "0",
            },
        )

        self.youtube_link.refresh_from_db()
        self.assertIsNotNone(self.youtube_link.verified_datetime)

    @patch("performers.views.search_and_create_performer_songs")
    def test_verify_youtube_deletes_existing_songs(self, mock_search: MagicMock) -> None:
        """Existing songs are deleted before YouTube search on verification."""
        PerformerSong.objects.create(
            performer=self.performer,
            title="Old Song",
            youtube_video_id="old123",
            youtube_url="https://youtube.com/watch?v=old123",
        )

        self.client.post(
            ACTION_URL,
            {
                "link_id": self.youtube_link.id,
                "action": "verify",
                "platform_url": self.youtube_link.url,
                "current_index": "0",
            },
        )

        self.assertFalse(PerformerSong.objects.filter(performer=self.performer).exists())
        mock_search.assert_called_once()

    @patch("performers.views.search_and_create_performer_songs")
    def test_verify_non_youtube_does_not_delete_songs(self, mock_search: MagicMock) -> None:
        """Verifying a non-YouTube link does not delete existing songs."""
        song = PerformerSong.objects.create(
            performer=self.performer,
            title="Keep This Song",
            youtube_video_id="keep123",
            youtube_url="https://youtube.com/watch?v=keep123",
        )

        self.client.post(
            ACTION_URL,
            {
                "link_id": self.twitter_link.id,
                "action": "verify",
                "platform_url": self.twitter_link.url,
                "current_index": "0",
            },
        )

        self.assertTrue(PerformerSong.objects.filter(id=song.id).exists())
