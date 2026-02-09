import re

from commons.models import TimestampedModel
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class Performer(TimestampedModel):
    """A model representing a performer."""

    name = models.CharField(max_length=255, unique=True)
    name_kana = models.CharField(max_length=255, unique=True)
    name_romaji = models.CharField(max_length=255, unique=True)
    phone_number = models.CharField(max_length=20, blank=True, default="", null=False)
    email = models.EmailField(max_length=255, blank=True, default="")
    website = models.URLField(max_length=255, blank=True, default="")
    playlist_weight = models.PositiveIntegerField(
        default=0, help_text="Used to provide weighting to the MonthlyPlaylist selection"
    )
    playlist_weight_update_datetime = models.DateTimeField(
        auto_now_add=True, help_text="Updated when playlist_weight is updated"
    )
    performer_image = models.ImageField(
        upload_to="performers/images/",
        blank=True,
        null=True,
        help_text="Representative performer/band photo",
    )
    logo_image = models.ImageField(
        upload_to="performers/logos/",
        blank=True,
        null=True,
        help_text="Performer/band logo image",
    )
    fanart_image = models.ImageField(
        upload_to="performers/fanart/",
        blank=True,
        null=True,
        help_text="Performer/band fanart image",
    )
    banner_image = models.ImageField(
        upload_to="performers/banners/",
        blank=True,
        null=True,
        help_text="Performer/band banner image",
    )

    def __str__(self) -> str:
        return self.name

    def is_valid_artist_name(self):
        """Check if the performer name indicates they are likely an artist/band."""
        if not self.name:
            return False

        # Common non-artist indicators (case-insensitive)
        non_artist_patterns = [
            r"\b(dj|host|mc|司会|ホスト|ナビゲーター|進行)\b",  # DJs, hosts, MCs
            r"\b(schedule|スケジュール|calendar|カレンダー)\b",  # Schedule-related
            r"\b(staff|スタッフ|管理|admin)\b",  # Staff
            r"\b(guest|ゲスト|客|お客)\b",  # Guests
            r"\b(sound|音響|lighting|照明|tech|技術)\b",  # Technical staff
            r"\b(food|フード|drink|ドリンク|bar|バー)\b",  # Food/drink
            r"\b(ticket|チケット|reservation|予約)\b",  # Ticketing
            r"\b(open|close|開|閉|start|終)\b",  # Time indicators
            r"\b(doors|ドア|entrance|入場|exit|退場)\b",  # Venue operations
            r"^\d+:\d+",  # Time format like "19:00"
            r"^\d+[年月日]",  # Date format
            r"^[¥$]\d+",  # Price format
        ]

        name_lower = self.name.lower()
        for pattern in non_artist_patterns:
            if re.search(pattern, name_lower, re.IGNORECASE):
                return False

        # Must have at least 2 characters and not be purely numeric
        return not (len(self.name.strip()) < 2 or self.name.strip().isdigit())  # noqa: PLR2004

    def has_valid_online_presence(self):
        """Check if performer has valid social media or unique website presence."""
        # Check for social media links (only if performer is saved to database)
        if self.pk and hasattr(self, "social_links") and self.social_links.exists():
            valid_social_platforms = [
                "twitter",
                "instagram",
                "facebook",
                "youtube",
                "bandcamp",
                "soundcloud",
                "spotify",
                "apple_music",
                "tiktok",
                "discord",
                "twitch",
                "reddit",
                "linkedin",
                "vimeo",
                "github",
                "patreon",
                "mastodon",
            ]
            for link in self.social_links.all():
                if link.platform.lower() in valid_social_platforms and link.url:
                    return True

        # Check for unique artist website (not just venue/generic sites)
        if self.website:
            website_lower = str(self.website).lower()

            # Generic/venue sites that don't count as artist presence
            generic_sites = [
                "facebook.com",
                "twitter.com",
                "instagram.com",  # Should be in social links
                "venue.com",
                "livehouse.com",
                "event.com",  # Generic venue sites
                "google.com",
                "yahoo.com",
                "example.com",  # Generic sites
                "localhost",
                "127.0.0.1",  # Test sites
            ]

            # Check if it's a dedicated artist site
            is_generic = any(generic in website_lower for generic in generic_sites)
            if not is_generic and len(website_lower) > 10:  # noqa: PLR2004  # Reasonable URL length
                return True

        return False

    def clean(self):
        """Validate that the performer is a legitimate artist."""
        super().clean()

        # Validate artist name
        if not self.is_valid_artist_name():
            raise ValidationError(  # noqa: B904
                {
                    "name": _(
                        "Name does not appear to be a valid artist/band name. "
                        "Please ensure this is an actual performer and not "
                        "schedule information, venue staff, or other non-artist data."
                    )
                }
            )

        # Note: We can't validate social links here because they might not exist yet
        # This validation will be done in the save method or separately

    def save(self, *args, **kwargs):  # noqa: ANN002, ANN003
        """Save the performer with validation."""
        # Clean name fields - strip whitespace, trailing slashes/backslashes, and "BAND:" prefix
        if self.name:
            self.name = self.name.strip().rstrip("/\\")
            self.name = re.sub(r"^BAND:\s*", "", self.name, flags=re.IGNORECASE)
        if self.name_kana:
            self.name_kana = self.name_kana.strip().rstrip("/\\")
            self.name_kana = re.sub(r"^BAND:\s*", "", self.name_kana, flags=re.IGNORECASE)
        if self.name_romaji:
            self.name_romaji = self.name_romaji.strip().rstrip("/\\")
            self.name_romaji = re.sub(r"^BAND:\s*", "", self.name_romaji, flags=re.IGNORECASE)

        # For new instances, we need to save first then validate social presence
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # For new instances, fetch performer images
        if is_new and not hasattr(self, "_skip_image_fetch"):
            try:
                from .image_fetcher import fetch_and_update_performer_images  # noqa: PLC0415

                fetch_and_update_performer_images(self)
            except Exception as e:  # noqa: BLE001
                # Don't fail performer creation if image fetching fails
                import logging  # noqa: PLC0415

                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to fetch images for {self.name}: {str(e)}")

        # For existing instances or after initial save, validate online presence
        if not is_new or hasattr(self, "_skip_online_validation"):
            # Skip validation if explicitly disabled (useful for data migration)
            pass
        else:
            # For new instances, we'll validate this after social links are potentially added
            # This allows for bulk creation workflows
            pass

    def validate_full_artist_profile(self):
        """Validate that this performer has complete artist validation."""
        errors = []

        if not self.is_valid_artist_name():
            errors.append("Name does not appear to be a valid artist/band name.")

        if not self.has_valid_online_presence():
            errors.append(
                "Performer must have at least one social media account "
                "(Twitter, Instagram, Facebook, YouTube, Bandcamp, SoundCloud, Spotify, Apple Music, "
                "TikTok, Discord, Twitch, Reddit, LinkedIn, Vimeo, GitHub, Patreon, Mastodon) "
                "or a unique artist website."
            )

        if errors:
            raise ValidationError(errors)  # noqa: B904

        return True

    class Meta:
        verbose_name = "Performer"
        verbose_name_plural = "Performers"
        ordering = ["name"]


class PerformerSocialLink(TimestampedModel):
    """A model representing a social link for a performer member."""

    performer = models.ForeignKey(Performer, on_delete=models.CASCADE, related_name="social_links")
    platform = models.CharField(max_length=50)
    platform_id = models.CharField(max_length=255, blank=True, default="")
    url = models.URLField(max_length=255, blank=True, default="")
    verified_datetime = models.DateTimeField(
        blank=True, null=True, default=None, help_text="Date and time when the PerformerSocialLink is verified"
    )

    class Meta:
        unique_together = [("performer", "platform")]


class PerformerMember(TimestampedModel):
    """A model representing a member of a performer."""

    performer = models.ForeignKey(Performer, on_delete=models.CASCADE, related_name="members")
    name = models.CharField(max_length=255)
    roles = models.CharField(max_length=255, blank=True, default="")

    def __str__(self) -> str:
        return f"{self.name} ({self.performer.name})"

    class Meta:
        verbose_name = "Performer Member"
        verbose_name_plural = "Performer Members"
        ordering = ["performer__name", "name"]


class PerformerMemberSocialLink(TimestampedModel):
    """A model representing a social link for a performer member."""

    member = models.ForeignKey(PerformerMember, on_delete=models.CASCADE, related_name="social_links")
    platform = models.CharField(max_length=50)
    platform_id = models.CharField(max_length=255, blank=True, default="")
    url = models.URLField(max_length=255, blank=True, default="")

    def __str__(self) -> str:
        return f"{self.platform} - {self.member.name}"

    class Meta:
        verbose_name = "Performer Member Social Link"
        verbose_name_plural = "Performer Member Social Links"
        ordering = ["member__performer__name", "member__name", "platform"]


class PerformerSong(TimestampedModel):
    """A model representing a song by a performer."""

    performer = models.ForeignKey(Performer, on_delete=models.CASCADE, related_name="songs")
    title = models.CharField(max_length=255)
    release_date = models.DateField(blank=True, null=True)  # noqa: DJ001
    duration = models.DurationField(blank=True, null=True)  # noqa: DJ001
    genre = models.CharField(max_length=100, blank=True, default="")

    # YouTube-specific fields
    youtube_video_id = models.CharField(max_length=20, blank=True, default="")
    youtube_url = models.URLField(max_length=255, blank=True, default="")
    youtube_view_count = models.BigIntegerField(blank=True, null=True)  # noqa: DJ001
    youtube_duration_seconds = models.IntegerField(blank=True, null=True)  # noqa: DJ001

    def save(self, *args, **kwargs):  # noqa: ANN002, ANN003
        """Save the song with cleaned title."""
        # Clean title - strip whitespace and trailing slashes/backslashes
        if self.title:
            self.title = self.title.strip().rstrip("/\\")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.title} by {self.performer.name}"

    class Meta:
        verbose_name = "Performer Song"
        verbose_name_plural = "Performer Songs"
        ordering = ["performer__name", "title"]
