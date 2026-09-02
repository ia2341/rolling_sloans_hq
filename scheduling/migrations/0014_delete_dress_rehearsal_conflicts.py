from django.db import migrations


def delete_dress_rehearsal_conflicts(apps, schema_editor):
    """Delete Conflicts (and their cascading ConflictWindows) pointing at a Dress Rehearsal.

    Rows predating ADR-0006's mandatory-attendance rule are now
    unreachable from /me/conflicts/ — the Dress Rehearsal no longer
    appears in Upcoming Rehearsals — so they could be neither read as
    the domain now expects nor fixed through the UI.
    """
    Conflict = apps.get_model('scheduling', 'Conflict')
    Conflict.objects.filter(rehearsal__is_full_setlist=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('scheduling', '0013_conflict_reason'),
    ]

    operations = [
        migrations.RunPython(delete_dress_rehearsal_conflicts, migrations.RunPython.noop),
    ]
