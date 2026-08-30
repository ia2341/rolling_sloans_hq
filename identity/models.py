from django.contrib.auth.models import AbstractUser


class Person(AbstractUser):
    """Placeholder for AUTH_USER_MODEL.

    AUTH_USER_MODEL must point at a real model before the first migration
    ever runs (changing it later requires a migration reset), so this stub
    exists to make that setting valid now. The real fields and behavior are
    designed and implemented in the Identity & Auth spec (issue #5); no
    migrations have been generated for this app yet.
    """
