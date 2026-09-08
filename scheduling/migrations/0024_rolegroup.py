# Generated for issue #457: introduce RoleGroup and add Role.group (nullable pending backfill).

import django.db.models.deletion
from django.db import migrations, models

# Seeded groups mirror the fixed instrument families `frontend/src/lib/roleColumns.ts`'s
# now-retired `classifyRole()` recognized, plus the catch-all every unmatched Role fell
# back to as its own column. `display_order` fixes column order on the Setlist/Schedule
# cast tables independently of each group's name.
SEED_GROUPS = [
    {'name': 'Vocals', 'display_order': 0, 'is_catch_all': False},
    {'name': 'Guitars', 'display_order': 1, 'is_catch_all': False},
    {'name': 'Bass', 'display_order': 2, 'is_catch_all': False},
    {'name': 'Drums', 'display_order': 3, 'is_catch_all': False},
    {'name': 'Keyboards', 'display_order': 4, 'is_catch_all': False},
    {'name': 'Saxophone', 'display_order': 5, 'is_catch_all': False},
    {'name': 'Trumpet', 'display_order': 6, 'is_catch_all': False},
    {'name': 'Violin', 'display_order': 7, 'is_catch_all': False},
    {'name': 'Other', 'display_order': 8, 'is_catch_all': True},
]


def seed_role_groups(apps, schema_editor):
    """Create the fixed instrument-family groups plus the catch-all, matching today's `classifyRole()` families."""
    RoleGroup = apps.get_model('scheduling', 'RoleGroup')
    RoleGroup.objects.bulk_create([RoleGroup(**fields) for fields in SEED_GROUPS])


def noop_reverse(apps, schema_editor):
    """No-op reverse: the RoleGroup rows are dropped with the table itself when this migration unapplies."""


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0023_backfill_personrole'),
    ]

    operations = [
        migrations.CreateModel(
            name='RoleGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('display_order', models.PositiveIntegerField(default=0)),
                ('is_catch_all', models.BooleanField(default=False)),
            ],
            options={
                'ordering': ['display_order', 'name'],
            },
        ),
        migrations.RunPython(seed_role_groups, noop_reverse),
        migrations.AddField(
            model_name='role',
            name='group',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='roles',
                to='scheduling.rolegroup',
            ),
        ),
    ]
