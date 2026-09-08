# Generated for issue #457: every Role now has a group (0025's backfill), so require it going forward.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0025_backfill_role_group'),
    ]

    operations = [
        migrations.AlterField(
            model_name='role',
            name='group',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='roles',
                to='scheduling.rolegroup',
            ),
        ),
    ]
