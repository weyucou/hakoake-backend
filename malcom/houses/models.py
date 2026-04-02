from commons.models import TimestampedModel
from django.db import models
from performers.models import Performer

from .definitions import CrawlerCollectionState, WebsiteProcessingState


class LiveHouseWebsite(TimestampedModel):
    url = models.URLField(max_length=255, unique=True, blank=False, null=False)
    schedule_url = models.URLField(max_length=255, blank=True, default="")
    state = models.CharField(
        choices=WebsiteProcessingState.choices(), default=WebsiteProcessingState.NOT_STARTED, max_length=20
    )
    crawler_class = models.CharField(max_length=100, blank=True, default="")


class LiveHouse(TimestampedModel):
    """A model representing a live house."""

    website = models.ForeignKey(LiveHouseWebsite, on_delete=models.CASCADE, related_name="live_houses")
    name = models.CharField(max_length=255, unique=True)
    name_kana = models.CharField(max_length=255, unique=True)
    name_romaji = models.CharField(max_length=255, unique=True)
    phone_number = models.CharField(max_length=20, blank=True, default="", null=False)
    address = models.CharField(max_length=255)
    capacity = models.PositiveIntegerField()
    opened_date = models.DateField()
    closed_date = models.DateField(null=True, default=None)  # noqa: DJ001
    last_collected_datetime = models.DateTimeField(null=True, blank=True)  # noqa: DJ001
    last_collection_state = models.CharField(
        choices=CrawlerCollectionState.choices(), default=CrawlerCollectionState.PENDING, max_length=20
    )

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = "Live House"
        verbose_name_plural = "Live Houses"
        ordering = ["name"]


class PerformanceSchedule(models.Model):
    """A model representing a performance schedule at a live house."""

    live_house = models.ForeignKey(LiveHouse, on_delete=models.CASCADE, related_name="performance_schedules")
    performance_name = models.CharField(max_length=255, blank=True, null=False, default="")
    performance_date = models.DateField()
    open_time = models.TimeField(blank=True, null=True)  # noqa: DJ001
    start_time = models.TimeField(blank=True, null=True)  # noqa: DJ001
    presale_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)  # noqa: DJ001
    door_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)  # noqa: DJ001
    performers = models.ManyToManyField(Performer, related_name="performance_schedules", blank=True)
    event_image = models.ImageField(
        upload_to="schedules/event_images/",
        blank=True,
        null=True,
        help_text="Event flyer or promotional image",
    )

    def __str__(self) -> str:
        return f"{self.live_house.name} - {self.performance_date} {self.start_time}"

    def save(self, *args, **kwargs):  # noqa: ANN002, ANN003
        """Save the performance schedule with cleaned performance name."""
        # Clean performance_name - strip whitespace and trailing slashes/backslashes
        if self.performance_name:
            self.performance_name = self.performance_name.strip().rstrip("/\\")
        super().save(*args, **kwargs)

    class Meta:  # noqa: DJ012
        verbose_name = "Performance Schedule"
        verbose_name_plural = "Performance Schedules"
        ordering = ["performance_date", "start_time"]


class PerformanceScheduleTicketPurchaseInfo(TimestampedModel):
    """A model representing ticket purchase information for a performance schedule."""

    performance = models.OneToOneField(
        PerformanceSchedule, on_delete=models.CASCADE, related_name="ticket_purchase_info"
    )
    ticket_contact_email = models.EmailField(max_length=255, blank=True, null=True)  # noqa: DJ001
    ticket_contact_phone = models.CharField(max_length=20, blank=True, null=True)  # noqa: DJ001
    ticket_url = models.URLField(max_length=255, blank=True)
    ticket_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)  # noqa: DJ001
    ticket_sales_start_date = models.DateTimeField(blank=True, null=True)  # noqa: DJ001
    ticket_sales_end_date = models.DateTimeField(blank=True, null=True)  # noqa: DJ001

    def __str__(self) -> str:
        return f"Ticket Info for {self.performance}"

    def get_ticket_service_info(self):  # noqa: PLR0911
        """Return ticket service name and icon based on URL."""
        if not self.ticket_url:
            return None, None

        url = str(self.ticket_url).lower()

        if "peatix.com" in url:
            return "Peatix", "fas fa-ticket-alt"
        if "eventbrite.com" in url or "eventbrite.co.jp" in url:
            return "Eventbrite", "fas fa-calendar-check"
        if "tiget.net" in url:
            return "tiget", "fas fa-ticket-alt"
        if "e-plus.jp" in url or "eplus.jp" in url:
            return "e+", "fas fa-plus-circle"
        if "pia.jp" in url or "pia.co.jp" in url:
            return "チケットぴあ", "fas fa-ticket-alt"
        if "lawson" in url or "l-tike" in url:
            return "ローソンチケット", "fas fa-store"
        if "cnplayguide" in url:
            return "CNプレイガイド", "fas fa-play"
        if "ticketport" in url:
            return "チケットポート", "fas fa-ship"
        if "livepocket" in url:
            return "LivePocket", "fas fa-mobile-alt"
        if "zaiko.io" in url:
            return "ZAIKO", "fas fa-video"
        return "チケット購入", "fas fa-external-link-alt"


class MonthlyPlaylist(TimestampedModel):
    date = models.DateField(verbose_name="target date", unique=True)
    youtube_playlist_id = models.CharField(max_length=100, blank=True, default="")
    youtube_playlist_url = models.URLField(max_length=500, blank=True, default="")
    youtube_channel_url = models.URLField(max_length=500, blank=True, default="")


class MonthlyPlaylistEntry(TimestampedModel):
    playlist = models.ForeignKey(MonthlyPlaylist, on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=1)
    song = models.ForeignKey("performers.PerformerSong", on_delete=models.CASCADE)
    is_spotlight = models.BooleanField(default=False)

    class Meta:
        unique_together = ("playlist", "position")

    def save(self, *args, **kwargs):  # noqa: ANN002, ANN003
        # Only auto-increment position for new entries without an explicit position
        if not self.pk and self.position == 1:  # position defaults to 1, so only auto-increment if it's still default
            # get latest position
            latest_entry = MonthlyPlaylistEntry.objects.filter(playlist=self.playlist).order_by("-position").first()
            if latest_entry:
                self.position = latest_entry.position + 1
        super().save(*args, **kwargs)


class WeeklyPlaylist(TimestampedModel):
    date = models.DateField(verbose_name="target date", unique=True)
    youtube_playlist_id = models.CharField(max_length=100, blank=True, default="")
    youtube_playlist_url = models.URLField(max_length=500, blank=True, default="")
    youtube_channel_url = models.URLField(max_length=500, blank=True, default="")


class WeeklyPlaylistEntry(TimestampedModel):
    playlist = models.ForeignKey(WeeklyPlaylist, on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=1)
    song = models.ForeignKey("performers.PerformerSong", on_delete=models.CASCADE)
    is_spotlight = models.BooleanField(default=False)

    class Meta:
        unique_together = ("playlist", "position")

    def save(self, *args, **kwargs):  # noqa: ANN002, ANN003
        # Only auto-increment position for new entries without an explicit position
        if not self.pk and self.position == 1:  # position defaults to 1, so only auto-increment if it's still default
            # get latest position
            latest_entry = WeeklyPlaylistEntry.objects.filter(playlist=self.playlist).order_by("-position").first()
            if latest_entry:
                self.position = latest_entry.position + 1
        super().save(*args, **kwargs)
