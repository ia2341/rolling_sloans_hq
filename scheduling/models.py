from django.conf import settings
from django.db import models


class Semester(models.Model):
    """A term (e.g. "Fall 2026") carrying default timing values for its Rehearsals and Songs."""

    name = models.CharField(max_length=255)
    default_rehearsal_duration_minutes = models.PositiveIntegerField()
    default_setup_grace_minutes = models.PositiveIntegerField()
    default_teardown_grace_minutes = models.PositiveIntegerField()
    default_song_slot_count = models.PositiveIntegerField()

    def __str__(self):
        return self.name


class Role(models.Model):
    """A global, semester-independent catalog entry (e.g. singer, guitarist, drummer).

    Deactivating a Role is a soft update (is_active=False); there is no
    deletion path, so historical references to it stay intact.
    """

    name = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    """A Person's participation in one Semester, carrying that term's declared Roles.

    Re-created fresh per Semester rather than carried forward, since declared
    roles legitimately change term to term (per ADR-0001).
    """

    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE)

    def __str__(self):
        return f'{self.person} — {self.semester}'


class MembershipRole(models.Model):
    """A Role a Membership has declared for its Semester."""

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)

    def __str__(self):
        return f'{self.membership} — {self.role}'
