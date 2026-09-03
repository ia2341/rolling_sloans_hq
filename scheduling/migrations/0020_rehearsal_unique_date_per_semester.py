from django.db import migrations, models


def raise_on_duplicate_rehearsal_dates(apps, schema_editor):
    """Refuse to migrate forward if any Semester already has more than one Rehearsal on the same date.

    The incoming UniqueConstraint(semester, date) (issue #214) can't apply
    over data that violates it, and a Rehearsal can carry RehearsalSong,
    Conflict and Recording rows an automatic merge or delete would silently
    destroy — so this reports the problem rather than resolving it. An
    admin must merge or remove the duplicates in the Django admin, then
    re-run this migration.
    """
    Rehearsal = apps.get_model('scheduling', 'Rehearsal')
    duplicates = list(
        Rehearsal.objects.values('semester_id', 'date')
        .annotate(count=models.Count('id'))
        .filter(count__gt=1)
        .order_by('semester_id', 'date')
    )
    if not duplicates:
        return
    summary = ', '.join(
        f'semester {row["semester_id"]} on {row["date"]} ({row["count"]} rows)' for row in duplicates
    )
    raise RuntimeError(
        'Cannot add unique_rehearsal_date_per_semester: existing duplicate Rehearsals found for '
        f'{summary}. Resolve them in the Django admin, then re-run this migration.'
    )


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0019_alter_songrolerequirement_count_and_more'),
    ]

    operations = [
        migrations.RunPython(raise_on_duplicate_rehearsal_dates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='rehearsal',
            constraint=models.UniqueConstraint(fields=['semester', 'date'], name='unique_rehearsal_date_per_semester'),
        ),
    ]
