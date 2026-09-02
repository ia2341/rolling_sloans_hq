"""Application services for the scheduling domain."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from itertools import pairwise
from uuid import uuid4

from botocore.exceptions import ClientError
from django.core.files.storage import storages
from django.db import IntegrityError, models, transaction
from django.db.models import Count, Q
from django.utils import timezone

from scheduling.models import (
    Conflict,
    ConflictWindow,
    Recording,
    Rehearsal,
    RehearsalSong,
    Role,
    Semester,
    Song,
    SongRoleAssignment,
)

MAX_RECORDING_FILE_SIZE = 50 * 1024 * 1024
PRESIGNED_URL_EXPIRY_SECONDS = 900
SUPPORTED_RECORDING_CONTENT_TYPES = frozenset(
    {
        'audio/aac',
        'audio/mpeg',
        'audio/mp4',
        'audio/ogg',
        'audio/wav',
        'audio/x-wav',
    }
)
_FILE_EXTENSIONS_BY_CONTENT_TYPE = {
    'audio/aac': '.aac',
    'audio/mpeg': '.mp3',
    'audio/mp4': '.m4a',
    'audio/ogg': '.ogg',
    'audio/wav': '.wav',
    'audio/x-wav': '.wav',
}


class RecordingUploadError(ValueError):
    """Raised when a recording object is not a valid private audio upload."""


@dataclass(frozen=True)
class RecordingUploadReservation:
    """The opaque private-object key and short-lived POST policy for one audio take.

    upload_url and fields are submitted together as a multipart/form-data POST
    (per boto3's generate_presigned_post contract) — R2 itself rejects the
    upload if the posted bytes don't match the content-length-range/
    Content-Type conditions baked into fields.
    """

    object_key: str
    upload_url: str
    fields: dict[str, str]


def reserve_recording_upload(content_type: str, file_size: int) -> RecordingUploadReservation:
    """Validate client metadata and return a short-lived direct R2 POST-policy reservation."""
    _validate_recording_metadata(content_type, file_size)
    object_key = _new_recording_object_key(content_type)
    storage = _recording_storage()
    presigned_post = storage.connection.meta.client.generate_presigned_post(
        Bucket=storage.bucket_name,
        Key=object_key,
        Fields={'Content-Type': content_type},
        Conditions=[
            {'Content-Type': content_type},
            ['content-length-range', 1, MAX_RECORDING_FILE_SIZE],
        ],
        ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
    )
    return RecordingUploadReservation(
        object_key=object_key,
        upload_url=presigned_post['url'],
        fields=presigned_post['fields'],
    )


def confirm_recording_upload(
    rehearsal_song: RehearsalSong,
    uploaded_by,
    object_key: str,
    note: str = '',
) -> Recording:
    """Verify R2's actual object metadata, then persist the corresponding Recording."""
    _validate_recording_object_key(object_key)
    if Recording.objects.filter(file=object_key).exists():
        raise RecordingUploadError('This recording object has already been confirmed.')
    storage = _recording_storage()
    try:
        uploaded_object = storage.connection.meta.client.head_object(
            Bucket=storage.bucket_name,
            Key=object_key,
        )
    except ClientError as error:
        raise RecordingUploadError('The uploaded recording object could not be found.') from error
    content_type = uploaded_object.get('ContentType')
    file_size = uploaded_object.get('ContentLength')
    _validate_recording_metadata(content_type, file_size)
    try:
        with transaction.atomic():
            return Recording.objects.create(
                rehearsal_song=rehearsal_song,
                uploaded_by=uploaded_by,
                file=object_key,
                content_type=content_type,
                file_size=file_size,
                note=note,
            )
    except IntegrityError as error:
        raise RecordingUploadError('This recording object has already been confirmed.') from error


def create_recording_playback_url(recording: Recording) -> str:
    """Return a freshly signed, short-lived R2 GET URL for a private Recording."""
    return _presign('get_object', recording.file.name, http_method='GET')


def _presign(client_method: str, object_key: str, http_method: str, extra_params=None) -> str:
    """Return a short-lived signed R2 URL for the given S3 client method and object key."""
    storage = _recording_storage()
    params = {'Bucket': storage.bucket_name, 'Key': object_key, **(extra_params or {})}
    return storage.connection.meta.client.generate_presigned_url(
        client_method,
        Params=params,
        ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
        HttpMethod=http_method,
    )


def _recording_storage():
    """Return the configured django-storages backend for private R2 recording objects."""
    return storages['default']


def _new_recording_object_key(content_type: str) -> str:
    """Return an opaque recordings-prefixed key with the format's conventional extension."""
    return f'recordings/{uuid4().hex}{_FILE_EXTENSIONS_BY_CONTENT_TYPE[content_type]}'


def _validate_recording_object_key(object_key: str) -> None:
    """Reject keys outside the private recordings namespace before querying object storage."""
    if not object_key.startswith('recordings/'):
        raise RecordingUploadError('Recording uploads must use a recordings/ object key.')


def _validate_recording_metadata(content_type: str | None, file_size: int | None) -> None:
    """Reject unsupported audio formats and sizes outside the recording-upload limit."""
    if content_type not in SUPPORTED_RECORDING_CONTENT_TYPES:
        raise RecordingUploadError('Recording uploads must use a supported audio content type.')
    if not isinstance(file_size, int) or isinstance(file_size, bool) or file_size < 1:
        raise RecordingUploadError('Recording uploads must include a positive file size.')
    if file_size > MAX_RECORDING_FILE_SIZE:
        raise RecordingUploadError('Recording uploads may not exceed 50 MB.')


def get_current_semester() -> Semester | None:
    """Return the most-recently-created Semester, or None if none exist yet.

    "Current semester" isn't specified anywhere else in the domain map
    (issue #56); this is the single place that decides it, so every read
    route that needs "the current semester" reuses this instead of
    re-deriving its own notion of recency.
    """
    return Semester.objects.order_by('-id').first()


@dataclass(frozen=True)
class SongRehearsalProgress:
    """A Song's RehearsalSong counts split by whether the rehearsal has already happened."""

    completed: int
    remaining: int
    total: int


def song_rehearsal_progress(song) -> SongRehearsalProgress:
    """Return `song`'s RehearsalSong counts split into completed/remaining/total (issue #92).

    completed/remaining are date-split (rehearsal.date < today vs >= today)
    counts of the Song's own RehearsalSong rows, computed in one aggregate
    query; total is their sum. Shared by the Overview song-progress table
    (X of Y = completed of total) and the Songs page's "rehearsals
    remaining" column (X/Y = remaining/total) so both read off one query
    instead of duplicating it.
    """
    today = timezone.localdate()
    counts = RehearsalSong.objects.filter(song=song).aggregate(
        completed=Count('pk', filter=Q(rehearsal__date__lt=today)),
        remaining=Count('pk', filter=Q(rehearsal__date__gte=today)),
    )
    return SongRehearsalProgress(
        completed=counts['completed'],
        remaining=counts['remaining'],
        total=counts['completed'] + counts['remaining'],
    )


def songs_with_progress_for(semester, person) -> list[Song]:
    """Return `semester`'s Songs in position order, each annotated with `.progress` and `.has_assignment` for `person` (issue #93).

    `.progress` is that Song's `song_rehearsal_progress` (X of Y);
    `.has_assignment` is True whenever `person` has any SongRoleAssignment
    on the Song, regardless of is_role_mismatch — the Overview page's "my
    songs only" filter is intentionally coarser than My Schedule's
    per-role assignment matrix.
    """
    assigned_song_ids = set(
        SongRoleAssignment.objects.filter(
            person=person, song__semester=semester,
        ).values_list('song_id', flat=True),
    )
    songs = list(Song.objects.filter(semester=semester).order_by('position'))
    for song in songs:
        song.progress = song_rehearsal_progress(song)
        song.has_assignment = song.pk in assigned_song_ids
    return songs


def rehearsal_count_target(song) -> int:
    """Return how many Rehearsals a Song is targeted to appear in.

    Nothing in the domain model persists a per-Song rehearsal-count target
    (issue #56); the closest available proxy is every non-Dress Rehearsal in
    the Song's Semester, since the Dress Rehearsal never carries persisted
    RehearsalSong rows (ADR-0003) and so can't be part of a song's actual
    count either. Centralized here so /songs/<id>/ and /setlist/ don't
    re-derive it.
    """
    return song.semester.rehearsal_set.filter(is_full_setlist=False).count()


@dataclass(frozen=True)
class AttendanceSuggestion:
    """A Person's suggested arrival/departure time-window for one Rehearsal (issue #94)."""

    arrival_time: time
    departure_time: time


def next_attended_rehearsal_for(person, semester):
    """Return `person`'s next upcoming Rehearsal in `semester` they have any assignment for, else None.

    "Next" is not necessarily the band's literal next Rehearsal: this walks
    the Semester's upcoming Rehearsals in date order and returns the first
    one with a non-None attendance_suggestion_for (issue #94), skipping any
    Rehearsal the Person isn't needed at. Deliberately not
    Rehearsal.attendance_for alone: that only reports endpoint (start/end)
    attendance, so a Person assigned only to a middle RehearsalSong (or a
    middle Dress Rehearsal setlist song) would be wrongly skipped. Also the
    default landing Rehearsal for the shared rehearsal-detail view
    (ScheduleView, issue #95).
    """
    for rehearsal in _upcoming_rehearsals(semester):
        if attendance_suggestion_for(rehearsal, person) is not None:
            return rehearsal
    return None


@dataclass(frozen=True)
class AssignmentMatrixCell:
    """One (Song, Role) cell in an assignment matrix: every SongRoleAssignment for that pair (issue #95)."""

    role: Role
    assignments: list[SongRoleAssignment]


@dataclass(frozen=True)
class AssignmentMatrixRow:
    """One Song's row in an assignment matrix: its slot start_time (if any) plus its per-Role cells (issue #95)."""

    song: Song
    start_time: time | None
    cells: list[AssignmentMatrixCell]


@dataclass(frozen=True)
class AssignmentMatrix:
    """A Rehearsal's Song x Role x Person assignment grid (issue #95)."""

    roles: list[Role]
    rows: list[AssignmentMatrixRow]


def assignment_matrix_for(rehearsal) -> AssignmentMatrix:
    """Build `rehearsal`'s Song x Role x Person assignment matrix (issue #95).

    Rows are the Rehearsal's Songs in Song.position order: the Songs linked
    via RehearsalSong for a regular Rehearsal, or the live setlist
    (Rehearsal.dress_rehearsal_songs, ADR-0003) for the Dress Rehearsal,
    which carries no RehearsalSong rows and so no per-row start_time.
    Columns are every Role carrying a SongRoleRequirement on any of those
    Songs, ordered by name. Each cell lists every SongRoleAssignment for
    that (Song, Role) pair, each already carrying is_role_mismatch.
    """
    songs, start_times = _matrix_songs(rehearsal)
    roles = list(Role.objects.filter(songrolerequirement__song__in=songs).distinct().order_by('name'))
    assignments_by_song_role = _assignments_by_song_role(songs, roles)
    rows = [
        AssignmentMatrixRow(
            song=song,
            start_time=start_times.get(song.id),
            cells=[
                AssignmentMatrixCell(role=role, assignments=assignments_by_song_role.get((song.id, role.id), []))
                for role in roles
            ],
        )
        for song in songs
    ]
    return AssignmentMatrix(roles=roles, rows=rows)


def _matrix_songs(rehearsal):
    """Return (Songs in Song.position order, {song_id: RehearsalSong.start_time}) for `rehearsal`.

    The Dress Rehearsal (is_full_setlist=True) has no RehearsalSong rows by
    design (ADR-0003), so its Songs come from the live setlist instead and
    the start_time map is empty.
    """
    if rehearsal.is_full_setlist:
        return list(rehearsal.dress_rehearsal_songs), {}
    rehearsal_songs = RehearsalSong.objects.filter(rehearsal=rehearsal)
    start_times = {rehearsal_song.song_id: rehearsal_song.start_time for rehearsal_song in rehearsal_songs}
    songs = list(Song.objects.filter(pk__in=start_times.keys()).order_by('position'))
    return songs, start_times


def _assignments_by_song_role(songs, roles):
    """Return {(song_id, role_id): [SongRoleAssignment, ...]} for every assignment among `songs`/`roles`."""
    assignments = SongRoleAssignment.objects.filter(
        song__in=songs, role__in=roles,
    ).select_related('person', 'role').order_by('person__name')
    result = {}
    for assignment in assignments:
        result.setdefault((assignment.song_id, assignment.role_id), []).append(assignment)
    return result


def upcoming_rehearsals_for(semester, count=3):
    """Return `semester`'s next `count` upcoming Rehearsals, band-wide, in date order."""
    return list(_upcoming_rehearsals(semester)[:count])


def _upcoming_rehearsals(semester):
    """Return `semester`'s not-yet-ended Rehearsals, in date order — the shared basis for both #94 lookups.

    A future-dated Rehearsal always qualifies; a same-day one only qualifies
    if its end_time hasn't passed yet, so a Rehearsal earlier today that's
    already over doesn't linger as someone's "next" one.
    """
    today = timezone.localdate()
    now = timezone.localtime().time()
    return Rehearsal.objects.filter(semester=semester).filter(
        Q(date__gt=today) | Q(date=today, end_time__gte=now),
    ).order_by('date', 'start_time')


def attendance_suggestion_for(rehearsal, person):
    """Return `person`'s suggested arrival/departure time-window for `rehearsal`, or None if not needed at all.

    Derived from the Person's earliest/latest assigned RehearsalSong
    start_time/end_time within `rehearsal`, minus/plus the Rehearsal's
    arrival_buffer_minutes/departure_buffer_minutes (already defaulted from
    the Semester at Rehearsal creation time). Falls back to the Rehearsal's
    own start_time/end_time, with no buffer applied, whenever
    attendance_for reports full-window attendance (needed at both ends) —
    and, for the Dress Rehearsal (ADR-0003, no persisted RehearsalSong
    rows), whenever the Person has any assignment among the live setlist at
    all, since there's no per-song clock time to derive a narrower window
    from.
    """
    if rehearsal.is_full_setlist:
        return _dress_rehearsal_attendance_suggestion(rehearsal, person)
    return _regular_rehearsal_attendance_suggestion(rehearsal, person)


def _dress_rehearsal_attendance_suggestion(rehearsal, person):
    """Return the Dress Rehearsal's own start/end as `person`'s suggestion, or None if they have no assignment."""
    has_assignment = SongRoleAssignment.objects.filter(
        person=person, song__in=rehearsal.dress_rehearsal_songs,
    ).exists()
    if not has_assignment:
        return None
    return AttendanceSuggestion(arrival_time=rehearsal.start_time, departure_time=rehearsal.end_time)


def _regular_rehearsal_attendance_suggestion(rehearsal, person):
    """Return `person`'s suggestion for a non-Dress Rehearsal, derived from their assigned RehearsalSong slots."""
    bounds = RehearsalSong.objects.filter(
        rehearsal=rehearsal, song__songroleassignment__person=person,
    ).aggregate(earliest_start=models.Min('start_time'), latest_end=models.Max('end_time'))
    if bounds['earliest_start'] is None:
        return None
    attendance = rehearsal.attendance_for(person)
    if attendance.needed_from_start and attendance.needed_until_end:
        return AttendanceSuggestion(arrival_time=rehearsal.start_time, departure_time=rehearsal.end_time)
    arrival_time = _shift_time(rehearsal.date, bounds['earliest_start'], -rehearsal.arrival_buffer_minutes)
    departure_time = _shift_time(rehearsal.date, bounds['latest_end'], rehearsal.departure_buffer_minutes)
    return AttendanceSuggestion(arrival_time=arrival_time, departure_time=departure_time)


def _shift_time(date, time_value, minutes):
    """Return `time_value` on `date` shifted by `minutes` (may be negative), as a plain time."""
    return (datetime.combine(date, time_value) + timedelta(minutes=minutes)).time()


@dataclass(frozen=True)
class RehearsalListRow:
    """One row of the All-Rehearsals view: a Rehearsal plus `person`'s one-line attendance summary (issue #97)."""

    rehearsal: Rehearsal
    attendance_suggestion: AttendanceSuggestion | None


@dataclass(frozen=True)
class RehearsalSchedule:
    """`semester`'s Rehearsals, split into past/future rows for the All-Rehearsals view (issue #97)."""

    past: list[RehearsalListRow]
    future: list[RehearsalListRow]


def rehearsal_schedule_for(semester, person) -> RehearsalSchedule:
    """Return `semester`'s Rehearsals split into past/future, each row carrying `person`'s attendance summary.

    Split is by date only (today counts as future) per issue #97's spec —
    unlike _upcoming_rehearsals, this is a display grouping for the
    All-Rehearsals list, not a "what's next" lookup, so a same-day
    already-ended Rehearsal still renders in the future/expanded section
    rather than being hidden away with the past ones.
    """
    today = timezone.localdate()
    rehearsals = Rehearsal.objects.filter(semester=semester).order_by('date', 'start_time')
    past, future = [], []
    for rehearsal in rehearsals:
        row = RehearsalListRow(
            rehearsal=rehearsal,
            attendance_suggestion=attendance_suggestion_for(rehearsal, person),
        )
        (past if rehearsal.date < today else future).append(row)
    return RehearsalSchedule(past=past, future=future)


@dataclass(frozen=True)
class Break:
    """One gap of idle time between two of a Person's assigned RehearsalSong slots (issue #96)."""

    start_time: time
    end_time: time


def breaks_for(rehearsal, person) -> list[Break]:
    """Return `person`'s idle-time gaps between their own assigned RehearsalSong slots at `rehearsal` (issue #96).

    Walks the Rehearsal's RehearsalSong rows that `person` is assigned to
    (via any SongRoleAssignment on the row's Song), in `order`. Each
    consecutive pair whose end_time/start_time don't line up back-to-back
    means an intervening, unassigned slot sits between them — that gap is a
    break. A Person with zero assigned slots gets an empty list here (the
    view treats that as "not needed at this rehearsal", not a break). The
    Dress Rehearsal always returns an empty list: it has no persisted
    RehearsalSong rows to compute a gap from (ADR-0003).
    """
    if rehearsal.is_full_setlist:
        return []
    assigned_slots = list(
        RehearsalSong.objects.filter(
            rehearsal=rehearsal, song__songroleassignment__person=person,
        ).distinct().order_by('order'),
    )
    breaks = []
    for earlier, later in pairwise(assigned_slots):
        if earlier.end_time < later.start_time:
            breaks.append(Break(start_time=earlier.end_time, end_time=later.start_time))
    return breaks


CONFLICT_FULL_ABSENCE = 'full_absence'
CONFLICT_LATE_ARRIVAL = 'late_arrival'
CONFLICT_EARLY_DEPARTURE = 'early_departure'
CONFLICT_DECLARATION_CHOICES = (
    (CONFLICT_FULL_ABSENCE, 'Unavailable for entire rehearsal'),
    (CONFLICT_LATE_ARRIVAL, 'Arrive late at'),
    (CONFLICT_EARLY_DEPARTURE, 'Leave early at'),
)


def future_rehearsals_for(semester) -> list[Rehearsal]:
    """Return `semester`'s Rehearsals dated today or later, in date order (issue #98's Upcoming Rehearsals list)."""
    today = timezone.localdate()
    return list(Rehearsal.objects.filter(semester=semester, date__gte=today).order_by('date', 'start_time'))


def declare_conflict(person, rehearsal, declaration_type, declared_time=None, reason='') -> Conflict:
    """Create a Conflict (plus, for a partial type, its one ConflictWindow) from an inline declaration (issue #98).

    The three declaration types map to the model layer as follows, and
    this is the only place that mapping is implemented — the Upcoming
    Rehearsals view never calls Conflict/ConflictWindow .save() directly:
    - full_absence: a FULL_CONFLICT Conflict, no ConflictWindow.
    - late_arrival: a PARTIAL Conflict with one ConflictWindow spanning
      the Rehearsal's start_time to `declared_time`.
    - early_departure: a PARTIAL Conflict with one ConflictWindow spanning
      `declared_time` to the Rehearsal's end_time.
    """
    with transaction.atomic():
        if declaration_type == CONFLICT_FULL_ABSENCE:
            return Conflict.objects.create(
                person=person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT, reason=reason,
            )
        if declaration_type in (CONFLICT_LATE_ARRIVAL, CONFLICT_EARLY_DEPARTURE):
            conflict = Conflict.objects.create(
                person=person, rehearsal=rehearsal, type=Conflict.PARTIAL, reason=reason,
            )
            if declaration_type == CONFLICT_LATE_ARRIVAL:
                window_start, window_end = rehearsal.start_time, declared_time
            else:
                window_start, window_end = declared_time, rehearsal.end_time
            ConflictWindow.objects.create(conflict=conflict, unavailable_start=window_start, unavailable_end=window_end)
            return conflict
        raise ValueError(f'Unknown conflict declaration_type: {declaration_type!r}')
