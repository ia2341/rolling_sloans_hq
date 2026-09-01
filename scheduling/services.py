"""Application services for the scheduling domain."""

from dataclasses import dataclass
from datetime import time
from uuid import uuid4

from botocore.exceptions import ClientError
from django.core.files.storage import storages
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from scheduling.models import (
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


def next_rehearsal_for(person, semester) -> Rehearsal | None:
    """Return `person`'s next upcoming Rehearsal in `semester` they're on the roster for, else None (issue #95).

    "Next" is not necessarily the band's literal next Rehearsal: this walks
    the Semester's Rehearsals from today onward in date order and returns
    the first one where `person` has a SongRoleAssignment on any of its
    Songs (via `_matrix_songs`, the same Rehearsal-scoped Song set the
    assignment matrix itself renders — the Dress Rehearsal's live setlist
    for `is_full_setlist=True`, RehearsalSong-linked Songs otherwise),
    skipping any Rehearsal they have no assignment at. Deliberately not
    `Rehearsal.attendance_for` (issue #38), which only reports need at the
    Rehearsal's first/last slot and would wrongly skip a Rehearsal where
    the Person is assigned only to a middle Song. This is the default
    landing Rehearsal for the shared rehearsal-detail view (ScheduleView).
    """
    upcoming = Rehearsal.objects.filter(semester=semester, date__gte=timezone.localdate()).order_by(
        'date', 'start_time',
    )
    for rehearsal in upcoming:
        songs, _ = _matrix_songs(rehearsal)
        if SongRoleAssignment.objects.filter(person=person, song__in=songs).exists():
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
