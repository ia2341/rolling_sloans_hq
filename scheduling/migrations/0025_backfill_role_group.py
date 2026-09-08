# Generated for issue #457: backfill every existing Role's group from the same
# case-insensitive keyword match frontend/src/lib/roleColumns.ts's `classifyRole()`
# used to perform client-side, so current grouping doesn't regress.

from django.db import migrations


def _group_name_for(role_name):
    """Classify a Role name into a seeded group name, mirroring the retired `classifyRole()`."""
    name = role_name.lower()
    if 'vocal' in name:
        return 'Vocals'
    if 'guitar' in name:
        return 'Guitars'
    if 'bass' in name:
        return 'Bass'
    if 'drum' in name:
        return 'Drums'
    if 'key' in name:
        return 'Keyboards'
    if 'sax' in name:
        return 'Saxophone'
    if 'trumpet' in name:
        return 'Trumpet'
    if 'violin' in name:
        return 'Violin'
    return 'Other'


def backfill_role_group(apps, schema_editor):
    """Assign every Role with no group yet the group its name keyword-matches, falling back to the catch-all."""
    Role = apps.get_model('scheduling', 'Role')
    RoleGroup = apps.get_model('scheduling', 'RoleGroup')
    groups_by_name = {group.name: group for group in RoleGroup.objects.all()}
    for role in Role.objects.filter(group__isnull=True):
        role.group = groups_by_name[_group_name_for(role.name)]
        role.save(update_fields=['group'])


def noop_reverse(apps, schema_editor):
    """No-op reverse: Role.group is re-derivable from Role.name by the same keyword match."""


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0024_rolegroup'),
    ]

    operations = [
        migrations.RunPython(backfill_role_group, noop_reverse),
    ]
