# Generated for issue #485: retire the email-based invite/reset flow (ADR 0018).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('identity', '0004_person_must_change_password'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='person',
            name='invited_at',
        ),
        migrations.DeleteModel(
            name='AuthEmailRequest',
        ),
    ]
