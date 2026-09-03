from datetime import datetime, timedelta
from typing import ClassVar, NamedTuple

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone


class Semester(models.Model):
    """A term (e.g. "Fall 2026") carrying default timing values for its Rehearsals and Songs.

    Also carries the semester lifecycle (ADR-0010): a Semester whose
    `published_at` is null is a **draft** — it exists, an admin can build it
    out, and no member sees it — and the **Live Semester** is the one with
    the greatest `published_at`. `created_at` exists so semesters can be
    ordered chronologically without leaning on primary keys.

    `updated_at` is the optimistic-concurrency stamp every bulk edit surface
    in this map shares (issue #178): a write that touches this Semester's
    rows sets it explicitly (never `auto_now`, so an unrelated read never
    bumps it) and rejects a submission carrying an older stamp wholesale.
    """

    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    default_rehearsal_duration_minutes = models.PositiveIntegerField()
    default_setup_grace_minutes = models.PositiveIntegerField()
    default_teardown_grace_minutes = models.PositiveIntegerField()
    default_song_slot_count = models.PositiveIntegerField()
    default_arrival_buffer_minutes = models.PositiveIntegerField()
    default_departure_buffer_minutes = models.PositiveIntegerField()

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


def _reevaluate_role_mismatches_for(membership, role):
    """Recompute is_role_mismatch on every SongRoleAssignment and Backup this MembershipRole change could affect.

    Generalised (issue #174, ADR-0007) to sweep both models in one pass
    rather than adding a second pair of post_save/post_delete receivers.
    """
    affected_assignments = SongRoleAssignment.objects.filter(
        person=membership.person,
        role=role,
        song__semester=membership.semester,
    )
    for assignment in affected_assignments:
        assignment.save()
    affected_backups = Backup.objects.filter(
        person=membership.person,
        role=role,
        rehearsal_song__rehearsal__semester=membership.semester,
    )
    for backup in affected_backups:
        backup.save()


@receiver(post_save, sender=MembershipRole)
def _membership_role_saved(sender, instance, **kwargs):
    """Re-evaluate is_role_mismatch on affected SongRoleAssignments/Backups when a Role is declared."""
    _reevaluate_role_mismatches_for(instance.membership, instance.role)


@receiver(post_delete, sender=MembershipRole)
def _membership_role_deleted(sender, instance, **kwargs):
    """Re-evaluate is_role_mismatch on affected SongRoleAssignments/Backups when a declared Role is removed.

    Skips re-evaluation if the parent Membership was itself cascade-deleted
    alongside this row (it's no longer fetchable) rather than raising.
    """
    try:
        membership = instance.membership
    except Membership.DoesNotExist:
        return
    _reevaluate_role_mismatches_for(membership, instance.role)


class RehearsalAttendance(NamedTuple):
    """Whether a Person is needed at a Rehearsal's start and/or end (issue #38)."""

    needed_from_start: bool
    needed_until_end: bool


class Rehearsal(models.Model):
    """A dated, timed event within a Semester (issue #36).

    `setup_grace_minutes`, `teardown_grace_minutes`, `arrival_buffer_minutes`,
    `departure_buffer_minutes`, and `end_time` (derived from `start_time`
    plus the Semester's default duration) are copied from the parent
    Semester's defaults only at creation time, when left blank — once
    saved, editing them here never reaches back to update the Semester's
    defaults or any other Rehearsal. They're nullable/optional at the field
    level (rather than required) specifically so the Django admin add form
    can be submitted with them left blank and still get sensible values,
    rather than forcing whoever's creating the Rehearsal to already know
    and retype the Semester's numbers.
    """

    semester = models.ForeignKey(Semester, on_delete=models.CASCADE)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField(null=True, blank=True)
    setup_grace_minutes = models.PositiveIntegerField(null=True, blank=True)
    teardown_grace_minutes = models.PositiveIntegerField(null=True, blank=True)
    arrival_buffer_minutes = models.PositiveIntegerField(null=True, blank=True)
    departure_buffer_minutes = models.PositiveIntegerField(null=True, blank=True)
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
        self.arrival_buffer_minutes = self._default_from_semester(
            self.arrival_buffer_minutes, 'default_arrival_buffer_minutes',
        )
        self.departure_buffer_minutes = self._default_from_semester(
            self.departure_buffer_minutes, 'default_departure_buffer_minutes',
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

    def _blocked_full_setlist_flip_count(self):
        """Return how many Conflicts block making this saved Rehearsal the Dress Rehearsal, else 0 (issue #150).

        Non-zero only when a saved Rehearsal is about to be written with
        is_full_setlist=True while Conflicts still point at it. It reads the
        pending value rather than diffing against the stored one: a
        Rehearsal that is already the Dress Rehearsal can carry no
        Conflicts (ADR-0006 keeps them off it from the Conflict side), so
        "about to be true with Conflicts" is exactly the flip. Discarding
        those declarations silently would lose data ADR-0005 treats as
        sensitive, so the write is refused instead.
        """
        if self._state.adding or not self.is_full_setlist:
            return 0
        return Conflict.objects.filter(rehearsal=self).count()

    def _blocked_full_setlist_flip_message(self, count):
        """Phrase the refused flip, naming only the Conflict count — never who declared it, or why (ADR-0005)."""
        members = 'member has' if count == 1 else 'members have'
        return (
            f'{count} {members} declared a Conflict against this Rehearsal, and attendance at the '
            'Dress Rehearsal is mandatory (ADR-0006). Clear those Conflicts in the Django admin '
            'Conflict list before making this the Dress Rehearsal.'
        )

    def clean(self):
        """Surface the midnight-wraparound case as a normal form error, not a 500.

        Model.full_clean() (as run by ModelForm, e.g. the admin add form)
        calls clean() after clean_fields() regardless of whether clean_fields()
        found errors, so a blank `semester` or `date` reaches here too —
        dereferencing self.semester or calling datetime.combine(self.date, ...)
        in that state raises Semester.DoesNotExist or TypeError, neither of
        which full_clean() converts to a ValidationError, so it would escape
        as a 500. Skip defaulting until those required fields are actually
        set and let clean_fields()'s own required-field errors stand.

        Also refuses a flip to is_full_setlist=True on a Rehearsal that
        already carries Conflicts (issue #150). RehearsalForm and the Django
        admin both reach this through ModelForm._post_clean(), so neither
        needs its own copy of the rule and the message renders once.
        """
        if self._state.adding and self.semester_id is not None and self.date is not None:
            try:
                self._apply_semester_defaults()
            except ValueError as exc:
                raise ValidationError({'end_time': str(exc)}) from exc
        blocking_conflicts = self._blocked_full_setlist_flip_count()
        if blocking_conflicts:
            raise ValidationError({
                'is_full_setlist': self._blocked_full_setlist_flip_message(blocking_conflicts),
            })

    def save(self, *args, **kwargs):
        """Fill grace periods and end_time from the Semester's defaults on first save only, refusing a blocked flip.

        The Conflict check is repeated here, rather than left to clean(),
        for the same belt-and-suspenders reason Conflict.save() and
        RehearsalSong.save() carry theirs: callers that skip full_clean()
        (.objects.update()-style scripts, factories) must not be able to
        create the Conflict rows ADR-0006 declares invalid either.
        """
        if self._state.adding:
            self._apply_semester_defaults()
        blocking_conflicts = self._blocked_full_setlist_flip_count()
        if blocking_conflicts:
            raise ValueError(self._blocked_full_setlist_flip_message(blocking_conflicts))
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
            return self._dress_attendance_for(person)
        bounds = RehearsalSong.objects.filter(rehearsal=self).aggregate(
            first=models.Min('order'), last=models.Max('order'),
        )
        if bounds['first'] is None:
            return RehearsalAttendance(needed_from_start=False, needed_until_end=False)
        assigned_orders = set(slots_for_person(self, person).values_list('order', flat=True))
        return RehearsalAttendance(
            needed_from_start=bounds['first'] in assigned_orders,
            needed_until_end=bounds['last'] in assigned_orders,
        )

    def _dress_attendance_for(self, person):
        """Return `person`'s start/end need at the Dress Rehearsal, read off the live setlist (ADR-0003).

        Kept apart from the slot-based path in attendance_for() because the
        Dress Rehearsal has no RehearsalSong rows to ask slots_for_person()
        about: its first/last "slot" is the first/last Song of the current
        setlist, computed live so it can't go stale.
        """
        songs = list(self.dress_rehearsal_songs)
        if not songs:
            return RehearsalAttendance(needed_from_start=False, needed_until_end=False)
        first_song, last_song = songs[0], songs[-1]
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


def slots_for_person(rehearsal, person):
    """Return the RehearsalSong rows in `rehearsal`'s Running Order that `person` is on (issues #173, #175).

    The single definition of "which slots is this Person on at this
    Rehearsal", shared by Rehearsal.attendance_for() and by
    services._regular_rehearsal_attendance_suggestion()/breaks_for(). Slot
    membership is the union of two independent facts: the Person's
    SongRoleAssignments on the slot's Song, and any Backup recorded for
    them directly on the slot (ADR-0007) — a Backup "genuinely changes when
    that person must arrive and leave", exactly like a standing assignment.

    Internal to the scheduling app despite the plain name: it lives here
    rather than in services.py only because models.py cannot import
    services.py. The tested surface stays the three public reads. It is
    deliberately not used by services.performers_for(), which is a
    Song-level Setlist read rather than a rehearsal-slot one (ADR-0007
    §5) — folding a Backup into it would misreport who performs the Song.

    Returned unordered and distinct: a Person holding two Role Assignments
    on the same Song, or both an Assignment and a Backup on the same slot,
    must not yield that slot twice, since breaks_for() walks the rows
    pairwise.
    """
    return RehearsalSong.objects.filter(rehearsal=rehearsal).filter(
        models.Q(song__songroleassignment__person=person) | models.Q(backup__person=person),
    ).distinct()


class Conflict(models.Model):
    """A Person's declared full or partial unavailability for one Rehearsal (issue #48).

    Editable in place at any time — there is no submission deadline or edit
    lock. A (person, rehearsal) pair with no Conflict row means implicit
    full availability; that's the absence of a row, not an explicit status
    value, so it stays distinguishable from a future "confirmed available"
    state without conflating the two — `status` is the *admin's verdict* on
    a declaration that exists, never the member's own availability.

    `status` and the optional admin-authored `adjudication_note` record
    that verdict and nothing more (issue #189). There is deliberately no
    provenance — no adjudicator, no timestamp, no prior-verdict history —
    so a re-decided Conflict keeps only its latest verdict and reads
    exactly like one never adjudicated. `declare_conflict()` resets both
    fields on every member edit, so a verdict can never outlive the
    declaration it was passed on.

    The verdict governs the owner's own row on their schedule and
    membership of the joint feasibility set, and nothing else. It must not
    reach `attendance_for()`, `attendance_suggestion_for()`,
    `next_attended_rehearsal_for()`, `breaks_for()` or `performers_for()`:
    those answer "are you needed", which is an assignment question. An
    approved absence un-assigns nobody, a rejected one constrains nothing,
    and a pending one is not a silent approval.
    """

    FULL_CONFLICT = 'full_conflict'
    PARTIAL = 'partial'
    TYPE_CHOICES = (
        (FULL_CONFLICT, 'Full conflict'),
        (PARTIAL, 'Partial'),
    )

    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    STATUS_CHOICES = (
        (PENDING, 'Pending'),
        (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'),
    )

    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rehearsal = models.ForeignKey(Rehearsal, on_delete=models.CASCADE)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    reason = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    adjudication_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=['person', 'rehearsal'], name='unique_conflict_per_person_per_rehearsal'),
        ]

    def _was_partial_in_db(self):
        """True if this row exists in the DB and was last saved with type=PARTIAL."""
        if self._state.adding:
            return False
        return Conflict.objects.filter(pk=self.pk, type=self.PARTIAL).exists()

    def clean(self):
        """Surface an attempted Dress Rehearsal Conflict as a normal form error, not a 500 (ADR-0006)."""
        if self.rehearsal_id and self.rehearsal.is_full_setlist:
            raise ValidationError({
                'rehearsal': (
                    'Attendance at the Dress Rehearsal (is_full_setlist=True) is mandatory, '
                    'so a Conflict cannot be declared against it.'
                ),
            })

    def save(self, *args, **kwargs):
        """Reject a Dress Rehearsal Conflict, save, then clear stale ConflictWindows on a PARTIAL-to-FULL flip.

        Mirrors RehearsalSong.save()'s belt-and-suspenders check, so the
        mandatory-attendance rule of ADR-0006 holds for every write path
        (e.g. .objects.create(), the Django admin), not only callers that
        run full_clean() first. There is deliberately no DB-level
        CheckConstraint backing it: a constraint expression cannot reach
        through the `rehearsal` FK to read is_full_setlist.
        """
        if self.rehearsal.is_full_setlist:
            raise ValueError(
                'Attendance at the Dress Rehearsal (is_full_setlist=True) is mandatory, '
                'so a Conflict cannot be declared against it.'
            )
        flipped_to_full = self.type == self.FULL_CONFLICT and self._was_partial_in_db()
        super().save(*args, **kwargs)
        if flipped_to_full:
            self.conflictwindow_set.all().delete()

    def __str__(self):
        """Return "<person> — <rehearsal> (<type>)" for admin/debug display."""
        return f'{self.person} — {self.rehearsal} ({self.type})'


class ConflictWindow(models.Model):
    """One disjoint unavailable time range within a partial Conflict's Rehearsal span (issue #49).

    Represents non-contiguous partial conflicts (e.g. unavailable 6-7pm and
    again 8:30-9pm) as separate rows. A full_conflict Conflict is expected to
    have no windows in normal application use — that's not enforced as a DB
    constraint, but Conflict.save() deletes any stale windows when an
    existing row's type flips from partial to full_conflict.
    """

    conflict = models.ForeignKey(Conflict, on_delete=models.CASCADE)
    unavailable_start = models.TimeField()
    unavailable_end = models.TimeField()

    def _outside_rehearsal_span(self):
        """True if unavailable_start or unavailable_end falls outside the parent Rehearsal's time span."""
        rehearsal = self.conflict.rehearsal
        return not (
            rehearsal.start_time <= self.unavailable_start <= rehearsal.end_time
            and rehearsal.start_time <= self.unavailable_end <= rehearsal.end_time
        )

    def _reversed_or_zero_length(self):
        """True if unavailable_start doesn't fall strictly before unavailable_end."""
        return self.unavailable_start >= self.unavailable_end

    def clean(self):
        """Surface a reversed/zero-length window, or one outside the Rehearsal's span, as a form error, not a 500."""
        if not (self.conflict_id and self.unavailable_start and self.unavailable_end):
            return
        if self._reversed_or_zero_length():
            message = 'End time must be after start time.'
            raise ValidationError({'unavailable_start': message, 'unavailable_end': message})
        if self._outside_rehearsal_span():
            message = "Must fall within the Rehearsal's time span."
            raise ValidationError({'unavailable_start': message, 'unavailable_end': message})

    def save(self, *args, **kwargs):
        """Reject a reversed/zero-length window, or one outside the Rehearsal's span, before saving.

        Mirrors RehearsalSong.save()'s belt-and-suspenders check, so this is
        enforced for every write path (e.g. .objects.create()), not only
        callers that run full_clean() first (e.g. a ModelForm).
        """
        if self._reversed_or_zero_length():
            raise ValueError("ConflictWindow's unavailable_start must be strictly before unavailable_end.")
        if self._outside_rehearsal_span():
            raise ValueError("ConflictWindow's unavailable_start/unavailable_end must fall within the Rehearsal's time span.")
        super().save(*args, **kwargs)

    def __str__(self):
        """Return "<conflict> <unavailable_start>-<unavailable_end>" for admin/debug display."""
        return f'{self.conflict} {self.unavailable_start}-{self.unavailable_end}'


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


class Backup(models.Model):
    """One Person covering one Role at a Rehearsal's timed slot (ADR-0007, issue #174).

    Anchored on RehearsalSong rather than (Rehearsal, Song) or a nullable
    `rehearsal` FK on SongRoleAssignment, so a Song's Role Assignments and
    the covering Person's Membership Roles stay completely untouched —
    standing in once never tells the system someone plays that instrument
    all term. `covering_for` is advisory (noting who is covered for is
    optional and never load-bearing), so it's nullable and SET_NULL rather
    than CASCADE. Hard deleted: the Role.is_active soft-delete convention
    deliberately does not apply here (ADR-0007 §4) since nothing else
    references a Backup and a removed row means the arrangement isn't
    happening. No created_at and no free-text notes, deliberately, per
    ADR-0007 §4.
    """

    rehearsal_song = models.ForeignKey(RehearsalSong, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    covering_for = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='backups_covered_for',
    )
    is_role_mismatch = models.BooleanField(default=False)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=['rehearsal_song', 'role', 'person'], name='unique_backup_per_slot_role_person',
            ),
            models.CheckConstraint(
                condition=~models.Q(person=models.F('covering_for')),
                name='backup_person_is_not_covering_for_self',
            ),
        ]

    def _compute_is_role_mismatch(self):
        """True when the Person has no matching MembershipRole for the Rehearsal's Semester."""
        return not MembershipRole.objects.filter(
            membership__person=self.person,
            membership__semester=self.rehearsal_song.rehearsal.semester,
            role=self.role,
        ).exists()

    def save(self, *args, **kwargs):
        """Recompute is_role_mismatch from the Person's current Membership before saving."""
        self.is_role_mismatch = self._compute_is_role_mismatch()
        super().save(*args, **kwargs)

    def is_stale(self):
        """True when covering_for is set but that Person no longer has a Conflict on this Rehearsal (ADR-0007 §3).

        Computed live, never stored: withdrawing the covered Person's
        Conflict leaves the Backup standing, since the Backup may already
        have learned the part. Always False when covering_for is null.
        """
        if self.covering_for_id is None:
            return False
        return not Conflict.objects.filter(
            person=self.covering_for, rehearsal=self.rehearsal_song.rehearsal,
        ).exists()

    def __str__(self):
        """Return "<person> backing up <role> @ <rehearsal_song>" for admin/debug display."""
        return f'{self.person} backing up {self.role} @ {self.rehearsal_song}'
