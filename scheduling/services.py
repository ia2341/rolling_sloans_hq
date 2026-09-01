"""Application services for the scheduling domain."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from uuid import uuid4

from botocore.exceptions import ClientError
from django.core.files.storage import storages
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from scheduling.models import (
    Recording,
    Rehearsal,
    RehearsalSong,
    Semester,
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
    """Return `person`'s next upcoming Rehearsal in `semester` where attendance_for reports any need, else None.

    "Next" is not necessarily the band's literal next Rehearsal: this walks
    the Semester's upcoming Rehearsals in date order and returns the first
    one where Rehearsal.attendance_for(person) reports at least one True
    (issue #94), skipping any Rehearsal the Person isn't needed at.
    """
    for rehearsal in _upcoming_rehearsals(semester):
        attendance = rehearsal.attendance_for(person)
        if attendance.needed_from_start or attendance.needed_until_end:
            return rehearsal
    return None


def upcoming_rehearsals_for(semester, count=3):
    """Return `semester`'s next `count` upcoming Rehearsals, band-wide, in date order."""
    return list(_upcoming_rehearsals(semester)[:count])


def _upcoming_rehearsals(semester):
    """Return `semester`'s Rehearsals from today onward, in date order — the shared basis for both #94 lookups."""
    return Rehearsal.objects.filter(semester=semester, date__gte=timezone.localdate()).order_by('date', 'start_time')


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
