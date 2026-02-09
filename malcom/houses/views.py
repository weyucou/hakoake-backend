from datetime import datetime, timedelta

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from performers.models import Performer

from .models import LiveHouse, PerformanceSchedule


def get_month_urls() -> list[dict[str, str]]:
    """Generate URLs for current and next 12 months for distill."""
    urls = []
    current_date = timezone.now().date()

    for i in range(12):
        month_date = current_date + timedelta(days=30 * i)
        urls.append({"year": month_date.year, "month": month_date.month})

    return urls


def performance_schedule_view(request: HttpRequest, year: int, month: int) -> HttpResponse:
    """View for displaying performance schedules for a specific month."""
    # Validate month and year
    if not (1 <= month <= 12) or year < 1900 or year > 3000:  # noqa: PLR2004
        raise Http404(f"Invalid month: {year}/{month}")  # noqa: B904

    try:
        # Get performances for the specified month
        performances = (
            PerformanceSchedule.objects.filter(performance_date__year=year, performance_date__month=month)
            .select_related("live_house")
            .prefetch_related("performers__social_links")
            .order_by("performance_date", "start_time")
        )

        # Group performances by date
        performances_by_date = {}
        for performance in performances:
            date_key = performance.performance_date
            if date_key not in performances_by_date:
                performances_by_date[date_key] = []
            performances_by_date[date_key].append(performance)

        # Calculate navigation months
        current_month = datetime(year, month, 1).date()  # noqa: DTZ001
        prev_month = (current_month - timedelta(days=1)).replace(day=1)
        next_month = (current_month + timedelta(days=32)).replace(day=1)

        # Check if previous month has performances
        has_prev_month = PerformanceSchedule.objects.filter(
            performance_date__year=prev_month.year, performance_date__month=prev_month.month
        ).exists()

        # Check if next month has performances
        has_next_month = PerformanceSchedule.objects.filter(
            performance_date__year=next_month.year, performance_date__month=next_month.month
        ).exists()

        context = {
            "performances_by_date": performances_by_date,
            "current_month": current_month,
            "prev_month": prev_month if has_prev_month else None,
            "next_month": next_month if has_next_month else None,
            "month_name": current_month.strftime("%Y年%m月"),
            "total_performances": len(performances),
            "total_venues": len(set(p.live_house for p in performances)),
            "total_performers": len(set(performer for p in performances for performer in p.performers.all())),
        }

        return render(request, "houses/schedule.html", context)

    except ValueError:
        raise Http404(f"Invalid date: {year}/{month}")  # noqa: B904


def current_month_view(request: HttpRequest) -> HttpResponse:
    """Redirect to current month's schedule."""
    now = timezone.now()
    return performance_schedule_view(request, now.year, now.month)


def performer_detail_view(request: HttpRequest, performer_id: int) -> HttpResponse:
    """View for displaying performer details."""
    try:
        performer = Performer.objects.get(id=performer_id)

        # Get upcoming performances for this performer
        upcoming_performances = (
            PerformanceSchedule.objects.filter(performers=performer, performance_date__gte=timezone.now().date())
            .select_related("live_house")
            .order_by("performance_date", "start_time")[:10]
        )

        # Get social links
        social_links = performer.social_links.all()

        context = {
            "performer": performer,
            "upcoming_performances": upcoming_performances,
            "social_links": social_links,
        }

        return render(request, "performers/detail.html", context)

    except Performer.DoesNotExist:  # noqa: DJ012
        raise Http404("Performer not found")  # noqa: B904


def get_performer_urls() -> list[dict[str, int]]:
    """Generate URLs for all performers for distill."""
    return [{"performer_id": p.id} for p in Performer.objects.all()]


def venue_detail_view(request: HttpRequest, venue_id: int) -> HttpResponse:
    """View for displaying venue/live house details."""
    try:
        live_house = LiveHouse.objects.get(id=venue_id)

        # Get upcoming performances for this venue
        upcoming_performances = (
            PerformanceSchedule.objects.filter(live_house=live_house, performance_date__gte=timezone.now().date())
            .prefetch_related("performers")
            .order_by("performance_date", "start_time")[:20]
        )

        # Get recent past performances (last 10)
        past_performances = (
            PerformanceSchedule.objects.filter(live_house=live_house, performance_date__lt=timezone.now().date())
            .prefetch_related("performers")
            .order_by("-performance_date", "-start_time")[:10]
        )

        # Get all unique performers who have played at this venue
        all_performers = Performer.objects.filter(performance_schedules__live_house=live_house).distinct()[
            :30
        ]  # Limit to avoid too many

        context = {
            "live_house": live_house,
            "upcoming_performances": upcoming_performances,
            "past_performances": past_performances,
            "all_performers": all_performers,
            "total_upcoming": upcoming_performances.count(),
            "total_past": past_performances.count(),
        }

        return render(request, "houses/venue_detail.html", context)

    except LiveHouse.DoesNotExist:  # noqa: DJ012
        raise Http404("Venue not found")  # noqa: B904


def get_venue_urls() -> list[dict[str, int]]:
    """Generate URLs for all venues for distill."""
    return [{"venue_id": v.id} for v in LiveHouse.objects.all()]
