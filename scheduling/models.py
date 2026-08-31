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
