"""Application services for the scheduling domain."""

from dataclasses import dataclass
from uuid import uuid4

from botocore.exceptions import ClientError
from django.core.files.storage import storages
from django.db import IntegrityError, transaction

from scheduling.models import Recording, RehearsalSong

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
    """The opaque private-object key and temporary PUT URL for one audio take."""

    object_key: str
    upload_url: str


def reserve_recording_upload(content_type: str, file_size: int) -> RecordingUploadReservation:
    """Validate client metadata and return a short-lived direct R2 PUT reservation."""
    _validate_recording_metadata(content_type, file_size)
    object_key = _new_recording_object_key(content_type)
    upload_url = _presign(
        'put_object',
        object_key,
        extra_params={'ContentType': content_type},
        http_method='PUT',
    )
    return RecordingUploadReservation(object_key=object_key, upload_url=upload_url)


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
