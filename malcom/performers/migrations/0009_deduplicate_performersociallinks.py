"""Data migration to remove duplicate PerformerSocialLink entries.

Keeps the entry with verified_datetime set (preferring most recent),
or the most recently updated entry if none are verified.
"""

from django.db import migrations, models


def deduplicate_social_links(apps, schema_editor):
    PerformerSocialLink = apps.get_model("performers", "PerformerSocialLink")
    db_alias = schema_editor.connection.alias

    from django.db.models import Count

    dupes = (
        PerformerSocialLink.objects.using(db_alias)
        .values("performer_id", "platform")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
    )

    deleted = 0
    for group in dupes:
        links = list(
            PerformerSocialLink.objects.using(db_alias)
            .filter(performer_id=group["performer_id"], platform=group["platform"])
            .order_by(
                # Verified first (nulls last), then most recently updated
                models.F("verified_datetime").desc(nulls_last=True),
                "-updated_datetime",
            )
        )
        # Keep the first (best) entry, delete the rest
        ids_to_delete = [link.id for link in links[1:]]
        count = PerformerSocialLink.objects.using(db_alias).filter(id__in=ids_to_delete).delete()[0]
        deleted += count

    if deleted:
        print(f"\n  Removed {deleted} duplicate PerformerSocialLink entries")


class Migration(migrations.Migration):
    dependencies = [
        ("performers", "0008_performer_fanart_banner_images"),
    ]

    operations = [
        migrations.RunPython(deduplicate_social_links, migrations.RunPython.noop),
    ]
