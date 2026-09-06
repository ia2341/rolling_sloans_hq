# Generated for issue #376: backfill PersonRole from every existing MembershipRole.

from django.db import migrations


def backfill_person_role(apps, schema_editor):
    """Create one PersonRole per distinct (person, role) pair ever declared across any MembershipRole.

    Unions across semesters — a person who declared a Role in any past
    Semester gets exactly one PersonRole row for it, not one per semester
    they declared it in.
    """
    MembershipRole = apps.get_model('scheduling', 'MembershipRole')
    PersonRole = apps.get_model('scheduling', 'PersonRole')

    pairs = MembershipRole.objects.values_list('membership__person_id', 'role_id').distinct()
    PersonRole.objects.bulk_create(
        [PersonRole(person_id=person_id, role_id=role_id) for person_id, role_id in pairs],
        ignore_conflicts=True,
    )


def noop_reverse(apps, schema_editor):
    """No-op reverse: PersonRole rows are re-derivable from MembershipRole, so nothing to undo."""


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0022_personrole'),
    ]

    operations = [
        migrations.RunPython(backfill_person_role, noop_reverse),
    ]
