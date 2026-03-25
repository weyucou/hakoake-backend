import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from .models import PerformerSocialLink
from .youtube_search import search_and_create_performer_songs

logger = logging.getLogger(__name__)


def _get_unverified_links() -> QuerySet[PerformerSocialLink]:
    """Return unverified PerformerSocialLinks in list order."""
    return (
        PerformerSocialLink.objects.filter(
            verified_datetime__isnull=True,
        )
        .select_related("performer")
        .order_by("performer__name", "platform")
    )


@login_required
def verify_social_link_view(request: HttpRequest) -> HttpResponse:
    """Display a single unverified PerformerSocialLink for verification."""
    unverified = _get_unverified_links()

    if not unverified.exists():
        return render(request, "performers/verify_social_link.html", {"link": None})

    # Get current link index from query param (default to first)
    try:
        current_index = int(request.GET.get("index", 0))
    except (ValueError, TypeError):
        current_index = 0

    total = unverified.count()
    current_index = max(0, min(current_index, total - 1))

    link = unverified[current_index]
    has_next = current_index + 1 < total

    context = {
        "link": link,
        "current_index": current_index,
        "has_next": has_next,
        "next_index": current_index + 1 if has_next else None,
        "total": total,
        "position": current_index + 1,
    }
    return render(request, "performers/verify_social_link.html", context)


def _handle_verify(request: HttpRequest, link: PerformerSocialLink, current_index: str) -> HttpResponse:
    """Handle the 'verify' action: update name, URL, and mark as verified."""
    new_name = request.POST.get("performer_name", "").strip()
    if new_name and new_name != link.performer.name:
        try:
            link.performer.name = new_name
            link.performer.save()
        except IntegrityError:
            messages.error(request, f"A performer named '{new_name}' already exists.")
            return redirect(f"/performers/verify/?index={current_index}")

    # Save edited URL (user may have changed it) and mark as verified
    new_url = request.POST.get("platform_url", "").strip()
    if new_url:
        link.url = new_url
    link.is_label = request.POST.get("is_label") == "on"
    link.verified_datetime = timezone.now()
    link.save()

    # Delete existing songs and re-search when a YouTube link is verified
    if link.platform == "youtube":
        try:
            link.performer.songs.all().delete()
            search_and_create_performer_songs(link.performer)
        except Exception:  # noqa: BLE001
            logger.exception(f"Failed to search YouTube for {link.performer.name}")

    return redirect(f"/performers/verify/?index={current_index}")


def _handle_delete_social_link(link: PerformerSocialLink, current_index: str) -> HttpResponse:
    """Handle the 'delete_social_link' action: delete songs and the link."""
    link.performer.songs.all().delete()
    link.delete()
    return redirect(f"/performers/verify/?index={current_index}")


def _handle_delete_performer(link: PerformerSocialLink, current_index: str) -> HttpResponse:
    """Handle the 'delete_performer' action: delete the entire performer."""
    link.performer.delete()
    return redirect(f"/performers/verify/?index={current_index}")


@login_required
def verify_social_link_action(request: HttpRequest) -> HttpResponse:
    """Handle verify and update actions for a PerformerSocialLink."""
    if request.method != "POST":
        return redirect("performers:verify_social_link")

    link_id = request.POST.get("link_id")
    current_index = request.POST.get("current_index", "0")

    try:
        link = PerformerSocialLink.objects.get(id=link_id)
    except PerformerSocialLink.DoesNotExist:
        return redirect("performers:verify_social_link")

    action = request.POST.get("action")
    if action == "verify":
        return _handle_verify(request, link, current_index)
    if action == "delete_social_link":
        return _handle_delete_social_link(link, current_index)
    if action == "delete_performer":
        return _handle_delete_performer(link, current_index)

    return redirect("performers:verify_social_link")
