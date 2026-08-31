from datetime import datetime, timedelta
from typing import ClassVar, NamedTuple

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver


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


class SongRoleRequirement(models.Model):
    """A target headcount for one Role on one Song (e.g. 3 singers).

    The count is a target for admins to track fill-status against, not a
    hard cap — nothing here prevents assigning more or fewer people than
    requested (issue #33).
    """

    song = models.ForeignKey(Song, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    count = models.PositiveIntegerField()

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=['song', 'role'], name='unique_role_requirement_per_song'),
        ]

    def __str__(self):
        """Return "<song> — <count> x <role>" for admin/debug display."""
        return f'{self.song} — {self.count} x {self.role}'


class SongRoleAssignment(models.Model):
    """A Person filling a Role on a Song (issue #35).

    is_role_mismatch is never a hard block on save (per ADR-0002): it just
    flags that the assigned Role isn't among the Roles the Person declared
    on their Membership for the Song's Semester, so an admin can notice and
    resolve it either way.
    """

    song = models.ForeignKey(Song, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    is_role_mismatch = models.BooleanField(default=False)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=['song', 'role', 'person'], name='unique_song_role_person'),
        ]

    def _compute_is_role_mismatch(self):
        """True when the Person has no matching MembershipRole for the Song's Semester."""
        return not MembershipRole.objects.filter(
            membership__person=self.person,
            membership__semester=self.song.semester,
            role=self.role,
        ).exists()

    def save(self, *args, **kwargs):
        """Recompute is_role_mismatch from the Person's current Membership before saving."""
        self.is_role_mismatch = self._compute_is_role_mismatch()
        super().save(*args, **kwargs)

    def __str__(self):
        """Return "<person> as <role> on <song>" for admin/debug display."""
        return f'{self.person} as {self.role} on {self.song}'


def _reevaluate_song_role_assignments_for(membership, role):
    """Recompute is_role_mismatch on every SongRoleAssignment this MembershipRole change could affect."""
    affected = SongRoleAssignment.objects.filter(
        person=membership.person,
        role=role,
        song__semester=membership.semester,
    )
    for assignment in affected:
        assignment.save()


@receiver(post_save, sender=MembershipRole)
def _membership_role_saved(sender, instance, **kwargs):
    """Re-evaluate is_role_mismatch on affected SongRoleAssignments when a Role is declared."""
    _reevaluate_song_role_assignments_for(instance.membership, instance.role)


@receiver(post_delete, sender=MembershipRole)
def _membership_role_deleted(sender, instance, **kwargs):
    """Re-evaluate is_role_mismatch on affected SongRoleAssignments when a declared Role is removed.

    Skips re-evaluation if the parent Membership was itself cascade-deleted
    alongside this row (it's no longer fetchable) rather than raising.
    """
    try:
        membership = instance.membership
    except Membership.DoesNotExist:
        return
    _reevaluate_song_role_assignments_for(membership, instance.role)


class RehearsalAttendance(NamedTuple):
    """Whether a Person is needed at a Rehearsal's start and/or end (issue #38)."""

    needed_from_start: bool
    needed_until_end: bool


class Rehearsal(models.Model):
    """A dated, timed event within a Semester (issue #36).

    `setup_grace_minutes`, `teardown_grace_minutes`, and `end_time` (derived
    from `start_time` plus the Semester's default duration) are copied from
    the parent Semester's defaults only at creation time, when left blank —
    once saved, editing them here never reaches back to update the
    Semester's defaults or any other Rehearsal. They're nullable/optional at
    the field level (rather than required) specifically so the Django admin
    add form can be submitted with them left blank and still get sensible
    values, rather than forcing whoever's creating the Rehearsal to already
    know and retype the Semester's numbers.
    """

    semester = models.ForeignKey(Semester, on_delete=models.CASCADE)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField(null=True, blank=True)
    setup_grace_minutes = models.PositiveIntegerField(null=True, blank=True)
    teardown_grace_minutes = models.PositiveIntegerField(null=True, blank=True)
    is_full_setlist = models.BooleanField(default=False)

    class Meta:
        ordering: ClassVar[list[str]] = ['semester', 'date', 'start_time']

    def _default_from_semester(self, value, semester_field_name):
        """Return `value` if set, else fall back to the Semester's `semester_field_name` default."""
        return value if value is not None else getattr(self.semester, semester_field_name)

    def _apply_semester_defaults(self):
        """Fill grace periods and end_time from the Semester's defaults, if not already set.

        Idempotent: once a field holds a concrete value, re-running this is a
        no-op for it. Raises ValueError if deriving end_time would carry it
        past midnight. Called from both clean() (so the admin form surfaces
        this as a normal validation error) and save() (so callers that skip
        full_clean(), e.g. factories/scripts, still get the same defaulting).
        """
        self.setup_grace_minutes = self._default_from_semester(
            self.setup_grace_minutes, 'default_setup_grace_minutes',
        )
        self.teardown_grace_minutes = self._default_from_semester(
            self.teardown_grace_minutes, 'default_teardown_grace_minutes',
        )
        if self.end_time is None and self.start_time is not None:
            duration = timedelta(minutes=self.semester.default_rehearsal_duration_minutes)
            start = datetime.combine(self.date, self.start_time)
            end = start + duration
            if end.date() != start.date():
                raise ValueError(
                    "Rehearsal's default duration would carry end_time past midnight; "
                    'set end_time explicitly instead.'
                )
            self.end_time = end.time()

    def clean(self):
        """Surface the midnight-wraparound case as a normal form error, not a 500.

        Model.full_clean() (as run by ModelForm, e.g. the admin add form)
        calls clean() before save() is ever reached, so raising
        ValidationError here lets it show up as a field error instead of an
        unhandled ValueError escaping ModelAdmin.save_model().
        """
        if self._state.adding:
            try:
                self._apply_semester_defaults()
            except ValueError as exc:
                raise ValidationError({'end_time': str(exc)}) from exc

    def save(self, *args, **kwargs):
        """Fill grace periods and end_time from the Semester's defaults on first save only."""
        if self._state.adding:
            self._apply_semester_defaults()
        super().save(*args, **kwargs)

    def __str__(self):
        """Return "<semester> — <date>" for admin/debug display."""
        return f'{self.semester} — {self.date}'

    @property
    def dress_rehearsal_songs(self):
        """The parent Semester's current setlist in concert-position order, computed live (ADR-0003).

        Meaningful for the Dress Rehearsal (is_full_setlist=True); no
        RehearsalSong rows are read or persisted here, so this can never go
        stale relative to the setlist.
        """
        return Song.objects.filter(semester=self.semester).order_by('position')

    def attendance_for(self, person):
        """Derive whether `person` is needed at this Rehearsal's start and/or end (issue #38).

        Computed live from the Person's SongRoleAssignments compared against
        which Song covers this Rehearsal's first/last slot — never a stored
        field, so it can't drift out of sync if assignments or the schedule
        change later. For the Dress Rehearsal (is_full_setlist=True), which
        has no RehearsalSong rows by design (ADR-0003), the first/last slot
        comes from the live setlist (dress_rehearsal_songs) instead.
        """
        if self.is_full_setlist:
            songs = list(self.dress_rehearsal_songs)
            if not songs:
                return RehearsalAttendance(needed_from_start=False, needed_until_end=False)
            first_song, last_song = songs[0], songs[-1]
        else:
            bounds = RehearsalSong.objects.filter(rehearsal=self).aggregate(
                first=models.Min('order'), last=models.Max('order'),
            )
            if bounds['first'] is None:
                return RehearsalAttendance(needed_from_start=False, needed_until_end=False)
            first_song = RehearsalSong.objects.get(rehearsal=self, order=bounds['first']).song
            last_song = RehearsalSong.objects.get(rehearsal=self, order=bounds['last']).song
        assigned_song_ids = set(
            SongRoleAssignment.objects.filter(
                person=person, song__in=(first_song, last_song),
            ).values_list('song_id', flat=True)
        )
        return RehearsalAttendance(
            needed_from_start=first_song.id in assigned_song_ids,
            needed_until_end=last_song.id in assigned_song_ids,
        )


class RehearsalSong(models.Model):
    """A Song scheduled into a timed slot within a non-Dress Rehearsal (issue #37).

    start_time/end_time are computed from the Rehearsal's fixed window and
    the Semester's default_song_slot_count, then persisted at save time
    rather than derived live at read time. A slot_count greater than 1 eats
    into the Rehearsal's fixed total time (i.e. takes multiple per-slot
    shares) rather than extending Rehearsal.end_time. Only valid for a
    Rehearsal with is_full_setlist=False — the Dress Rehearsal derives its
    songs live from the setlist instead (see Rehearsal.dress_rehearsal_songs
    and ADR-0003).
    """

    rehearsal = models.ForeignKey(Rehearsal, on_delete=models.CASCADE)
    song = models.ForeignKey(Song, on_delete=models.CASCADE)
    order = models.PositiveIntegerField()
    slot_count = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    start_time = models.TimeField(editable=False)
    end_time = models.TimeField(editable=False)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=['rehearsal', 'order'], name='unique_order_per_rehearsal'),
        ]
        ordering: ClassVar[list[str]] = ['rehearsal', 'order']

    def _slot_duration(self):
        """One song-slot's length: the Rehearsal's fixed window divided by its Semester's slot count."""
        start = datetime.combine(self.rehearsal.date, self.rehearsal.start_time)
        end = datetime.combine(self.rehearsal.date, self.rehearsal.end_time)
        return (end - start) / self.rehearsal.semester.default_song_slot_count

    def _prior_slots(self):
        """Sum of slot_count for this Rehearsal's lower-order rows (excluding this one)."""
        return RehearsalSong.objects.filter(
            rehearsal=self.rehearsal, order__lt=self.order,
        ).exclude(pk=self.pk).aggregate(total=models.Sum('slot_count'))['total'] or 0

    def _compute_times(self):
        """Derive start_time/end_time from the slot_counts of lower-order rows plus this row's own."""
        slot_duration = self._slot_duration()
        rehearsal_start = datetime.combine(self.rehearsal.date, self.rehearsal.start_time)
        start = rehearsal_start + self._prior_slots() * slot_duration
        end = start + self.slot_count * slot_duration
        self.start_time = start.time()
        self.end_time = end.time()

    def _overruns_rehearsal_window(self):
        """True when this row's own + prior rows' slot_counts exceed the Semester's slot count.

        Guards against a slot allocation that would silently push end_time
        past the Rehearsal's fixed end_time (or even past midnight), mirroring
        Rehearsal's own "raise instead of wrap" handling for its default
        duration.
        """
        return self._prior_slots() + self.slot_count > self.rehearsal.semester.default_song_slot_count

    def clean(self):
        """Surface an attempted Dress Rehearsal attachment or a slot overrun as a normal form error, not a 500."""
        if self.rehearsal_id and self.rehearsal.is_full_setlist:
            raise ValidationError({
                'rehearsal': (
                    'RehearsalSong rows cannot be added to the Dress Rehearsal '
                    '(is_full_setlist=True); its songs are derived live from the setlist instead.'
                ),
            })
        if self.rehearsal_id and self._overruns_rehearsal_window():
            raise ValidationError({
                'slot_count': (
                    "This row's slot_count, added to this Rehearsal's other rows, "
                    "exceeds the Semester's default_song_slot_count."
                ),
            })

    def save(self, *args, **kwargs):
        """Reject the Dress Rehearsal or a slot overrun, then compute start_time/end_time before saving."""
        if self.rehearsal.is_full_setlist:
            raise ValueError(
                'RehearsalSong rows cannot be added to the Dress Rehearsal (is_full_setlist=True).'
            )
        if self._overruns_rehearsal_window():
            raise ValueError(
                "This row's slot_count, added to this Rehearsal's other rows, "
                "exceeds the Semester's default_song_slot_count."
            )
        self._compute_times()
        super().save(*args, **kwargs)

    def __str__(self):
        """Return "<song> @ <rehearsal> (order <order>)" for admin/debug display."""
        return f'{self.song} @ {self.rehearsal} (order {self.order})'


class Conflict(models.Model):
    """A Person's declared full or partial unavailability for one Rehearsal (issue #48).

    Editable in place at any time — there is no submission deadline or edit
    lock. A (person, rehearsal) pair with no Conflict row means implicit
    full availability; that's the absence of a row, not an explicit status
    value, so it stays distinguishable from a future "confirmed available"
    status without conflating the two.
    """

    FULL_CONFLICT = 'full_conflict'
    PARTIAL = 'partial'
    TYPE_CHOICES = (
        (FULL_CONFLICT, 'Full conflict'),
        (PARTIAL, 'Partial'),
    )

    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rehearsal = models.ForeignKey(Rehearsal, on_delete=models.CASCADE)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=['person', 'rehearsal'], name='unique_conflict_per_person_per_rehearsal'),
        ]

    def __str__(self):
        """Return "<person> — <rehearsal> (<type>)" for admin/debug display."""
        return f'{self.person} — {self.rehearsal} ({self.type})'


class Recording(models.Model):
    """An uploaded audio take for one Song's slot at one Rehearsal (issue #50).

    The Song and Rehearsal are intentionally reached only through
    `rehearsal_song`, so those relationships cannot drift from the slot the
    Recording represents. `file` stores the private-object key; storage and
    signed-URL handling are addressed separately by ADR-0004.
    """

    rehearsal_song = models.ForeignKey(RehearsalSong, on_delete=models.CASCADE)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    file = models.FileField(upload_to='recordings/', unique=True)
    content_type = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()
    note = models.TextField(blank=True)

    def __str__(self):
        """Return the Recording's object key for admin/debug display."""
        return self.file.name
