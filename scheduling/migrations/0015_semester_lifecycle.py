import django.utils.timezone
from django.db import migrations, models


def publish_the_outgoing_current_semester(apps, schema_editor):
    """Publish the one Semester the outgoing `get_current_semester()` returned, leaving every other a draft.

    That function returned the greatest-`id` row, so backfilling
    `published_at` onto exactly that row and nothing else makes deploying
    the lifecycle invisible to members: the Semester they see today stays
    live, and older rows become drafts, which is the honest description of
    rows nobody ever deliberately published (ADR-0010).
    """
    Semester = apps.get_model('scheduling', 'Semester')
    outgoing_current = Semester.objects.order_by('-id').first()
    if outgoing_current is not None:
        Semester.objects.filter(pk=outgoing_current.pk).update(published_at=django.utils.timezone.now())


def unpublish_every_semester(apps, schema_editor):
    """Reverse the backfill by clearing `published_at` everywhere, returning every Semester to a draft."""
    Semester = apps.get_model('scheduling', 'Semester')
    Semester.objects.update(published_at=None)


class Migration(migrations.Migration):
    dependencies = [
        ('scheduling', '0014_delete_dress_rehearsal_conflicts'),
    ]

    operations = [
        migrations.AddField(
            model_name='semester',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='semester',
            name='published_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(publish_the_outgoing_current_semester, unpublish_every_semester),
    ]
