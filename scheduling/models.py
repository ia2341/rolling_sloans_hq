from datetime import time, timedelta
from typing import ClassVar

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

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=['person', 'semester'], name='unique_membership_per_person_per_semester'),
        ]

    def __str__(self):
        """Return "<person> — <semester>" for admin/debug display."""
        return f'{self.person} — {self.semester}'


class MembershipRole(models.Model):
    """A Role a Membership has declared for its Semester."""

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=['membership', 'role'], name='unique_role_per_membership'),
        ]

    def __str__(self):
        """Return "<membership> — <role>" for admin/debug display."""
        return f'{self.membership} — {self.role}'


class Song(models.Model):
    """A song on one Semester's setlist, placed at a concert-order position.

    Carries no relationship back to any other Semester's Song — a title
    replayed in a later semester is represented by a brand-new row, never a
    reused one (per ADR-0001).
    """

    semester = models.ForeignKey(Semester, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    artist = models.CharField(max_length=255)
    length = models.DurationField()
    notes = models.TextField(blank=True)
    position = models.PositiveIntegerField()

    class Meta:
        # Deferred so a reorder can update several Songs' positions inside
        # one atomic transaction without a transient collision on this
        # constraint (e.g. swapping two songs' positions directly).
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=['semester', 'position'],
                name='unique_song_position_per_semester',
                deferrable=models.Deferrable.DEFERRED,
            ),
        ]
        ordering: ClassVar[list[str]] = ['semester', 'position']

    def __str__(self):
        """Return "<title> (<semester>)" for admin/debug display."""
        return f'{self.title} ({self.semester})'


class Rehearsal(models.Model):
    """A dated, timed event within a Semester (issue #36).

    `setup_grace_minutes`, `teardown_grace_minutes`, and `end_time` (derived
    from `start_time` plus the Semester's default duration) are copied from
    the parent Semester's defaults only at creation time, when left unset —
    once saved, editing them here never reaches back to update the
    Semester's defaults or any other Rehearsal.
    """

    semester = models.ForeignKey(Semester, on_delete=models.CASCADE)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    setup_grace_minutes = models.PositiveIntegerField()
    teardown_grace_minutes = models.PositiveIntegerField()
    is_full_setlist = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        """Fill grace periods and end_time from the Semester's defaults on first save only."""
        if self._state.adding:
            if self.setup_grace_minutes is None:
                self.setup_grace_minutes = self.semester.default_setup_grace_minutes
            if self.teardown_grace_minutes is None:
                self.teardown_grace_minutes = self.semester.default_teardown_grace_minutes
            if self.end_time is None and self.start_time is not None:
                start_seconds = (
                    self.start_time.hour * 3600 + self.start_time.minute * 60 + self.start_time.second
                )
                duration = timedelta(minutes=self.semester.default_rehearsal_duration_minutes)
                end_seconds = (start_seconds + duration.total_seconds()) % (24 * 3600)
                hours, remainder = divmod(int(end_seconds), 3600)
                minutes, seconds = divmod(remainder, 60)
                self.end_time = time(hours, minutes, seconds)
        super().save(*args, **kwargs)

    def __str__(self):
        """Return "<semester> — <date>" for admin/debug display."""
        return f'{self.semester} — {self.date}'
