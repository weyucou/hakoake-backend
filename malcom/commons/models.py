from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

NAME_READING_FIELDS = ("name_kana", "name_romaji")


def blank_name_reading_errors(instance: models.Model) -> dict:
    """Return a ValidationError message dict for each blank name_kana / name_romaji field."""
    return {
        field: _("This field must not be blank.")
        for field in NAME_READING_FIELDS
        if not (getattr(instance, field) or "").strip()
    }


class TimestampedModel(models.Model):
    created_datetime = models.DateTimeField(auto_now_add=True, editable=False)
    updated_datetime = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True


class UserTimestampedModel(TimestampedModel):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        editable=False,
        related_name="%(app_label)s_%(class)s_created_by",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        editable=False,
        related_name="%(app_label)s_%(class)s_updated_by",
    )

    class Meta:
        abstract = True
