from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("houses", "0010_add_schedule_url_to_livehousewebsite"),
    ]

    operations = [
        migrations.AddField(
            model_name="performanceschedule",
            name="event_image",
            field=models.ImageField(
                blank=True,
                help_text="Event flyer or promotional image",
                null=True,
                upload_to="schedules/event_images/",
            ),
        ),
    ]
