"""Retire `AuthEmailRequest` and `Person.invited_at` (issue #487, ADR 0018).

Both existed only to support the email-based invite/reset flow this issue
removes: `AuthEmailRequest` backed `is_auth_email_rate_limited()`
(outbound-auth-email quota), and `invited_at` recorded when
`invite_person()`/`resend_invite()` last emailed a set-password link.
Neither has a writer left in the codebase.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('identity', '0004_person_must_change_password'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='authemailrequest',
            name='identity_au_email_fe0bd3_idx',
        ),
        migrations.RemoveIndex(
            model_name='authemailrequest',
            name='identity_au_ip_addr_2e78d4_idx',
        ),
        migrations.DeleteModel(
            name='AuthEmailRequest',
        ),
        migrations.RemoveField(
            model_name='person',
            name='invited_at',
        ),
    ]
