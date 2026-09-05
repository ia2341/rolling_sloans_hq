"""Application services for the scheduling domain."""

import logging
import random
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from itertools import pairwise, permutations
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from django.core.files.storage import storages
from django.db import IntegrityError, models, transaction
from django.db.models import Count, Q
from django.utils import timezone

from identity.models import Person
from scheduling.fields import format_song_length
from scheduling.models import (
    Backup,
    Conflict,
    ConflictWindow,
    Membership,
    MembershipRole,
    Recording,
    Rehearsal,
    RehearsalPattern,
    RehearsalSong,
    RehearsalTime,
    Role,
    Semester,
    SkipDate,
    Song,
    SongRoleAssignment,
    SongRoleRequirement,
    slots_for_person,
)

logger = logging.getLogger(__name__)

MAX_RECORDING_FILE_SIZE = 50 * 1024 * 1024
VIEWING_SEMESTER_SESSION_KEY = 'viewing_semester_id'
SEMESTER_STATUS_LIVE = 'Live'
SEMESTER_STATUS_DRAFT = 'Draft'
SEMESTER_STATUS_PREVIOUSLY_PUBLISHED = 'Previously published'
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
class SemesterOption:
    """One entry in the admin's Semester dropdown: a Semester, its Live/Draft/Previously-published label, whether it's the one on screen, and its counts.

    `member_count`, `song_count` and `rehearsal_count` are the three counts
    the `/api/` sidebar's dropdown wants on every entry without a per-option
    query (issue #326) — `semester_options_for()` annotates them onto the
    single queryset it already builds, rather than issuing one query per
    Semester per count.
    """

    semester: Semester
    status: str
    is_viewing: bool
    member_count: int
    song_count: int
    rehearsal_count: int


@dataclass(frozen=True)
class SemesterBanner:
    """The shell's warning that this request is scoped to a Semester members can't see, plus the Live Semester to return to (None when nothing is published)."""

    semester: Semester
    live_semester: Semester | None


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


@dataclass(frozen=True)
class RecordingSlotGroup:
    """One RehearsalSong slot's Recordings, for the Song detail page's grouped display (issue #104)."""

    rehearsal_song: RehearsalSong
    recordings: list[Recording]


def recording_groups_for(song: Song) -> list[RecordingSlotGroup]:
    """Return `song`'s Recordings grouped by RehearsalSong slot, ordered by Rehearsal date then slot order.

    Slots with no Recordings are omitted rather than rendered empty, so the
    Song detail page shows only slots that actually have takes.
    """
    recordings = (
        Recording.objects.filter(rehearsal_song__song=song)
        .select_related('rehearsal_song__rehearsal', 'uploaded_by')
        .order_by('rehearsal_song__rehearsal__date', 'rehearsal_song__order', 'uploaded_at')
    )
    grouped: dict[int, list[Recording]] = {}
    slots_in_order: list[RehearsalSong] = []
    for recording in recordings:
        rehearsal_song = recording.rehearsal_song
        if rehearsal_song.pk not in grouped:
            grouped[rehearsal_song.pk] = []
            slots_in_order.append(rehearsal_song)
        grouped[rehearsal_song.pk].append(recording)
    return [
        RecordingSlotGroup(rehearsal_song=rehearsal_song, recordings=grouped[rehearsal_song.pk])
        for rehearsal_song in slots_in_order
    ]


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


def get_live_semester() -> Semester | None:
    """Return the Live Semester — the greatest `published_at`, nulls excluded — or None if nothing is published.

    This is the answer to "what do members see", and it takes no request:
    every non-admin sees the same Semester, always. A Semester with a null
    `published_at` is a draft and can never be live (ADR-0010).

    Ties on `published_at` fall back to the greater id, so the result is
    deterministic even when two rows are published in the same instant.
    """
    return Semester.objects.exclude(published_at=None).order_by('-published_at', '-id').first()


class InvalidSemesterNameError(ValueError):
    """Raised by `create_semester()` for a blank name, or one matching an existing Semester (issue #200)."""


def create_semester(name: str, **timing_defaults) -> Semester:
    """Create and return a new draft Semester (`published_at` null) named `name`, carrying `timing_defaults` (issue #200).

    The one seam Semester setup adds outside the Django admin panel: it
    takes no semester row lock (it renumbers nothing and the row does not
    exist yet) and registers no side effect. `name` is compared
    case-insensitively against every existing Semester, live or draft, so
    two terms an admin cannot tell apart by name is never possible; a blank
    or duplicate name raises `InvalidSemesterNameError` before anything is
    written, and every other Semester is left untouched.
    """
    name = name.strip()
    if not name:
        raise InvalidSemesterNameError('Name your new semester before continuing.')
    if Semester.objects.filter(name__iexact=name).exists():
        raise InvalidSemesterNameError(f'A semester named "{name}" already exists — choose a different name.')
    return Semester.objects.create(name=name, **timing_defaults)


def publish_semester(semester: Semester) -> None:
    """Stamp `semester.published_at` to now — the whole of Publish (issue #170).

    Visibility only: it never gates or locks edits inside the Semester.
    Bumping `published_at` on an already-live Semester is harmless and is
    the same code path rollback uses — re-publishing an older Semester
    simply makes that one's `published_at` the greatest again.
    """
    semester.published_at = timezone.now()
    semester.save(update_fields=['published_at'])


class LiveSemesterDeletionError(ValueError):
    """Raised when a caller attempts to delete the Live Semester (issue #171)."""


@dataclass(frozen=True)
class SemesterDeletionSummary:
    """Counts of what deleting a Semester would destroy, for the confirmation surface (issue #171)."""

    member_count: int
    song_count: int
    rehearsal_count: int
    recording_count: int


def semester_deletion_summary(semester: Semester) -> SemesterDeletionSummary:
    """Return the counts of Memberships, Songs, Rehearsals and Recordings a delete of `semester` would destroy."""
    return SemesterDeletionSummary(
        member_count=Membership.objects.filter(semester=semester).count(),
        song_count=Song.objects.filter(semester=semester).count(),
        rehearsal_count=Rehearsal.objects.filter(semester=semester).count(),
        recording_count=Recording.objects.filter(rehearsal_song__rehearsal__semester=semester).count(),
    )


def delete_semester(semester: Semester) -> None:
    """Hard-delete `semester` and everything scoped to it, including its Recordings' storage objects (issue #171).

    Refuses the Live Semester so no caller — view or otherwise — can route
    around that protection (ADR 0011). The cascade (FK `on_delete=CASCADE`)
    destroys Memberships, MembershipRoles, Songs, SongRoleRequirements,
    SongRoleAssignments, Rehearsals, RehearsalSongs, Conflicts,
    ConflictWindows and Recordings; every Person row is untouched.

    Recording object keys are collected before the cascade, since the rows
    naming them are gone afterwards. Their storage deletion is registered
    with `transaction.on_commit()` and is best-effort: a storage failure is
    logged, never raised, and never rolls back or blocks the Semester
    deletion that already committed.
    """
    if semester == get_live_semester():
        raise LiveSemesterDeletionError('The Live Semester cannot be deleted.')
    object_keys = list(
        Recording.objects.filter(rehearsal_song__rehearsal__semester=semester).values_list('file', flat=True)
    )
    semester.delete()
    if object_keys:
        transaction.on_commit(lambda: _delete_recording_objects(object_keys))


def _delete_recording_objects(object_keys: list[str]) -> None:
    """Best-effort delete each of `object_keys` from private storage, logging rather than raising on failure.

    Runs inside a `transaction.on_commit()` callback, after the Semester row
    is already gone — any exception here must be swallowed, not just a
    `ClientError` (a network-level outage raises `BotoCoreError`, not
    `ClientError`), or it would surface as a 500 on a request that already
    succeeded.
    """
    storage = _recording_storage()
    client = storage.connection.meta.client
    for object_key in object_keys:
        try:
            client.delete_object(Bucket=storage.bucket_name, Key=object_key)
        except (ClientError, BotoCoreError):
            logger.exception('Failed to delete recording object %r from storage after Semester deletion.', object_key)


def reorder_songs(semester: Semester, ordered_song_ids: list[int]) -> None:
    """Renumber `ordered_song_ids`'s Songs to a contiguous 1..N, in that order (issue #179).

    The setlist edit grid's Save is the only caller: `ordered_song_ids` is
    the buffer's surviving row order (deleted rows already excluded), never
    a client-submitted position. Must run inside the caller's
    `transaction.atomic()` — a whole-table renumber briefly assigns
    positions that collide with each other's prior values, which is only
    free of a mid-transaction constraint violation because
    `unique_song_position_per_semester` is `Deferrable.DEFERRED`.
    """
    songs_by_id = {song.pk: song for song in Song.objects.filter(semester=semester, pk__in=ordered_song_ids)}
    for position, song_id in enumerate(ordered_song_ids, start=1):
        song = songs_by_id[song_id]
        song.position = position
        song.save(update_fields=['position'])


def reorder_rehearsal_songs(rehearsal: Rehearsal, ordered_rehearsal_song_ids: list[int]) -> None:
    """Renumber a Rehearsal's Running Order to a contiguous 1..N and re-derive persisted times (issue #215).

    Mirrors `reorder_songs()`'s shape, but `unique_order_per_rehearsal`
    isn't `Deferrable.DEFERRED` (unlike `unique_song_position_per_semester`),
    so a permutation of the existing order can't be written in one pass —
    two rows could momentarily want each other's `order` value. A first
    pass moves every row to a placeholder `order` strictly above the final
    `1..N` range (and mutually distinct), clear of both the final range and
    each other; the second pass then assigns the final contiguous order in
    `ordered_rehearsal_song_ids`' sequence, saving each row in that order.
    Placeholders must land *above* N, not merely outside `1..N` (e.g. not
    negative): `RehearsalSong._prior_slots()` sums the `slot_count` of rows
    with a lower `order`, so a not-yet-finalized sibling must compare as
    "later" during the second pass, or its slot_count would be wrongly
    counted as prior and skew every row's re-derived `start_time`/`end_time`.
    They must also clear each *surviving* row's current `order`, not just
    `N` — a prior deletion elsewhere can leave survivors with non-contiguous
    order values above `N` (e.g. 1 and 3 surviving out of a deleted 2), and
    a placeholder landing on one of those would collide with it before it's
    had its own turn to move. Saving in `ordered_rehearsal_song_ids`'
    sequence during the second pass is what makes `RehearsalSong.save()`
    re-derive correct times: each row's lower-order siblings are already
    saved with their final order by the time it's this row's turn. This
    is also the fix for the stale times
    a Rehearsal window edit used to leave behind: the caller passes the
    *current* order unchanged (an identity permutation) just to force every
    row's times to be recomputed against the Rehearsal's new window.

    Must run inside the caller's `transaction.atomic()`, same as
    `reorder_songs()`.
    """
    rehearsal_songs_by_id = {
        rehearsal_song.pk: rehearsal_song
        for rehearsal_song in RehearsalSong.objects.filter(rehearsal=rehearsal, pk__in=ordered_rehearsal_song_ids)
    }
    song_count = len(ordered_rehearsal_song_ids)
    placeholder_base = max([song_count, *(rs.order for rs in rehearsal_songs_by_id.values())])
    for offset, rehearsal_song_id in enumerate(ordered_rehearsal_song_ids, start=1):
        rehearsal_song = rehearsal_songs_by_id[rehearsal_song_id]
        rehearsal_song.order = placeholder_base + offset
        rehearsal_song.save()
    for position, rehearsal_song_id in enumerate(ordered_rehearsal_song_ids, start=1):
        rehearsal_song = rehearsal_songs_by_id[rehearsal_song_id]
        rehearsal_song.order = position
        rehearsal_song.save()


@dataclass(frozen=True)
class SongDeletionSummary:
    """One doomed Song's recording/uploader counts, for the setlist edit grid's delete confirmation (issue #179)."""

    song: Song
    recording_count: int
    uploader_count: int


def song_deletion_summaries(songs) -> list['SongDeletionSummary']:
    """Return each of `songs`' recording count and distinct-uploader count, for the delete confirmation dialog.

    A pure counts read: no locking, no transaction, nothing written. Not
    ADR-0008 preview machinery — there is nothing to roll back.
    """
    summaries = []
    for song in songs:
        recordings = Recording.objects.filter(rehearsal_song__song=song)
        summaries.append(SongDeletionSummary(
            song=song,
            recording_count=recordings.count(),
            uploader_count=recordings.values('uploaded_by').distinct().count(),
        ))
    return summaries


def delete_songs_with_recordings(songs) -> None:
    """Hard-delete `songs`, cleaning up their Recordings' storage objects (issue #179).

    Mirrors `delete_semester`'s shape (issue #171): the cascade
    (`RehearsalSong.song` and `Recording.rehearsal_song` both
    `on_delete=CASCADE`) destroys every RehearsalSong and Recording row for
    these Songs, so object keys are collected first, while they're still
    reachable. Storage deletion is registered with `transaction.on_commit()`
    and reuses `_delete_recording_objects`'s best-effort, log-don't-raise
    behavior — a storage failure never blocks or rolls back the Save this
    runs inside.
    """
    song_ids = [song.pk for song in songs]
    if not song_ids:
        return
    object_keys = list(
        Recording.objects.filter(rehearsal_song__song_id__in=song_ids).values_list('file', flat=True)
    )
    Song.objects.filter(pk__in=song_ids).delete()
    if object_keys:
        transaction.on_commit(lambda: _delete_recording_objects(object_keys))


def delete_rehearsal_songs_with_recordings(rehearsal_songs) -> None:
    """Hard-delete `rehearsal_songs`, cleaning up their Recordings' storage objects (issue #220).

    Mirrors `delete_songs_with_recordings()`'s shape: `Recording.rehearsal_song`
    is `on_delete=CASCADE`, so object keys are collected first, while
    they're still reachable. Storage deletion is registered with
    `transaction.on_commit()` and reuses `_delete_recording_objects`'s
    best-effort, log-don't-raise behavior — a storage failure never blocks
    or rolls back the Save this runs inside. Deleting a recorded row by
    hand is deliberately allowed here (unlike the bulk generator, which
    refuses to touch one) — a room genuinely worked its songs in a
    different order, and that correction is on the admin, not the tool.
    """
    ids = [rehearsal_song.pk for rehearsal_song in rehearsal_songs]
    if not ids:
        return
    object_keys = list(Recording.objects.filter(rehearsal_song_id__in=ids).values_list('file', flat=True))
    RehearsalSong.objects.filter(pk__in=ids).delete()
    if object_keys:
        transaction.on_commit(lambda: _delete_recording_objects(object_keys))


def delete_rehearsals_with_recordings(rehearsals) -> None:
    """Hard-delete `rehearsals`, cleaning up their Recordings' storage objects (issue #221).

    Mirrors `delete_songs_with_recordings()`/`delete_rehearsal_songs_with_recordings()`'s
    shape: the cascade (`RehearsalSong.rehearsal` and `Conflict.rehearsal`
    both `on_delete=CASCADE`) destroys every RehearsalSong, Recording,
    Conflict and ConflictWindow row scoped to these Rehearsals, so
    Recording object keys are collected first, while they're still
    reachable. Storage deletion is registered with `transaction.on_commit()`
    and reuses `_delete_recording_objects`'s best-effort, log-don't-raise
    behavior — a storage failure never blocks or rolls back the Save this
    runs inside. Conflict rows destroyed by this cascade are never counted
    or enumerated anywhere (ADR 0005): a bare count would add nothing.

    Deleting a Rehearsal that carries Recordings is deliberately allowed
    here — unlike `preview_rehearsal_generation()`'s Orphan bucket (issue
    #222), which disables its delete checkbox outright whenever an orphan
    carries at least one Recording. That asymmetry is intentional: the
    generator is blind and bulk, acting on a Pattern re-run an admin didn't
    review row by row, so it protects itself; this manual per-row path
    always runs behind the destructive-save confirmation dialog, where an
    admin has already seen exactly what they're removing.
    """
    ids = [rehearsal.pk for rehearsal in rehearsals]
    if not ids:
        return
    object_keys = list(
        Recording.objects.filter(rehearsal_song__rehearsal_id__in=ids).values_list('file', flat=True)
    )
    Rehearsal.objects.filter(pk__in=ids).delete()
    if object_keys:
        transaction.on_commit(lambda: _delete_recording_objects(object_keys))


def get_viewing_semester(request) -> Semester | None:
    """Return the Semester `request` is scoped to, for reads and writes alike.

    The single place that answers "which Semester am I looking at", so no
    view re-derives its own notion and they cannot drift apart:

    - a non-admin gets the Live Semester, or None. A session selection on a
      non-admin account is ignored, never honoured, so an account that has
      lost `is_admin` immediately sees exactly what a member sees.
    - an admin with a session selection gets that Semester — including a
      draft, which is what makes an admin's writes land on the draft.
    - an admin with no selection gets the Live Semester; and with nothing
      published at all, the most recently *created* Semester, so a solo
      admin bootstrapping the first term isn't trapped in empty states.
      Members never get that fallback.

    A selection pointing at a since-deleted Semester falls back silently to
    the Live Semester rather than raising.
    """
    if not _is_admin(getattr(request, 'user', None)):
        return get_live_semester()
    selected_id = request.session.get(VIEWING_SEMESTER_SESSION_KEY)
    if selected_id is not None:
        selected = Semester.objects.filter(pk=selected_id).first()
        if selected is not None:
            return selected
    return get_live_semester() or Semester.objects.order_by('-created_at', '-id').first()


def semester_options_for(request) -> list['SemesterOption']:
    """Return every Semester as a switcher option, newest-created first, or nothing for a non-admin (issue #169).

    The label distinguishes the three states an admin has to tell apart at a
    glance: the Live Semester, a Draft (null `published_at`), and a
    Previously published one — a term that was live and has since been
    superseded. Exactly one option carries `is_viewing`, matching whatever
    `get_viewing_semester()` resolves, so the dropdown preselects the same
    Semester the page is actually rendering.

    A member gets an empty list rather than a hidden one: there is nothing
    for them to choose between, so the data never reaches the template.
    """
    if not _is_admin(getattr(request, 'user', None)):
        return []
    live = get_live_semester()
    viewing = get_viewing_semester(request)
    semesters = Semester.objects.order_by('-created_at', '-id').annotate(
        member_count=Count('membership', distinct=True),
        song_count=Count('song', distinct=True),
        rehearsal_count=Count('rehearsal', distinct=True),
    )
    return [
        SemesterOption(
            semester=semester,
            status=_semester_status(semester, live),
            is_viewing=viewing is not None and semester.pk == viewing.pk,
            member_count=semester.member_count,
            song_count=semester.song_count,
            rehearsal_count=semester.rehearsal_count,
        )
        for semester in semesters
    ]


def _semester_status(semester: Semester, live: Semester | None) -> str:
    """Return `semester`'s switcher label, given the already-resolved Live Semester."""
    if live is not None and semester.pk == live.pk:
        return SEMESTER_STATUS_LIVE
    if semester.published_at is None:
        return SEMESTER_STATUS_DRAFT
    return SEMESTER_STATUS_PREVIOUSLY_PUBLISHED


def semester_banner_for(request) -> 'SemesterBanner | None':
    """Return the warning banner for a request resolved to something other than the Live Semester, else None (issue #169).

    Only an admin can ever be looking at a non-live Semester, so a member
    always gets None. `live_semester` is carried alongside so the banner can
    offer a way back — and is itself None when nothing is published at all,
    the bootstrapping case where an admin views the newest draft by fallback
    and there is nowhere to return to.
    """
    if not _is_admin(getattr(request, 'user', None)):
        return None
    viewing = get_viewing_semester(request)
    if viewing is None:
        return None
    live = get_live_semester()
    if live is not None and viewing.pk == live.pk:
        return None
    return SemesterBanner(semester=viewing, live_semester=live)


def set_viewing_semester(request, semester: Semester | None) -> None:
    """Record `semester` as this request's session selection, or clear the selection when given None.

    The selection lives in `request.session` and therefore dies at logout —
    chosen over a `?semester=` param or an `/s/<id>/` URL prefix because the
    admin controls that read it are inlined onto the existing member-facing
    pages, where a URL-borne selection would have to be threaded through
    every link and form.
    """
    if semester is None:
        request.session.pop(VIEWING_SEMESTER_SESSION_KEY, None)
        return
    request.session[VIEWING_SEMESTER_SESSION_KEY] = semester.pk


def _is_admin(user) -> bool:
    """Return whether `user` is a logged-in admin — False for anonymous or missing users."""
    return bool(user is not None and getattr(user, 'is_authenticated', False) and getattr(user, 'is_admin', False))


def roster_for(memberships):
    """Return `memberships` as the Band Members roster: ordered by Person name, carrying Roles and a Song count (issue #137).

    Takes a Membership queryset rather than a Semester so the caller keeps
    the no-viewing-Semester empty state in one place (the
    `_scoped_to_viewing_semester` idiom in `views.py`).

    Each row is annotated with `songs_count` — the number of distinct Songs
    in that Membership's own Semester the Person holds any
    SongRoleAssignment on, counted regardless of is_role_mismatch per
    ADR-0002 — and prefetches its MembershipRoles in Role-name order. Both
    are batched deliberately: the roster's cardinality is the band, so the
    per-row lookups `SetlistView` does per Song would grow the query count
    with the roster.
    """
    return memberships.select_related('person').prefetch_related(
        models.Prefetch(
            'membershiprole_set',
            queryset=MembershipRole.objects.select_related('role').order_by('role__name'),
        ),
    ).annotate(
        songs_count=Count(
            'person__songroleassignment__song',
            filter=Q(person__songroleassignment__song__semester=models.F('semester')),
            distinct=True,
        ),
    ).order_by('person__name')


def declared_roles_for(membership):
    """Return `membership`'s declared Roles for its Semester, in name order (issue #138).

    Empty for an unsaved Membership — the not-yet-rostered self case on
    `/members/<pk>/`, which has no MembershipRole rows to reach.
    """
    if membership.pk is None:
        return Role.objects.none()
    return Role.objects.filter(membershiprole__membership=membership).order_by('name')


def mismatched_person_ids_for(semester) -> frozenset[int]:
    """Return the ids of every Person holding a mismatched SongRoleAssignment on `semester`'s Songs (issue #227).

    Backs the Roster editor's quiet per-row completeness flag: a batched
    lookup rather than one query per row, so the flag's cost doesn't grow
    with the roster.
    """
    return frozenset(
        SongRoleAssignment.objects.filter(
            song__semester=semester, is_role_mismatch=True,
        ).values_list('person_id', flat=True)
    )


def assigned_songs_for(person, semester):
    """Return `person`'s SongRoleAssignments on `semester`'s Songs, in setlist-position order (issue #138).

    Counted and rendered regardless of `is_role_mismatch` per ADR-0002 —
    the flag itself stays off this surface
    (`docs/person-page-visibility.md`).
    """
    return SongRoleAssignment.objects.filter(
        person=person, song__semester=semester,
    ).select_related('song', 'role').order_by('song__position')


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


@dataclass(frozen=True)
class SongPerformer:
    """One Person who performs on a Song, plus every Role they fill on it (issue #103)."""

    person: object
    roles: list[Role]


def performers_for(song) -> list[SongPerformer]:
    """Return `song`'s distinct performers, ordered by name, each carrying every Role they fill on it.

    A Person appearing under multiple roles on the same Song (e.g. singer
    and guitarist) is deduped into one SongPerformer listing all their
    Roles, rather than showing up as separate rows — the Songs page
    performers column (issue #103) needs one entry per person, not per
    SongRoleAssignment.
    """
    assignments = SongRoleAssignment.objects.filter(song=song).select_related('person', 'role').order_by(
        'person__name', 'role__name',
    )
    roles_by_person_id: dict[int, list[Role]] = {}
    people_in_order = []
    for assignment in assignments:
        if assignment.person_id not in roles_by_person_id:
            roles_by_person_id[assignment.person_id] = []
            people_in_order.append(assignment.person)
        roles_by_person_id[assignment.person_id].append(assignment.role)
    return [
        SongPerformer(person=person, roles=roles_by_person_id[person.id])
        for person in people_in_order
    ]


@dataclass(frozen=True)
class RoleFillStatus:
    """One SongRoleRequirement's target headcount versus its Role's actual assignment count (issue #207).

    A Requirement is a target, never a cap (issue #33): sitting at or over
    target is the normal, unflagged case, and only `is_understaffed`
    distinguishes the quiet under-target state a member can notice and
    volunteer to fill. `is_retired_role` surfaces a Requirement naming a
    Role that's since been deactivated, without hiding it.
    """

    role: Role
    target: int
    actual: int
    is_understaffed: bool
    is_retired_role: bool


def fill_status_for(song) -> list[RoleFillStatus]:
    """Return `song`'s Role Requirements as target-vs-actual fill status, ordered by Role name.

    A Song with no Requirements returns an empty list rather than raising. A
    Requirement naming a retired Role is included and flagged via
    `is_retired_role`, never filtered out, since it's real data an admin may
    want to clear later (issue #207).
    """
    requirements = SongRoleRequirement.objects.filter(song=song).select_related('role').order_by('role__name')
    actual_by_role_id = dict(
        SongRoleAssignment.objects.filter(song=song)
        .values('role_id')
        .annotate(actual=Count('id'))
        .values_list('role_id', 'actual'),
    )
    return [
        RoleFillStatus(
            role=requirement.role,
            target=requirement.count,
            actual=actual_by_role_id.get(requirement.role_id, 0),
            is_understaffed=actual_by_role_id.get(requirement.role_id, 0) < requirement.count,
            is_retired_role=not requirement.role.is_active,
        )
        for requirement in requirements
    ]


def recording_count_for(song) -> int:
    """Return the all-time count of Recordings across every RehearsalSong slot for `song` (issue #103).

    Purely informational for the Songs page's recording-count column: 0 is
    a normal, valid count, not an error state, and this counts every past
    Recording regardless of which RehearsalSong slot it was uploaded
    against.
    """
    return Recording.objects.filter(rehearsal_song__song=song).count()


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


def active_roles_for(semester) -> list[Role]:
    """Return `semester`'s active Roles, in a stable name order — the fixed Role set every cast line in the Semester shares.

    Computed once per payload, not per Song (issue #330): deriving the
    set from each Song's own Role Requirements instead would make a Role's
    hue and position shift row to row, the exact property the Setlist's
    constant cast line exists to avoid.
    """
    return list(Role.objects.filter(is_active=True).order_by('name'))


def _derive_role_code(name: str) -> str:
    """Derive a short presentational code from a Role's name: initials of up to 3 words, else its first 3 letters, uppercased.

    Never persisted (issue #330) — `Role` has no `code` field, and adding
    one would be a second name column to keep in sync for something purely
    presentational.
    """
    words = name.split()
    if len(words) >= 2:
        return ''.join(word[0] for word in words[:3]).upper()
    return name[:3].upper()


def role_codes_for(roles: list[Role]) -> dict[int, str]:
    """Return a short code per Role id, derived from its name, falling back to the full name wherever two Roles' derived codes would collide.

    A pill's `title` always names the Role in full regardless (issue
    #330) — this code is a scannable accelerator, never the only channel
    carrying the meaning.
    """
    codes_by_role_id = {role.id: _derive_role_code(role.name) for role in roles}
    code_counts: dict[str, int] = defaultdict(int)
    for code in codes_by_role_id.values():
        code_counts[code] += 1
    roles_by_id = {role.id: role for role in roles}
    return {
        role_id: (roles_by_id[role_id].name if code_counts[code] > 1 else code)
        for role_id, code in codes_by_role_id.items()
    }


@dataclass(frozen=True)
class CastPerformer:
    """One Person filling one Role in a Song's cast line, carrying the ADR-0002 mismatch flag for that Role (issue #330)."""

    person: object
    is_role_mismatch: bool


@dataclass(frozen=True)
class CastRoleEntry:
    """One Role's slot in a Song's cast line: its code and every Person who fills it — empty when nobody does (issue #330)."""

    role: Role
    code: str
    performers: list[CastPerformer]


def cast_line_for(song, roles: list[Role], codes: dict[int, str]) -> list[CastRoleEntry]:
    """Return `song`'s cast as one entry per `roles`, in that fixed order, including an empty entry for an unfilled Role.

    Reshapes `performers_for(song)` — person-first — into the Role-first
    shape the Setlist and Song page need (issue #330): a Role in `roles`
    with nobody assigned still gets an entry with an empty performer list,
    a rendered empty rather than an omission. `roles`/`codes` are computed
    once per payload by the caller (`active_roles_for`/`role_codes_for`),
    never re-derived per Song.
    """
    mismatch_by_role_and_person = {
        (role_id, person_id): is_role_mismatch
        for role_id, person_id, is_role_mismatch in SongRoleAssignment.objects.filter(
            song=song,
        ).values_list('role_id', 'person_id', 'is_role_mismatch')
    }
    performers_by_role_id: dict[int, list[CastPerformer]] = defaultdict(list)
    for performer in performers_for(song):
        for role in performer.roles:
            performers_by_role_id[role.id].append(
                CastPerformer(
                    person=performer.person,
                    is_role_mismatch=mismatch_by_role_and_person.get((role.id, performer.person.id), False),
                ),
            )
    return [
        CastRoleEntry(role=role, code=codes[role.id], performers=performers_by_role_id.get(role.id, []))
        for role in roles
    ]


def setlist_total_running_time(semester) -> str:
    """Return the Setlist's total running time as a musician-readable display string, summed server-side across every Song's length.

    Never a client-side reduce (issue #330): the client renders what this
    returns and derives nothing. A Semester with no Songs returns
    `"0:00"`.
    """
    total = Song.objects.filter(semester=semester).aggregate(total=models.Sum('length'))['total'] or timedelta()
    return format_song_length(total)


@dataclass(frozen=True)
class RehearsedAtRow:
    """One Rehearsal `song` is worked at: a scheduled slot with its times, or the Dress Rehearsal's live "whole setlist" row (ADR-0003, issue #330)."""

    rehearsal: Rehearsal
    is_dress_rehearsal: bool
    start_time: time | None
    end_time: time | None


def rehearsed_at_for(song) -> list[RehearsedAtRow]:
    """Return the Rehearsals `song` is worked at: each RehearsalSong slot's Rehearsal with its slot times, plus the Semester's Dress Rehearsal (if any) as a live "whole setlist" row.

    The Dress Rehearsal carries no persisted RehearsalSong row for any Song
    (ADR-0003) — every Song in the Semester "rehearses" there by
    definition, so it's appended here rather than surfacing from the
    RehearsalSong query.
    """
    rows = [
        RehearsedAtRow(
            rehearsal=rehearsal_song.rehearsal,
            is_dress_rehearsal=False,
            start_time=rehearsal_song.start_time,
            end_time=rehearsal_song.end_time,
        )
        for rehearsal_song in RehearsalSong.objects.filter(song=song)
        .select_related('rehearsal')
        .order_by('rehearsal__date')
    ]
    dress_rehearsal = Rehearsal.objects.filter(semester=song.semester, is_full_setlist=True).first()
    if dress_rehearsal is not None:
        rows.append(
            RehearsedAtRow(rehearsal=dress_rehearsal, is_dress_rehearsal=True, start_time=None, end_time=None),
        )
    return rows


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
    Rehearsal the Person isn't needed at — never the Dress Rehearsal, whose
    suggestion is non-None for everyone (ADR-0006). Deliberately not
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


class AssignmentMatrixEntryKind:
    """The kinds of thing an AssignmentMatrixEntry can wrap (issue #208, #216)."""

    ASSIGNMENT = 'assignment'
    BACKUP = 'backup'


@dataclass(frozen=True)
class AssignmentMatrixEntry:
    """One chip in an assignment matrix cell: a Person plus what kind of thing put them there (issue #208, #216).

    `id` is a stable identity for the underlying row (e.g. a
    SongRoleAssignment's or Backup's pk) that an edit-mode chip can buffer
    removals against; it is not necessarily unique across kinds.
    `covering_for` is only ever set on a BACKUP entry (ADR-0007) and is
    admin-only per ADR-0005 — callers rendering to a member must not
    surface it.
    """

    id: int
    kind: str
    person: Person
    is_role_mismatch: bool
    covering_for: Person | None = None


@dataclass(frozen=True)
class AssignmentMatrixCell:
    """One (Song, Role) cell in an assignment matrix: its ordered chip entries (issue #95, #208, #216).

    `standing_assignees` is the same Persons as the ASSIGNMENT-kind
    entries, pulled out separately so a Backup chip's "covering for"
    select (issue #216) can be built from it without filtering entries by
    kind in every template that needs it.
    """

    role: Role
    entries: list[AssignmentMatrixEntry]
    standing_assignees: list[Person]


@dataclass(frozen=True)
class AssignmentMatrixRow:
    """One Song's row in an assignment matrix: its slot start_time (if any) plus its per-Role cells (issue #95, #216).

    `rehearsal_song_id` is None on the Dress Rehearsal (ADR-0006) — the
    grid uses that to withhold the Backup affordance there, since a
    Backup has nothing to anchor on.
    """

    song: Song
    start_time: time | None
    rehearsal_song_id: int | None
    cells: list[AssignmentMatrixCell]


@dataclass(frozen=True)
class AssignmentMatrix:
    """A Rehearsal's Song x Role x Person assignment grid (issue #95)."""

    roles: list[Role]
    rows: list[AssignmentMatrixRow]


def assignment_matrix_for(rehearsal) -> AssignmentMatrix:
    """Build `rehearsal`'s Song x Role x Person assignment matrix (issue #95, #216).

    Rows are the Rehearsal's Songs in Song.position order: the Songs linked
    via RehearsalSong for a regular Rehearsal, or the live setlist
    (Rehearsal.dress_rehearsal_songs, ADR-0003) for the Dress Rehearsal,
    which carries no RehearsalSong rows and so no per-row start_time.
    Columns are every Role carrying a SongRoleRequirement *or* a
    SongRoleAssignment on any of those Songs, ordered by name (issue #213)
    — a Requirement is a target, never a cap, so an Assignment with no
    Requirement is a legal column with no target, not a hidden one. Each
    cell lists an AssignmentMatrixEntry per SongRoleAssignment for that
    (Song, Role) pair, ordered by person name, each carrying
    is_role_mismatch (issue #208), plus one per Backup anchored on that
    Song's RehearsalSong at this Rehearsal (issue #216) — the Dress
    Rehearsal has no RehearsalSong rows to anchor a Backup on (ADR-0006),
    so it never carries any, structurally rather than by a filter here.
    """
    songs, start_times, rehearsal_song_ids = _matrix_songs(rehearsal)
    roles = list(
        Role.objects.filter(
            Q(songrolerequirement__song__in=songs) | Q(songroleassignment__song__in=songs),
        ).distinct().order_by('name')
    )
    entries_by_song_role = _matrix_entries_by_song_role(songs, roles, rehearsal_song_ids)
    rows = [
        AssignmentMatrixRow(
            song=song,
            start_time=start_times.get(song.id),
            rehearsal_song_id=rehearsal_song_ids.get(song.id),
            cells=[
                AssignmentMatrixCell(
                    role=role,
                    entries=(entries := entries_by_song_role.get((song.id, role.id), [])),
                    standing_assignees=[
                        entry.person for entry in entries if entry.kind == AssignmentMatrixEntryKind.ASSIGNMENT
                    ],
                )
                for role in roles
            ],
        )
        for song in songs
    ]
    return AssignmentMatrix(roles=roles, rows=rows)


def _matrix_songs(rehearsal):
    """Return (Songs in Song.position order, {song_id: start_time}, {song_id: RehearsalSong.pk}) for `rehearsal`.

    The Dress Rehearsal (is_full_setlist=True) has no RehearsalSong rows by
    design (ADR-0003), so its Songs come from the live setlist instead and
    the start_time and RehearsalSong-id maps are both empty — which is
    exactly what keeps a Backup unanchorable there (ADR-0006, issue #216).
    """
    if rehearsal.is_full_setlist:
        return list(rehearsal.dress_rehearsal_songs), {}, {}
    rehearsal_songs = list(RehearsalSong.objects.filter(rehearsal=rehearsal))
    start_times = {rehearsal_song.song_id: rehearsal_song.start_time for rehearsal_song in rehearsal_songs}
    rehearsal_song_ids = {rehearsal_song.song_id: rehearsal_song.pk for rehearsal_song in rehearsal_songs}
    songs = list(Song.objects.filter(pk__in=start_times.keys()).order_by('position'))
    return songs, start_times, rehearsal_song_ids


def addable_roles_for(matrix: AssignmentMatrix) -> list[Role]:
    """Return active Roles not already a column in `matrix`, ordered by name (issue #213).

    Backs "+ Add role" on /schedule/'s assignment grid: a client-side-only
    column add that writes no SongRoleRequirement. Bounded to active Roles
    the same way RosterAddRoleView's declared-Role choices are, and
    excludes anything already a column since re-offering it would be a
    no-op the admin can't tell apart from a fresh addable Role.
    """
    existing_role_ids = {role.pk for role in matrix.roles}
    return list(Role.objects.filter(is_active=True).exclude(pk__in=existing_role_ids).order_by('name'))


def _matrix_entries_by_song_role(songs, roles, rehearsal_song_ids):
    """Return {(song_id, role_id): [AssignmentMatrixEntry, ...]} for every assignment/Backup among `songs`/`roles` (issue #208, #216).

    Assignments are ordered by person name first; Backups (looked up via
    `rehearsal_song_ids`, empty on the Dress Rehearsal) are appended after,
    also ordered by person name, so a cell's standing assignees always
    lead its Backups.
    """
    assignments = SongRoleAssignment.objects.filter(
        song__in=songs, role__in=roles,
    ).select_related('person', 'role').order_by('person__name')
    result = {}
    for assignment in assignments:
        entry = AssignmentMatrixEntry(
            id=assignment.pk,
            kind=AssignmentMatrixEntryKind.ASSIGNMENT,
            person=assignment.person,
            is_role_mismatch=assignment.is_role_mismatch,
        )
        result.setdefault((assignment.song_id, assignment.role_id), []).append(entry)

    if rehearsal_song_ids:
        song_id_by_rehearsal_song_id = {
            rehearsal_song_id: song_id for song_id, rehearsal_song_id in rehearsal_song_ids.items()
        }
        backups = Backup.objects.filter(
            rehearsal_song_id__in=rehearsal_song_ids.values(), role__in=roles,
        ).select_related('person', 'role', 'covering_for').order_by('person__name')
        for backup in backups:
            song_id = song_id_by_rehearsal_song_id.get(backup.rehearsal_song_id)
            entry = AssignmentMatrixEntry(
                id=backup.pk,
                kind=AssignmentMatrixEntryKind.BACKUP,
                person=backup.person,
                is_role_mismatch=backup.is_role_mismatch,
                covering_for=backup.covering_for,
            )
            result.setdefault((song_id, backup.role_id), []).append(entry)
    return result


@dataclass(frozen=True)
class AssignmentPickerOption:
    """One selectable row in the cell picker (issue #211): a rostered Person plus whether they declared the cell's Role."""

    person: Person
    has_declared_role: bool


@dataclass(frozen=True)
class AssignmentPickerResult:
    """The picker's contents for one (Song, Role) cell (issues #211, #216): who can be picked, split by section then declared-Role order.

    `declared`/`others` are the "Assigned (every rehearsal + concert)"
    section: `declared` lists Role-declaring Members first (ADR-0009's
    picker plan), `others` holds every other rostered Member, meant to
    sit behind a "Show all members" disclosure per ADR-0002 — picking one
    is allowed with no confirmation, since the resulting mismatch flag is
    the existing soft signal, not a block. Both exclude anyone already
    assigned to this exact (Song, Role): re-offering them would only
    invite a duplicate the unique constraint would reject.

    `backup_declared`/`backup_others` are the same split for the "Backup
    (this rehearsal only)" section — always empty when
    `rehearsal_song_id` is None, which is the Dress Rehearsal's case
    (ADR-0006): it carries no RehearsalSong to anchor a Backup on, so the
    section renders structural copy instead of a picker (issue #216).
    """

    song: Song
    role: Role
    declared: list[AssignmentPickerOption]
    others: list[AssignmentPickerOption]
    backup_declared: list[AssignmentPickerOption]
    backup_others: list[AssignmentPickerOption]
    rehearsal_song_id: int | None


def assignment_picker_for(song, role, semester, *, rehearsal_song=None) -> AssignmentPickerResult:
    """Build the "+" picker's contents for `song`/`role`, scoped to `semester`'s roster (issues #211, #216).

    Population is deliberately narrow: only People with a Membership in
    `semester` are offered, because an assignment (or a Backup) presupposes
    membership (rostering rules purge a removed Member's assignments) — a
    non-rostered Person would create a row that would then be deleted.
    Ordering is Person name within each declared/others group.

    `rehearsal_song` scopes the Backup section: pass the Rehearsal's
    RehearsalSong for `song` to populate it, or None (the Dress
    Rehearsal's case, ADR-0006) to leave both Backup lists empty and let
    the template render the structural explanation instead.
    """
    already_assigned_ids = frozenset(
        SongRoleAssignment.objects.filter(song=song, role=role).values_list('person_id', flat=True)
    )
    declared_person_ids = frozenset(
        MembershipRole.objects.filter(
            membership__semester=semester, role=role,
        ).values_list('membership__person_id', flat=True)
    )
    people = Person.objects.filter(
        membership__semester=semester,
    ).exclude(pk__in=already_assigned_ids).order_by('name')

    declared, others = [], []
    for person in people:
        option = AssignmentPickerOption(person=person, has_declared_role=person.pk in declared_person_ids)
        (declared if option.has_declared_role else others).append(option)

    backup_declared, backup_others = [], []
    if rehearsal_song is not None:
        already_backed_up_ids = frozenset(
            Backup.objects.filter(rehearsal_song=rehearsal_song, role=role).values_list('person_id', flat=True)
        )
        backup_people = Person.objects.filter(
            membership__semester=semester,
        ).exclude(pk__in=already_backed_up_ids).order_by('name')
        for person in backup_people:
            option = AssignmentPickerOption(person=person, has_declared_role=person.pk in declared_person_ids)
            (backup_declared if option.has_declared_role else backup_others).append(option)

    return AssignmentPickerResult(
        song=song,
        role=role,
        declared=declared,
        others=others,
        backup_declared=backup_declared,
        backup_others=backup_others,
        rehearsal_song_id=rehearsal_song.pk if rehearsal_song is not None else None,
    )


def assignment_grid_is_editable(rehearsal) -> bool:
    """Return whether an admin gets an "Edit assignments" control on `rehearsal`'s assignment grid (issue #210).

    A usability rule, not a data-integrity one (ADR-0009): every
    SongRoleAssignment row reachable through a past-dated Rehearsal's grid
    is exactly as writable in the database as any other, and removing one
    still reaches every Rehearsal and the concert semester-wide regardless
    of which grid the admin removed it from. The rule exists only because a
    grid captioned with a stale date is a misleading place to change a live
    concert lineup — unlike the rehearsal editor's own past-date lock,
    which *is* about integrity. A same-day Rehearsal stays editable all day
    (whole days, not instants, so a last-minute reassignment during
    tonight's rehearsal is possible). The Dress Rehearsal is always
    editable: its rows are the live setlist (ADR-0003) and it is the
    Semester's last-dated Rehearsal, so it is the backstop that keeps a
    late Semester editable once every other Rehearsal has passed.
    """
    return rehearsal.is_full_setlist or rehearsal.date >= timezone.localdate()


class StaleAssignmentSemesterError(ValueError):
    """Raised when an assignment edit Buffer's Semester changed since the Buffer was loaded (issue #210)."""


@dataclass(frozen=True)
class AssignmentEditBuffer:
    """The Pending Buffer `apply_song_role_assignments()` commits in one transaction (issues #210, #211, #216).

    `removed_assignment_ids` names every SongRoleAssignment row to delete,
    wherever on the grid its chip's ✕ was clicked. `added_entries` names
    every (song_id, role_id, person_id) a "+" picker pick added from the
    "Assigned" section, wherever on the grid it was picked from.

    `removed_backup_ids` and `added_backup_entries` are the Backup
    equivalents (issue #216): a Backup add is a
    (rehearsal_song_id, role_id, person_id, covering_for_id) tuple, where
    `covering_for_id` is None when the admin left "covering for" empty
    (ADR-0007: recording it is a choice, never a demand).
    `backup_covering_for_updates` is a set of (backup_id, covering_for_id)
    pairs — every already-persisted Backup chip's "covering for" select
    resubmits its current value on every save, whether the admin changed
    it or not, so this always names every visible Backup chip's pick.

    `semester_id` and `semester_updated_at` back the same two staleness
    checks `RosterEditBuffer` uses — `semester_id` against the caller's
    session-scoped viewing Semester, `semester_updated_at` against the
    Semester row's current stamp.
    """

    semester_id: int
    semester_updated_at: datetime
    removed_assignment_ids: frozenset[int]
    added_entries: frozenset[tuple[int, int, int]] = frozenset()
    removed_backup_ids: frozenset[int] = frozenset()
    added_backup_entries: frozenset[tuple[int, int, int, int | None]] = frozenset()
    backup_covering_for_updates: frozenset[tuple[int, int | None]] = frozenset()


def apply_song_role_assignments(
    buffer: AssignmentEditBuffer, *, viewing_semester: Semester, rehearsal=None,
) -> None:
    """Apply a Buffer of SongRoleAssignment and Backup removals and adds in one transaction (issues #210, #211, #216, ADR-0009).

    The SongRoleAssignment half is semester-wide: SongRoleAssignment is
    (song, role, person) with no rehearsal FK, so a removal or an add
    here changes that Person's assignment to that Song at every Rehearsal
    and at the concert, not only the Rehearsal whose grid the admin was
    viewing. The Backup half is anchored on a RehearsalSong instead
    (ADR-0007), so it only ever touches the one Rehearsal it was added
    from — every Backup query below is scoped to `rehearsal`, not merely
    to `viewing_semester`, so a hand-crafted POST naming a RehearsalSong
    or Backup id from a *different* Rehearsal in the same Semester (one
    the admin wasn't looking at, possibly a past, non-editable one) can't
    touch anything. `rehearsal` is required whenever `buffer` carries any
    Backup field; the standing-assignment-only tests predating issue #216
    pass no Backup entries and so can omit it. Takes no Semester row
    lock — nothing here renumbers Song positions or RehearsalSong order,
    so there is no ordering constraint to serialize against. Registers no
    `transaction.on_commit()` call — nothing here reaches outside the
    Semester (no mail, no object storage).

    An added assignment entry is silently skipped if its Song isn't one
    of `viewing_semester`'s (a hand-crafted POST naming another
    Semester's Song), or if its Person holds no Membership in
    `viewing_semester` (the picker never offers a non-rostered Person,
    per issue #211, but a tampered POST could still try). `get_or_create`
    makes a duplicate add a no-op rather than an IntegrityError against
    `unique_song_role_person` — the picker already excludes anyone
    already assigned to the cell, but two concurrent saves could still
    race here. `SongRoleAssignment.save()` recomputes `is_role_mismatch`
    on create (ADR-0002): picking a Person who hasn't declared the Role
    is allowed, not blocked.

    An added Backup entry is likewise skipped if its RehearsalSong isn't
    one of `rehearsal`'s — which, since the Dress Rehearsal carries no
    RehearsalSong row at all (ADR-0006), is exactly what makes a Backup
    against it impossible by this route, structurally rather than by an
    explicit check — or if its Person holds no Membership in
    `viewing_semester`. A `covering_for_id` naming the Backup's own
    Person (which `backup_person_is_not_covering_for_self` would
    otherwise reject), or anyone who isn't a standing SongRoleAssignment
    on that same (Song, Role) cell — the only people the "covering for"
    <select> ever offers — is silently dropped to None rather than
    failing the whole save: recording who is covered is advisory
    (ADR-0007), never worth losing the Backup itself over. `get_or_create`
    makes a duplicate add a no-op against
    `unique_backup_per_slot_role_person`, matching the assignment side.

    A `backup_covering_for_updates` pair naming a Backup outside
    `rehearsal`, or one this call already deleted (via
    `removed_backup_ids`), is silently skipped rather than resurrecting
    or misattributing anything; one naming a still-live Backup within
    `rehearsal` applies the same self/standing-assignee guard as an added
    entry's `covering_for_id`.

    Raises `WrongViewingSemesterError` if `buffer.semester_id` doesn't
    match `viewing_semester`, checked before any transaction opens. Raises
    `StaleAssignmentSemesterError` inside the transaction if the Semester's
    `updated_at` no longer matches `buffer.semester_updated_at`, rolling
    back whatever this call had already applied.
    """
    if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
        raise WrongViewingSemesterError(
            "This assignment edit Buffer's Semester doesn't match the Semester you're currently viewing."
        )

    with transaction.atomic():
        semester = Semester.objects.get(pk=buffer.semester_id)
        if semester.updated_at != buffer.semester_updated_at:
            raise StaleAssignmentSemesterError('The assignments changed while you were editing — reload and reapply.')

        rostered_person_ids = frozenset(
            Membership.objects.filter(semester=semester).values_list('person_id', flat=True)
        )

        SongRoleAssignment.objects.filter(
            pk__in=buffer.removed_assignment_ids, song__semester=semester,
        ).delete()

        if buffer.added_entries:
            valid_song_ids = frozenset(
                Song.objects.filter(
                    semester=semester, pk__in={song_id for song_id, _, _ in buffer.added_entries},
                ).values_list('pk', flat=True)
            )
            for song_id, role_id, person_id in buffer.added_entries:
                if song_id not in valid_song_ids or person_id not in rostered_person_ids:
                    continue
                SongRoleAssignment.objects.get_or_create(song_id=song_id, role_id=role_id, person_id=person_id)

        Backup.objects.filter(
            pk__in=buffer.removed_backup_ids, rehearsal_song__rehearsal=rehearsal,
        ).delete()

        # A covering_for pick is only ever valid against a standing SongRoleAssignment on the
        # same (Song, Role) cell -- the only people the "covering for" <select> offers -- so both
        # the add and the update path below check membership in this one set (issue #216 review).
        standing_assignee_cells = frozenset(
            SongRoleAssignment.objects.filter(song__semester=semester).values_list('song_id', 'role_id', 'person_id')
        )

        if buffer.added_backup_entries:
            song_id_by_rehearsal_song_id = dict(
                RehearsalSong.objects.filter(
                    rehearsal=rehearsal,
                    pk__in={rehearsal_song_id for rehearsal_song_id, _, _, _ in buffer.added_backup_entries},
                ).values_list('pk', 'song_id')
            )
            for rehearsal_song_id, role_id, person_id, covering_for_id in buffer.added_backup_entries:
                song_id = song_id_by_rehearsal_song_id.get(rehearsal_song_id)
                if song_id is None or person_id not in rostered_person_ids:
                    continue
                if covering_for_id == person_id or (song_id, role_id, covering_for_id) not in standing_assignee_cells:
                    covering_for_id = None
                Backup.objects.get_or_create(
                    rehearsal_song_id=rehearsal_song_id,
                    role_id=role_id,
                    person_id=person_id,
                    defaults={'covering_for_id': covering_for_id},
                )

        for backup_id, covering_for_id in buffer.backup_covering_for_updates:
            try:
                backup = Backup.objects.select_related('rehearsal_song').get(
                    pk=backup_id, rehearsal_song__rehearsal=rehearsal,
                )
            except Backup.DoesNotExist:
                continue
            song_id = backup.rehearsal_song.song_id
            if covering_for_id == backup.person_id or (song_id, backup.role_id, covering_for_id) not in standing_assignee_cells:
                covering_for_id = None
            if backup.covering_for_id != covering_for_id:
                backup.covering_for_id = covering_for_id
                backup.save(update_fields=['covering_for_id'])

        semester.updated_at = timezone.now()
        semester.save(update_fields=['updated_at'])


@dataclass(frozen=True)
class AssignmentEditFallout:
    """Every observable consequence of a candidate SongRoleAssignment edit Buffer for one Rehearsal (issue #212, ADR 0008).

    `is_blocked` mirrors `apply_song_role_assignments()`'s two checks
    (wrong Semester, stale stamp) with no Fallout computed at all -- a
    Validation Error in ADR 0008's terms, never blended with Fallout.
    `loud`/`quiet` are the two ADR-0002/issue #185-worded tiers, computed
    against the Rehearsal's current (post-apply) assignment state rather
    than a before/after diff: loud is the warning ADR-0009 built this
    per-Rehearsal surface to raise (an assigned Person who can't be there
    that evening), and quiet is a standing signal resolved elsewhere (an
    unfilled Role Requirement, a role mismatch) -- neither ever blocks a
    save. `is_stale` flags a `Semester.updated_at` mismatch, reported never
    refused, per ADR 0008. Never reads `Conflict.status`.
    """

    is_blocked: bool
    block_message: str
    is_stale: bool
    loud: list[str]
    quiet: list[str]


def _blocked_assignment_fallout(block_message: str, *, is_stale: bool = False) -> AssignmentEditFallout:
    """Return an AssignmentEditFallout reporting a hard block, with no Fallout lines computed at all."""
    return AssignmentEditFallout(is_blocked=True, block_message=block_message, is_stale=is_stale, loud=[], quiet=[])


def _assignment_fallout_lines(rehearsal, songs):
    """Return (loud, quiet) Fallout lines for `rehearsal`'s current (post-apply) assignments and Backups over `songs` (issue #212).

    Loud: an assigned Person (standing or Backup, issue #216) with a full
    Conflict for `rehearsal` (moot for the Dress Rehearsal, which no
    Conflict can point at per ADR-0006), or a partial Conflict whose
    Window overlaps the Song's RehearsalSong slot -- only computable
    through a Rehearsal, which is ADR-0009's whole reason this surface
    exists. A Backup shares its standing counterpart's slot, so a Person
    holding both is warned only once. Quiet: an unfilled Role Requirement,
    or a role mismatch -- both standing flags resolved elsewhere
    (ADR-0002), kept quiet so they don't train an admin to ignore the loud
    tier. Reads `Conflict.type` to tell full from partial, never
    `Conflict.status`.
    """
    song_ids = [song.pk for song in songs]
    assignments = list(
        SongRoleAssignment.objects.filter(song_id__in=song_ids)
        .select_related('person', 'role', 'song')
        .order_by('song__position', 'role__name', 'person__name')
    )
    backups = list(
        Backup.objects.filter(rehearsal_song__rehearsal=rehearsal, rehearsal_song__song_id__in=song_ids)
        .select_related('person', 'role', 'rehearsal_song__song')
        .order_by('rehearsal_song__song__position', 'role__name', 'person__name')
    )
    person_ids = {assignment.person_id for assignment in assignments} | {backup.person_id for backup in backups}

    full_conflict_person_ids = frozenset(
        Conflict.objects.filter(
            rehearsal=rehearsal, type=Conflict.FULL_CONFLICT, person_id__in=person_ids,
        ).values_list('person_id', flat=True)
    )
    partial_conflicts = Conflict.objects.filter(
        rehearsal=rehearsal, type=Conflict.PARTIAL, person_id__in=person_ids,
    ).prefetch_related('conflictwindow_set')
    windows_by_person_id = {
        conflict.person_id: [
            (window.unavailable_start, window.unavailable_end) for window in conflict.conflictwindow_set.all()
        ]
        for conflict in partial_conflicts
    }
    slot_by_song_id = {
        rehearsal_song.song_id: (rehearsal_song.start_time, rehearsal_song.end_time)
        for rehearsal_song in RehearsalSong.objects.filter(rehearsal=rehearsal, song_id__in=song_ids)
    }

    def _conflict_line(person_id, person_name, song_id, song_title, *, is_backup):
        role_word = 'a Backup for' if is_backup else 'assigned to'
        if person_id in full_conflict_person_ids:
            return f'{person_name} is {role_word} {song_title} but has a full Conflict for this Rehearsal.'
        windows = windows_by_person_id.get(person_id)
        slot = slot_by_song_id.get(song_id)
        if windows and slot is not None and any(
            _windows_overlap(window_start, window_end, slot[0], slot[1]) for window_start, window_end in windows
        ):
            return (
                f'{person_name} is {role_word} {song_title}, but a declared Conflict Window overlaps its '
                'rehearsal slot.'
            )
        return None

    loud = []
    warned_person_song_pairs = set()
    for assignment in assignments:
        line = _conflict_line(
            assignment.person_id, assignment.person.name, assignment.song_id, assignment.song.title, is_backup=False,
        )
        if line is not None:
            loud.append(line)
            warned_person_song_pairs.add((assignment.person_id, assignment.song_id))
    for backup in backups:
        song = backup.rehearsal_song.song
        if (backup.person_id, song.id) in warned_person_song_pairs:
            continue
        line = _conflict_line(backup.person_id, backup.person.name, song.id, song.title, is_backup=True)
        if line is not None:
            loud.append(line)
            warned_person_song_pairs.add((backup.person_id, song.id))

    quiet = []
    for song in songs:
        for status in fill_status_for(song):
            if status.is_understaffed:
                quiet.append(
                    f"{song.title}'s {status.role.name} Requirement is unfilled ({status.actual}/{status.target})."
                )
    for assignment in assignments:
        if assignment.is_role_mismatch:
            quiet.append(
                f"{assignment.person.name}'s {assignment.role.name} assignment on {assignment.song.title} "
                "doesn't match their declared Roles."
            )

    return loud, quiet


def preview_song_role_assignments(buffer: AssignmentEditBuffer, *, rehearsal, viewing_semester: Semester) -> AssignmentEditFallout:
    """Run the real `apply_song_role_assignments()` for `buffer` and report `rehearsal`'s Fallout, without committing it.

    ADR 0008/issue #212: this function's write is real -- it must be called
    inside a transaction the *caller* rolls back (`PreviewMixin` does this
    for the Preview view; tests must wrap the call the same way). Called
    outside such a transaction, this function corrupts the database.

    Mirrors `apply_song_role_assignments()`'s wrong-Semester check so a
    Preview can never disagree with what Save would reject. The Semester's
    current `updated_at` is swapped in before the real call runs (mirroring
    `preview_roster_edits()`), so the write actually applies regardless of
    whether the submitted Buffer's own stamp is stale; `is_stale` is
    reported separately, from the *original* stamp, exactly like the Save
    endpoint's own staleness check would see it.
    """
    if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
        return _blocked_assignment_fallout(
            "This assignment edit Buffer's Semester doesn't match the Semester you're currently viewing."
        )

    current_semester = Semester.objects.get(pk=viewing_semester.pk)
    is_stale = buffer.semester_updated_at != current_semester.updated_at

    apply_buffer = replace(buffer, semester_updated_at=current_semester.updated_at)
    try:
        apply_song_role_assignments(apply_buffer, viewing_semester=viewing_semester, rehearsal=rehearsal)
    except (WrongViewingSemesterError, StaleAssignmentSemesterError) as error:
        return _blocked_assignment_fallout(str(error), is_stale=is_stale)

    songs, _, _ = _matrix_songs(rehearsal)
    loud, quiet = _assignment_fallout_lines(rehearsal, songs)
    return AssignmentEditFallout(is_blocked=False, block_message='', is_stale=is_stale, loud=loud, quiet=quiet)


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
    attendance_for reports full-window attendance (needed at both ends).
    The Dress Rehearsal (ADR-0003, no persisted RehearsalSong rows) always
    returns that full window for every Person, assigned or not: attendance
    there is mandatory (ADR-0006), and there's no per-song clock time to
    derive a narrower window from anyway.
    """
    if rehearsal.is_full_setlist:
        return _dress_rehearsal_attendance_suggestion(rehearsal, person)
    return _regular_rehearsal_attendance_suggestion(rehearsal, person)


def _dress_rehearsal_attendance_suggestion(rehearsal, person):
    """Return the Dress Rehearsal's own start/end as every `person`'s suggestion (ADR-0006, issue #149).

    Never None: attendance at the Dress Rehearsal is mandatory, so a Person
    holding no Role Assignment on any setlist Song is expected for the whole
    window just the same as an assigned one — `person` is unused for that
    reason. The window is the Rehearsal's own start_time/end_time, which
    already carry the Semester's setup/teardown grace (Rehearsal.save()
    derives end_time from them), with no arrival/departure buffer applied,
    matching the full-window fallback in
    _regular_rehearsal_attendance_suggestion.
    """
    return AttendanceSuggestion(arrival_time=rehearsal.start_time, departure_time=rehearsal.end_time)


def _regular_rehearsal_attendance_suggestion(rehearsal, person):
    """Return `person`'s suggestion for a non-Dress Rehearsal, derived from the slots they are on."""
    bounds = slots_for_person(rehearsal, person).aggregate(
        earliest_start=models.Min('start_time'), latest_end=models.Max('end_time'),
    )
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
    assigned_slots = list(slots_for_person(rehearsal, person).order_by('order'))
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
CONFLICT_TYPE_LABELS = {
    CONFLICT_FULL_ABSENCE: 'Full absence',
    CONFLICT_LATE_ARRIVAL: 'Late arrival',
    CONFLICT_EARLY_DEPARTURE: 'Early departure',
    None: 'Partial (custom)',
}


def future_rehearsals_for(semester) -> list[Rehearsal]:
    """Return `semester`'s declarable Rehearsals dated today or later, in date order (issue #98's Upcoming Rehearsals list).

    The Dress Rehearsal is excluded: attendance there is mandatory, so
    there is nothing to declare against it (ADR-0006). The Conflicts page
    says so in place of the missing row, rather than letting it silently
    vanish.
    """
    today = timezone.localdate()
    return list(
        Rehearsal.objects.filter(
            semester=semester, date__gte=today, is_full_setlist=False,
        ).order_by('date', 'start_time'),
    )


@dataclass(frozen=True)
class ConflictAdjudicationRow:
    """One row of the admin adjudication index: a Rehearsal plus its pending Conflict count (issue #191)."""

    rehearsal: Rehearsal
    pending_count: int


def conflict_adjudication_index_for(semester) -> list[ConflictAdjudicationRow]:
    """Return `semester`'s adjudicatable Rehearsals with each one's pending Conflict count, in date order (issue #191).

    Shares future_rehearsals_for()'s future/non-Dress filter — the Dress
    Rehearsal can hold no Conflict (ADR-0006), and a past Rehearsal's
    pending count is not a work queue that ever empties (CONTEXT.md's
    Adjudication entry) — but is its own function rather than an
    extension of that one: future_rehearsals_for() also backs
    member-facing declaration paths that have no business carrying a
    Conflict-derived count. A Rehearsal with zero Conflicts still gets a
    row, so an admin can confirm there is nothing to do rather than infer
    it from an absence.
    """
    rehearsals = future_rehearsals_for(semester)
    pending_counts = dict(
        Conflict.objects.filter(rehearsal__in=rehearsals, status=Conflict.PENDING)
        .values('rehearsal_id')
        .annotate(count=Count('id'))
        .values_list('rehearsal_id', 'count'),
    )
    return [
        ConflictAdjudicationRow(rehearsal=rehearsal, pending_count=pending_counts.get(rehearsal.pk, 0))
        for rehearsal in rehearsals
    ]


def pending_conflict_count_for(semester) -> int:
    """Return `semester`'s total pending-Conflict count across every adjudicatable Rehearsal (issue #326).

    The ambient count the `/api/` envelope's `context.pending_conflict_count`
    carries for an admin — its one consumer is the admin Conflicts index
    (issue #340); #328 must not render it on the Conflicts nav item, which
    #311 removed deliberately. Shares `conflict_adjudication_index_for()`'s
    future/non-Dress Rehearsal scope (ADR 0006), summed rather than broken
    out per Rehearsal.
    """
    rehearsals = future_rehearsals_for(semester)
    return Conflict.objects.filter(rehearsal__in=rehearsals, status=Conflict.PENDING).count()


@dataclass(frozen=True)
class ConflictAdjudicationDetailRow:
    """One row of a Rehearsal's adjudication table: a Conflict with its display fields pre-derived (issue #192)."""

    conflict: Conflict
    person: Person
    type_label: str
    declared_time: time | None
    reason: str
    status: str


def conflict_adjudication_rows_for(rehearsal) -> list[ConflictAdjudicationDetailRow]:
    """Return every Conflict declared against `rehearsal`, each with its display fields pre-derived (issue #192).

    Ordered by person name for a stable, readable table. Shares
    `_derive_declaration()` with `conflict_history_for()` rather than
    re-deriving the type label/declared-time mapping a second time.
    """
    conflicts = Conflict.objects.filter(
        rehearsal=rehearsal,
    ).select_related('person').prefetch_related('conflictwindow_set').order_by('person__name')
    rows = []
    for conflict in conflicts:
        declaration_type, declared_time = _derive_declaration(conflict)
        rows.append(ConflictAdjudicationDetailRow(
            conflict=conflict,
            person=conflict.person,
            type_label=CONFLICT_TYPE_LABELS[declaration_type],
            declared_time=declared_time,
            reason=conflict.reason,
            status=conflict.status,
        ))
    return rows


class WrongAdjudicationSemesterError(ValueError):
    """Raised when an Adjudication Buffer's Semester id doesn't match the session-scoped viewing Semester (issue #192)."""


class StaleAdjudicationSemesterError(ValueError):
    """Raised when an Adjudication Buffer's Semester changed since the Buffer was loaded (issue #192)."""


class UnknownConflictError(ValueError):
    """Raised when an Adjudication Buffer names a Conflict id that doesn't belong to its target Rehearsal (issue #192)."""


@dataclass(frozen=True)
class AdjudicationEntry:
    """One Conflict's target verdict and note in an Adjudication Buffer (issue #192)."""

    conflict_id: int
    status: str
    note: str


@dataclass(frozen=True)
class AdjudicationBuffer:
    """The whole diff `apply_adjudications()` commits in one transaction, for one Rehearsal (issue #192).

    `semester_id` and `semester_updated_at` back the two staleness checks,
    the same shape `RosterEditBuffer` uses: `semester_id` is cross-checked
    against the caller's session-scoped viewing Semester, and
    `semester_updated_at` against the Semester row's current stamp.
    `rehearsal_id` scopes `entries` — every entry's `conflict_id` must
    belong to this Rehearsal, or the whole save is rejected.
    """

    rehearsal_id: int
    semester_id: int
    semester_updated_at: datetime
    entries: list[AdjudicationEntry]


def apply_adjudications(buffer: AdjudicationBuffer, *, viewing_semester: Semester) -> None:
    """Apply a whole Rehearsal's Conflict adjudications — every status and note — in one transaction (issue #192).

    Approving or rejecting changes nothing but `status`/`adjudication_note`
    on the named Conflicts: no `RehearsalSong.order`, `SongRoleAssignment`
    or Backup is touched, since the model holds no link from a Conflict to
    the accommodation (if any) an admin makes for it elsewhere (#131,
    #134). Takes no Semester row lock — like `apply_roster_edits()`, this
    renumbers no positions, so there is no unique-position constraint to
    serialise against; the stamp is the guard.

    Raises `WrongAdjudicationSemesterError` if `buffer.semester_id` doesn't
    match `viewing_semester`, or `UnknownConflictError` if any
    `buffer.entries` names a Conflict not belonging to
    `buffer.rehearsal_id` — both checked, and both writing nothing, before
    any transaction opens. Raises `StaleAdjudicationSemesterError` inside
    the transaction if the Semester's `updated_at` no longer matches
    `buffer.semester_updated_at`, rolling back whatever this call had
    already applied. Makes no external call, so nothing here needs
    `transaction.on_commit()`.
    """
    if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
        raise WrongAdjudicationSemesterError(
            "This adjudication Buffer's Semester doesn't match the Semester you're currently viewing."
        )
    conflict_ids = {entry.conflict_id for entry in buffer.entries}
    valid_ids = set(
        Conflict.objects.filter(pk__in=conflict_ids, rehearsal_id=buffer.rehearsal_id).values_list('pk', flat=True),
    )
    if conflict_ids - valid_ids:
        raise UnknownConflictError(
            "This adjudication Buffer names a Conflict that doesn't belong to this Rehearsal."
        )

    with transaction.atomic():
        semester = Semester.objects.get(pk=buffer.semester_id)
        if semester.updated_at != buffer.semester_updated_at:
            raise StaleAdjudicationSemesterError(
                'The schedule changed while you were deciding — reload and reapply.'
            )
        for entry in buffer.entries:
            Conflict.objects.filter(pk=entry.conflict_id).update(
                status=entry.status, adjudication_note=entry.note,
            )
        semester.updated_at = timezone.now()
        semester.save(update_fields=['updated_at'])


FEASIBLE = 'feasible'
INFEASIBLE = 'infeasible'
NOT_APPLICABLE = 'not_applicable'

FEASIBILITY_ROW_CEILING = 8
"""Ceiling on RehearsalSong rows conflict_feasibility_for() will exhaustively search (issue #194).

8! is already 40,320 orderings and a real Rehearsal holds a handful of
songs, so this is generous headroom rather than a tight limit. Beyond it
the search is not attempted at all -- see ConflictFeasibilityRow.checked.
"""


@dataclass(frozen=True)
class ConflictFeasibilityRow:
    """One Conflict's feasibility verdict and standing-overlap advisory, from `conflict_feasibility_for()` (issue #194).

    `checked` is False only when the search was never attempted because
    the Rehearsal's RehearsalSong count exceeds FEASIBILITY_ROW_CEILING;
    `verdict` is then None, meant to render as "not checked" -- never as
    feasible or infeasible. When `checked` is True, `verdict` is one of
    FEASIBLE/INFEASIBLE/NOT_APPLICABLE: a full Conflict is always
    NOT_APPLICABLE (no search needed, the person just isn't there), and a
    partial Conflict held by someone with no assigned Songs that evening
    is always FEASIBLE (also no search needed, there's nothing to place).
    `has_standing_overlap` is only ever True for a Conflict id passed in
    `approved_conflict_ids` -- a pending or rejected Conflict never
    carries the advisory, since it isn't part of the band's real state.
    `overlap_song_id`/`overlap_role_id` name the first assigned (Song,
    Role) cell the overlap was found at -- the target for the adjudication
    row's doors to the Running Order and the assignment grid (issue #195)
    -- and are None exactly when `has_standing_overlap` is False.
    """

    conflict_id: int
    checked: bool
    verdict: str | None
    has_standing_overlap: bool
    overlap_song_id: int | None
    overlap_role_id: int | None


def _windows_overlap(window_start, window_end, slot_start, slot_end) -> bool:
    """True when a [window_start, window_end) unavailable range intersects a [slot_start, slot_end) slot.

    Shared by conflict_feasibility_for()'s candidate-ordering search and its
    standing-overlap advisory (issue #194), so the two can never disagree
    about what "overlap" means. Touching endpoints don't count as overlap.
    """
    return window_start < slot_end and slot_start < window_end


def _slot_duration_for(rehearsal):
    """Return one song-slot's length for `rehearsal`, mirroring RehearsalSong._slot_duration()'s formula.

    Recomputed here rather than reused from a saved RehearsalSong instance
    because conflict_feasibility_for()'s search evaluates hypothetical
    orderings that are never persisted (issue #194).
    """
    start = datetime.combine(rehearsal.date, rehearsal.start_time)
    end = datetime.combine(rehearsal.date, rehearsal.end_time)
    return (end - start) / rehearsal.semester.default_song_slot_count


def _person_avoids_windows(windows, song_ids, times_by_song_id) -> bool:
    """True if none of `song_ids`' computed (start, end) slots in `times_by_song_id` overlap any of `windows`."""
    for song_id in song_ids:
        slot = times_by_song_id.get(song_id)
        if slot is None:
            continue
        if any(_windows_overlap(window_start, window_end, slot[0], slot[1]) for window_start, window_end in windows):
            return False
    return True


def _search_feasible(active_constraints, rehearsal_songs, rehearsal) -> bool:
    """Exhaustively search orderings of `rehearsal_songs` for one where every (windows, song_ids) constraint holds.

    This is the seam a real optimiser would replace (issue #194): a
    Rehearsal's RehearsalSong rows can carry different slot_counts, so a
    slot's start/end depends on every row that precedes it in the
    ordering -- slot boundaries are not fixed columns, so bipartite
    matching of songs to slots would only be exact when every row shares
    the same slot_count. Enumerating full orderings sidesteps that
    entirely and is exact for the handful of songs a real Rehearsal holds.
    """
    slot_duration = _slot_duration_for(rehearsal)
    rehearsal_start = datetime.combine(rehearsal.date, rehearsal.start_time)
    for ordering in permutations(rehearsal_songs):
        times_by_song_id = {}
        elapsed_slots = 0
        for rehearsal_song in ordering:
            start = rehearsal_start + elapsed_slots * slot_duration
            end = start + rehearsal_song.slot_count * slot_duration
            times_by_song_id[rehearsal_song.song_id] = (start.time(), end.time())
            elapsed_slots += rehearsal_song.slot_count
        if all(
            _person_avoids_windows(windows, song_ids, times_by_song_id)
            for windows, song_ids in active_constraints
        ):
            return True
    return False


def _standing_overlap_target(
    conflict, assigned_song_ids, rehearsal_song_by_song_id, role_by_person_and_song, backed_up_slots,
) -> tuple[int, int] | None:
    """Return the first (song_id, role_id) `conflict`'s person is still assigned into their own Window at, or None.

    Computed against each assigned Song's stored RehearsalSong start_time/
    end_time -- never a candidate ordering -- because this describes the
    band's real state (issue #194). Silent once a Backup covers that Role
    on that Song at that Rehearsal (ADR-0007). "First" follows
    `assigned_song_ids`' iteration order, which is fine: the advisory (and
    its doors, issue #195) only ever need one target cell to send an admin
    to, not an exhaustive list.
    """
    windows = [(window.unavailable_start, window.unavailable_end) for window in conflict.conflictwindow_set.all()]
    if not windows:
        return None
    for song_id in assigned_song_ids:
        rehearsal_song = rehearsal_song_by_song_id.get(song_id)
        if rehearsal_song is None:
            continue
        if not any(
            _windows_overlap(window_start, window_end, rehearsal_song.start_time, rehearsal_song.end_time)
            for window_start, window_end in windows
        ):
            continue
        role_id = role_by_person_and_song[(conflict.person_id, song_id)]
        if (rehearsal_song.pk, role_id) not in backed_up_slots:
            return (song_id, role_id)
    return None


def conflict_feasibility_for(rehearsal, approved_conflict_ids) -> list[ConflictFeasibilityRow]:
    """Answer, per Conflict on `rehearsal`, whether some ordering of its Running Order can accommodate it (issue #194).

    A pure read: never proposes or applies an ordering, only whether one
    exists. `approved_conflict_ids` names the joint set of partial
    Conflicts to accommodate together -- the caller's job (typically an
    in-progress Adjudication Buffer, not necessarily what's saved) to
    decide which ids that is. Every row's own id is unioned into that set
    before the check runs, so an approved row reads the real joint
    verdict, and a pending or rejected row reads "if this were approved
    too, given everything already approved" -- the same predicate for
    every row, since the function has no other signal for a row's status.

    A full Conflict's verdict is always NOT_APPLICABLE, no search
    involved. A partial Conflict held by someone with no assigned Songs at
    this Rehearsal is always FEASIBLE, also with no search. Otherwise, if
    the Rehearsal holds more RehearsalSong rows than
    FEASIBILITY_ROW_CEILING, the row comes back unchecked
    (`checked=False`, `verdict=None`) rather than guessing.
    """
    conflicts = list(
        Conflict.objects.filter(rehearsal=rehearsal)
        .select_related('person')
        .prefetch_related('conflictwindow_set')
        .order_by('person__name'),
    )
    approved_ids = frozenset(approved_conflict_ids)
    rehearsal_songs = list(RehearsalSong.objects.filter(rehearsal=rehearsal).select_related('song'))
    song_ids = [rehearsal_song.song_id for rehearsal_song in rehearsal_songs]
    rehearsal_song_by_song_id = {rehearsal_song.song_id: rehearsal_song for rehearsal_song in rehearsal_songs}

    assigned_song_ids_by_person: dict[int, set[int]] = defaultdict(set)
    role_by_person_and_song: dict[tuple[int, int], int] = {}
    for song_id, person_id, role_id in SongRoleAssignment.objects.filter(
        song_id__in=song_ids,
    ).values_list('song_id', 'person_id', 'role_id'):
        assigned_song_ids_by_person[person_id].add(song_id)
        role_by_person_and_song[(person_id, song_id)] = role_id

    backed_up_slots = set(
        Backup.objects.filter(rehearsal_song__in=rehearsal_songs).values_list('rehearsal_song_id', 'role_id'),
    )

    windows_by_conflict_id = {
        conflict.pk: [
            (window.unavailable_start, window.unavailable_end) for window in conflict.conflictwindow_set.all()
        ]
        for conflict in conflicts
        if conflict.type == Conflict.PARTIAL
    }
    person_id_by_conflict_id = {conflict.pk: conflict.person_id for conflict in conflicts}
    fits_ceiling = len(rehearsal_songs) <= FEASIBILITY_ROW_CEILING
    feasibility_cache: dict[frozenset, bool] = {}

    def is_jointly_feasible(conflict_ids):
        active_constraints = [
            (windows_by_conflict_id[conflict_id], assigned_song_ids_by_person.get(person_id_by_conflict_id[conflict_id], set()))
            for conflict_id in conflict_ids
            if conflict_id in windows_by_conflict_id
        ]
        active_constraints = [(windows, songs) for windows, songs in active_constraints if songs]
        if not active_constraints:
            return True
        cache_key = frozenset(conflict_ids)
        if cache_key not in feasibility_cache:
            feasibility_cache[cache_key] = _search_feasible(active_constraints, rehearsal_songs, rehearsal)
        return feasibility_cache[cache_key]

    rows = []
    for conflict in conflicts:
        if conflict.type == Conflict.FULL_CONFLICT:
            rows.append(ConflictFeasibilityRow(
                conflict_id=conflict.pk, checked=True, verdict=NOT_APPLICABLE, has_standing_overlap=False,
                overlap_song_id=None, overlap_role_id=None,
            ))
            continue
        assigned_song_ids = assigned_song_ids_by_person.get(conflict.person_id, set())
        if not assigned_song_ids:
            checked, verdict = True, FEASIBLE
        elif not fits_ceiling:
            checked, verdict = False, None
        else:
            checked = True
            verdict = FEASIBLE if is_jointly_feasible(approved_ids | {conflict.pk}) else INFEASIBLE
        overlap_target = None
        if conflict.pk in approved_ids:
            overlap_target = _standing_overlap_target(
                conflict, assigned_song_ids, rehearsal_song_by_song_id, role_by_person_and_song, backed_up_slots,
            )
        rows.append(ConflictFeasibilityRow(
            conflict_id=conflict.pk, checked=checked, verdict=verdict,
            has_standing_overlap=overlap_target is not None,
            overlap_song_id=overlap_target[0] if overlap_target else None,
            overlap_role_id=overlap_target[1] if overlap_target else None,
        ))
    return rows


@dataclass(frozen=True)
class AdjudicationFallout:
    """Every observable consequence of a candidate Adjudication Buffer, computed without writing anything (issue #194).

    `is_blocked`/`block_message` mirror apply_adjudications()'s two
    checks (wrong Semester, unknown Conflict id) without calling it --
    conflict_feasibility_for() is a pure read, so there's no write to
    run-and-roll-back the way preview_roster_edits() needs.
    `feasibility_by_conflict_id` keys every Conflict on the Rehearsal by
    id, for a view to zip against its own rows/formset. `loud`/`quiet` are
    the ADR-0002/issue #185-tiered Fallout lines; neither ever blocks a
    save. `is_stale` flags a `Semester.updated_at` mismatch -- reported,
    never refused, per ADR 0008.
    """

    is_blocked: bool
    block_message: str
    is_stale: bool
    feasibility_by_conflict_id: dict[int, ConflictFeasibilityRow]
    loud: list[str]
    quiet: list[str]


def _blocked_adjudication_fallout(block_message: str, *, is_stale: bool = False) -> AdjudicationFallout:
    """Return an AdjudicationFallout reporting a hard block, with no feasibility computed and no Fallout lines."""
    return AdjudicationFallout(
        is_blocked=True, block_message=block_message, is_stale=is_stale,
        feasibility_by_conflict_id={}, loud=[], quiet=[],
    )


def _feasibility_fallout_lines(approved_ids, feasibility_by_id, conflicts_by_id):
    """Build loud/quiet Fallout lines for every approved Conflict id, from its feasibility verdict/advisory (issue #194).

    Loud: the approval makes the joint set infeasible -- it breaks the
    evening. Quiet: a standing overlap on an approved row -- an admin who
    approved knowing the person will just skip a Song is in a legitimate
    state, so this never shouts.
    """
    loud, quiet = [], []
    for conflict_id in approved_ids:
        feasibility_row = feasibility_by_id.get(conflict_id)
        conflict = conflicts_by_id.get(conflict_id)
        if feasibility_row is None or conflict is None:
            continue
        if feasibility_row.verdict == INFEASIBLE:
            loud.append(f"Approving {conflict.person.name}'s Conflict leaves no Running Order that works for tonight.")
        if feasibility_row.has_standing_overlap:
            quiet.append(
                f'{conflict.person.name} is still assigned to a Song during their approved absence, with no Backup covering it.',
            )
    return loud, quiet


def preview_adjudications(buffer: AdjudicationBuffer, *, rehearsal, viewing_semester: Semester) -> AdjudicationFallout:
    """Compute feasibility verdicts and Fallout for a candidate Adjudication Buffer, writing nothing (issue #194).

    Unlike `preview_roster_edits()`, this calls no `apply_*()`:
    `conflict_feasibility_for()` is a pure read, so the candidate approved
    set lives only in `buffer.entries` and never touches the database.
    Mirrors `apply_adjudications()`'s wrong-Semester and unknown-Conflict
    checks so a Preview can never disagree with what Save would reject,
    without re-running the write itself.
    """
    if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
        return _blocked_adjudication_fallout(
            "This adjudication Buffer's Semester doesn't match the Semester you're currently viewing.",
        )
    conflicts = list(Conflict.objects.filter(rehearsal=rehearsal).select_related('person'))
    conflicts_by_id = {conflict.pk: conflict for conflict in conflicts}
    entry_ids = {entry.conflict_id for entry in buffer.entries}
    if entry_ids - conflicts_by_id.keys():
        return _blocked_adjudication_fallout(
            "This adjudication Buffer names a Conflict that doesn't belong to this Rehearsal.",
        )

    is_stale = buffer.semester_updated_at != viewing_semester.updated_at
    approved_ids = {entry.conflict_id for entry in buffer.entries if entry.status == Conflict.APPROVED}
    feasibility_rows = conflict_feasibility_for(rehearsal, approved_ids)
    feasibility_by_id = {row.conflict_id: row for row in feasibility_rows}
    loud, quiet = _feasibility_fallout_lines(approved_ids, feasibility_by_id, conflicts_by_id)
    return AdjudicationFallout(
        is_blocked=False, block_message='', is_stale=is_stale,
        feasibility_by_conflict_id=feasibility_by_id, loud=loud, quiet=quiet,
    )


_CLEARED_ADJUDICATION = {'status': Conflict.PENDING, 'adjudication_note': ''}
"""The undecided verdict every declaration is written with (issue #189).

Applied on create *and* on edit, so an admin's approval never appears to
bless a window the member has since moved, and a note reasoning about a
declaration that no longer says that never survives to be read. It lives
in `declare_conflict()` rather than in a view because that service is
already the only mapping from a declaration to Conflict/ConflictWindow
rows, so every caller gets the reset without opting in.
"""


def declare_conflict(person, rehearsal, declaration_type, declared_time=None, reason='', allow_edit=True) -> Conflict:
    """Create or edit-in-place `person`'s Conflict for `rehearsal` from an inline declaration (issues #98, #99).

    The three declaration types map to the model layer as follows, and
    this is the only place that mapping is implemented — the Conflicts page
    never calls Conflict/ConflictWindow .save() directly:
    - full_absence: a FULL_CONFLICT Conflict, no ConflictWindow.
    - late_arrival: a PARTIAL Conflict with one ConflictWindow spanning
      the Rehearsal's start_time to `declared_time`.
    - early_departure: a PARTIAL Conflict with one ConflictWindow spanning
      `declared_time` to the Rehearsal's end_time.

    Conflict has a unique (person, rehearsal) constraint, so a call against
    a Rehearsal `person` has already declared for edits that existing row
    in place (History's inline edit, issue #99) rather than raising or
    creating a second one; a call against an undeclared Rehearsal creates a
    fresh one (issue #98's declare form). `allow_edit=False` (the initial
    declare endpoint) instead rejects an already-declared Rehearsal with an
    IntegrityError, including one that only started existing after the
    caller's own pre-check raced a concurrent declaration.

    A Dress Rehearsal is rejected outright before any DB write: attendance
    there is mandatory (ADR-0006).

    Every write path here also resets the row's adjudication to pending
    with an empty note (issue #189) — see _CLEARED_ADJUDICATION.
    """
    if rehearsal.is_full_setlist:
        raise ValueError(
            'Attendance at the Dress Rehearsal (is_full_setlist=True) is mandatory, '
            'so a Conflict cannot be declared against it.'
        )
    with transaction.atomic():
        if declaration_type == CONFLICT_FULL_ABSENCE:
            conflict, created = Conflict.objects.update_or_create(
                person=person, rehearsal=rehearsal,
                defaults={'type': Conflict.FULL_CONFLICT, 'reason': reason, **_CLEARED_ADJUDICATION},
            )
        elif declaration_type in (CONFLICT_LATE_ARRIVAL, CONFLICT_EARLY_DEPARTURE):
            conflict, created = Conflict.objects.update_or_create(
                person=person, rehearsal=rehearsal,
                defaults={'type': Conflict.PARTIAL, 'reason': reason, **_CLEARED_ADJUDICATION},
            )
            conflict.conflictwindow_set.all().delete()
            if declaration_type == CONFLICT_LATE_ARRIVAL:
                window_start, window_end = rehearsal.start_time, declared_time
            else:
                window_start, window_end = declared_time, rehearsal.end_time
            ConflictWindow.objects.create(conflict=conflict, unavailable_start=window_start, unavailable_end=window_end)
        else:
            raise ValueError(f'Unknown conflict declaration_type: {declaration_type!r}')
        if not created and not allow_edit:
            raise IntegrityError(f'A Conflict already exists for person={person.pk} rehearsal={rehearsal.pk}.')
        return conflict


@dataclass(frozen=True)
class ConflictHistoryRow:
    """One History row: a Person's existing Conflict for a Rehearsal, with its display fields pre-derived (issue #99)."""

    rehearsal: Rehearsal
    conflict: Conflict
    declaration_type: str
    type_label: str
    declared_time: time | None
    is_future: bool


def _derive_declaration(conflict) -> tuple[str | None, time | None]:
    """Return (declaration_type, declared_time) derived from `conflict`'s type and, for partial, its ConflictWindow.

    Never guessed from raw field presence by a template (issue #99): a
    full_conflict Conflict is always full_absence; a partial Conflict whose
    single ConflictWindow is anchored at the Rehearsal's start_time is
    late_arrival, or at its end_time is early_departure — the only two
    shapes declare_conflict itself ever creates. `ConflictWindow` carries no
    DB-level constraint tying it to that invariant (e.g. the Django admin
    can attach zero, several, or an unanchored window), so any Conflict
    whose windows don't match exactly one of those two shapes is reported
    as (None, None) rather than crashing on a missing window or guessing
    from a single arbitrarily-picked one.
    """
    if conflict.type == Conflict.FULL_CONFLICT:
        return CONFLICT_FULL_ABSENCE, None
    rehearsal = conflict.rehearsal
    windows = list(conflict.conflictwindow_set.all())
    if len(windows) == 1:
        window = windows[0]
        if window.unavailable_start == rehearsal.start_time:
            return CONFLICT_LATE_ARRIVAL, window.unavailable_end
        if window.unavailable_end == rehearsal.end_time:
            return CONFLICT_EARLY_DEPARTURE, window.unavailable_start
    return None, None


@dataclass(frozen=True)
class RoleCreationResult:
    """The outcome of `create_or_reactivate_role()` — the Role plus how it was obtained (issue #225)."""

    role: Role
    created: bool
    reactivated: bool


def create_or_reactivate_role(name: str) -> RoleCreationResult:
    """Get-or-create a Role by name, case-insensitively, and commit immediately (issue #225).

    Backs the inline "declare Trombone right now" control on the Roster
    editor. Commits outside any Pending Buffer — discarding a batch of
    Roster edits must not un-invent a Role a row is already ticking. It
    writes with no `transaction.atomic()` wrapper and no `on_commit()`
    deferral, so — as long as no future caller nests this call inside the
    Roster batch's own `apply_roster_edits()` transaction — it commits in
    Django's default autocommit mode, independent of that batch's later
    success or failure.

    A name matching an existing Role case-insensitively returns that Role
    (`created=False`) rather than creating a near-duplicate that differs
    only in capitalisation. If that match is retired (`is_active=False`),
    it is flipped back to active (`reactivated=True`) — the soft-delete
    convention's whole point (per Role's docstring). There is no retire
    path here: retiring a Role stays a deliberate act in the Django admin.
    """
    name = name.strip()
    existing = Role.objects.filter(name__iexact=name).first()
    if existing is not None:
        reactivated = not existing.is_active
        if reactivated:
            existing.is_active = True
            existing.save(update_fields=['is_active'])
        return RoleCreationResult(role=existing, created=False, reactivated=reactivated)
    role = Role.objects.create(name=name)
    return RoleCreationResult(role=role, created=True, reactivated=False)


def _prior_semester(semester: Semester) -> Semester | None:
    """Return the Semester chronologically immediately before `semester`, or None if it is the first (issue #225).

    Ordered by `created_at` per ADR-0010, with `id` as a deterministic
    tiebreak for rows created in the same instant.
    """
    return Semester.objects.filter(
        Q(created_at__lt=semester.created_at) | Q(created_at=semester.created_at, id__lt=semester.id)
    ).order_by('-created_at', '-id').first()


@dataclass(frozen=True)
class RosterImportPerson:
    """One Person `import_roster_from_semester()` proposes to roster, with the Roles to declare fresh (issue #225)."""

    person: Person
    roles: list[Role]


@dataclass(frozen=True)
class RosterImportProposal:
    """The prior Semester's Roster, proposed as fresh declarations for a target Semester (issue #225).

    `source_semester` is None when there is nothing to import from, in
    which case `people` is empty.
    """

    source_semester: Semester | None
    people: list['RosterImportPerson']


def import_roster_from_semester(semester: Semester) -> RosterImportProposal:
    """Propose `semester`'s prior Semester's Roster as fresh declarations for `semester` (issue #225).

    A read, not a write — nothing is saved here, so the same call can
    serve both the Roster editor's import button and the setup wizard's
    roster step; the write still goes through the batch save. Deactivated
    People are excluded silently (a Person who cannot log in cannot act on
    a Membership), and the Roles returned are values to copy into fresh
    `MembershipRole` declarations, never references into the prior
    Semester's rows (ADR 0001) — editing this term can never rewrite last
    term's history.
    """
    source = _prior_semester(semester)
    if source is None:
        return RosterImportProposal(source_semester=None, people=[])
    memberships = Membership.objects.filter(
        semester=source, person__is_active=True,
    ).select_related('person').prefetch_related(
        models.Prefetch(
            'membershiprole_set',
            queryset=MembershipRole.objects.select_related('role').order_by('role__name'),
        ),
    ).order_by('person__name')
    people = [
        RosterImportPerson(
            person=membership.person,
            roles=[membership_role.role for membership_role in membership.membershiprole_set.all()],
        )
        for membership in memberships
    ]
    return RosterImportProposal(source_semester=source, people=people)


def unrostered_people_for(semester: Semester) -> list[Person]:
    """Return every active Person holding no Membership in `semester`, ordered by name (issue #229).

    Backs the Roster editor's add list — the People a "Save Changes"
    batch could newly roster. Deactivated People are excluded silently: a
    Person who cannot log in cannot act on a Membership, so offering them
    here would create a row nobody can ever use; reactivating somebody
    stays a people-management act, deliberately not offered here.
    """
    return list(
        Person.objects.filter(is_active=True).exclude(membership__semester=semester).order_by('name')
    )


def conflict_history_for(semester, person) -> list[ConflictHistoryRow]:
    """Return every Rehearsal in `semester` that `person` has declared a Conflict for, in date order (issue #99).

    **There is no History surface any more** (issue #190): the Conflicts
    page and its History section are both gone, and availability now folds
    into the rehearsal it concerns on `/schedule/`. This survives as the
    *per-row lookup* feeding that read — a reader who greps for "history"
    looking for a page will not find one. `conflict_rows_by_rehearsal()`
    is the shape `/schedule/` actually consumes.

    Includes past and future Rehearsals alike — a declaration stays
    visible on its own row once its Rehearsal has passed, inside the
    collapsed past section; `is_future` tells the view/template which rows
    may offer edit and delete.
    """
    today = timezone.localdate()
    conflicts = Conflict.objects.filter(
        person=person, rehearsal__semester=semester,
    ).select_related('rehearsal').prefetch_related('conflictwindow_set').order_by('rehearsal__date', 'rehearsal__start_time')
    rows = []
    for conflict in conflicts:
        declaration_type, declared_time = _derive_declaration(conflict)
        rows.append(ConflictHistoryRow(
            rehearsal=conflict.rehearsal,
            conflict=conflict,
            declaration_type=declaration_type,
            type_label=CONFLICT_TYPE_LABELS[declaration_type],
            declared_time=declared_time,
            is_future=conflict.rehearsal.date >= today,
        ))
    return rows


def conflict_rows_by_rehearsal(semester, person) -> dict[int, ConflictHistoryRow]:
    """Return `person`'s Conflict rows in `semester`, keyed by Rehearsal id (issue #190).

    The shape `/schedule/` actually reads: every rehearsal it renders —
    the `?view=next` detail, and every past and future `?view=all` row —
    asks this one dict whether the viewer has declared against that
    Rehearsal, so the merged page costs the same single query the
    standalone Conflicts page did rather than one lookup per row.
    """
    return {row.rehearsal.pk: row for row in conflict_history_for(semester, person)}


def landing_rehearsal_for(person, semester):
    """Return the Rehearsal `/schedule/` anchors on for `person`, or None if `semester` has none upcoming (issue #190).

    `next_attended_rehearsal_for()` first — landing on the Rehearsal you
    are personally needed at is the page's value in the common case, and
    the fallback must not move that anchor for a member who has one. But a
    member holding no Role Assignments at all is needed at none, and since
    declaring a Conflict is now an affordance *on* a rehearsal, "No
    upcoming rehearsal to show" would hide the declare path from exactly
    the members most likely to want it. So they fall back to the band's
    literal next Rehearsal.
    """
    return next_attended_rehearsal_for(person, semester) or _upcoming_rehearsals(semester).first()


class WrongViewingSemesterError(ValueError):
    """Raised when a Pending Buffer's Semester id doesn't match the session-scoped viewing Semester.

    Shared across every ADR-0008 apply function that carries this
    staleness check: `apply_roster_edits()` (issue #226) and
    `apply_song_role_assignments()` (issue #210).
    """


class StaleRosterSemesterError(ValueError):
    """Raised when a Roster edit Buffer's Semester changed since the Buffer was loaded (issue #226)."""


class SelfRemovalError(ValueError):
    """Raised when a Roster edit Buffer would remove the requesting admin's own Person (issue #226)."""


@dataclass(frozen=True)
class RosterEditEntry:
    """One Person's target Roster state in a Buffer: the name to save and the Role set to declare (issue #226)."""

    person: Person
    name: str
    role_ids: frozenset[int]


@dataclass(frozen=True)
class RosterEditBuffer:
    """The whole diff `apply_roster_edits()` commits in one transaction (issue #226).

    `semester_id` and `semester_updated_at` back the two staleness checks:
    `semester_id` is cross-checked against the caller's session-scoped
    viewing Semester (two open tabs editing different terms), and
    `semester_updated_at` against the Semester row's current stamp (another
    admin's save landed first). `entries` carries every Person the Buffer
    wants rostered afterward — existing or newly added — with the name and
    Role set to save; `removed_person_ids` names every Person to purge from
    the Roster. A Person id appearing in neither is left untouched.
    """

    semester_id: int
    semester_updated_at: datetime
    entries: list[RosterEditEntry]
    removed_person_ids: frozenset[int]


def apply_roster_edits(buffer: RosterEditBuffer, *, viewing_semester: Semester, requesting_admin: Person) -> None:
    """Apply a whole Roster Pending Buffer — adds, removals, Role sets and name edits — in one transaction (issue #226).

    The single write the Roster edit surface and its Preview both run
    (ADR-0008, issue #185): a failure anywhere leaves nothing applied.
    Takes no Semester row lock — nothing here renumbers positions, and the
    Membership/MembershipRole uniqueness constraints plus get-or-create
    absorb the concurrent-admin case, the same reasoning the existing
    `_membership_for_writing()` write helper documents.

    Removing a Person is a Semester-scoped purge, not a bare Membership
    delete: it also deletes that Semester's `SongRoleAssignment` rows and
    `Conflict` rows for them, since both point at `Person` rather than at
    `Membership` and would otherwise survive un-rostered. A prior Semester's
    rows for the same Person are untouched. Role-set changes go through
    ordinary `MembershipRole` creates/deletes so the model's own
    `post_save`/`post_delete` signals re-evaluate `is_role_mismatch` on
    every affected `SongRoleAssignment`/`Backup` — this function never
    recomputes that flag by hand.

    Raises `WrongViewingSemesterError` if `buffer.semester_id` doesn't match
    `viewing_semester`, or `SelfRemovalError` if the Buffer would remove
    `requesting_admin`'s own Person — both checked, and both writing
    nothing, before any transaction opens. Raises `StaleRosterSemesterError`
    inside the transaction if the Semester's `updated_at` no longer matches
    `buffer.semester_updated_at`, rolling back whatever this call had
    already applied. Makes no external call (no mail, no object storage),
    so nothing here needs `transaction.on_commit()`.
    """
    if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
        raise WrongViewingSemesterError(
            "This Roster edit Buffer's Semester doesn't match the Semester you're currently viewing."
        )
    if requesting_admin.pk in buffer.removed_person_ids:
        raise SelfRemovalError('An admin cannot remove their own Person from the Roster.')

    with transaction.atomic():
        semester = Semester.objects.get(pk=buffer.semester_id)
        if semester.updated_at != buffer.semester_updated_at:
            raise StaleRosterSemesterError('The Roster changed while you were editing — reload and reapply.')

        for person_id in buffer.removed_person_ids:
            _purge_person_from_semester(person_id, semester)
        for entry in buffer.entries:
            _apply_roster_edit_entry(entry, semester)

        semester.updated_at = timezone.now()
        semester.save(update_fields=['updated_at'])


def _purge_person_from_semester(person_id: int, semester: Semester) -> None:
    """Delete `person_id`'s Role Assignments and Conflicts scoped to `semester`, then their Membership.

    The Membership delete cascades onto its MembershipRoles (FK
    `on_delete=CASCADE`), the same mechanism `delete_semester()` relies on
    — declared Roles have no existence independent of their Membership, so
    there is nothing here that needs deleting explicitly.
    """
    SongRoleAssignment.objects.filter(person_id=person_id, song__semester=semester).delete()
    Conflict.objects.filter(person_id=person_id, rehearsal__semester=semester).delete()
    Membership.objects.filter(person_id=person_id, semester=semester).delete()


def _apply_roster_edit_entry(entry: RosterEditEntry, semester: Semester) -> None:
    """Save `entry.name` onto its Person, then get-or-create their Membership and reconcile its declared Roles."""
    if entry.person.name != entry.name:
        entry.person.name = entry.name
        entry.person.save(update_fields=['name'])
    membership, _ = Membership.objects.get_or_create(person=entry.person, semester=semester)
    current_role_ids = frozenset(
        MembershipRole.objects.filter(membership=membership).values_list('role_id', flat=True)
    )
    for role_id in entry.role_ids - current_role_ids:
        MembershipRole.objects.create(membership=membership, role_id=role_id)
    if current_role_ids - entry.role_ids:
        MembershipRole.objects.filter(
            membership=membership, role_id__in=current_role_ids - entry.role_ids,
        ).delete()


@dataclass(frozen=True)
class RosterRemoval:
    """One Person a Roster edit Buffer removes, carrying the name/email its removal confirm dialog needs (issue #228).

    Email is otherwise kept off the Roster surfaces (ADR 0005); the
    removal confirmation is the one place it's shown, so an admin can tell
    apart two similarly-named people before dropping one of them.
    """

    person_id: int
    name: str
    email: str


@dataclass(frozen=True)
class RosterEditFallout:
    """Every observable consequence of a Roster edit Buffer, computed without committing it (issue #228).

    `is_blocked` is true iff the Buffer cannot be saved at all (a
    WrongViewingSemesterError or SelfRemovalError) — a Validation Error in
    ADR 0008's terms, never blended with Fallout; `pending_*` and
    `loud`/`quiet` are all empty when blocked, since nothing was computed.
    `pending_*` name every row's outcome for the Preview's summary list.
    `loud`/`quiet` are human-readable Fallout messages in the two ADR
    0002/issue #228 tiers; neither ever blocks a save. `is_stale` flags a
    `Semester.updated_at` mismatch — reported, never refused, per ADR 0008.
    """

    is_blocked: bool
    block_message: str
    is_stale: bool
    pending_adds: list[str]
    pending_removals: list[RosterRemoval]
    pending_role_changes: list[str]
    pending_name_edits: list[str]
    loud: list[str]
    quiet: list[str]


def _blocked_roster_fallout(block_message: str, *, is_stale: bool = False) -> RosterEditFallout:
    """Return a RosterEditFallout reporting a hard block, with every Fallout/pending list empty."""
    return RosterEditFallout(
        is_blocked=True,
        block_message=block_message,
        is_stale=is_stale,
        pending_adds=[],
        pending_removals=[],
        pending_role_changes=[],
        pending_name_edits=[],
        loud=[],
        quiet=[],
    )


def preview_roster_edits(buffer: RosterEditBuffer, *, viewing_semester: Semester, requesting_admin: Person) -> RosterEditFallout:
    """Run the real `apply_roster_edits()` for `buffer` and report every observable consequence, without committing it.

    ADR 0008/issue #228: this function's write is real — it must be called
    inside a transaction the *caller* rolls back (`PreviewMixin` does this
    for the Roster Preview view; tests must wrap the call the same way).
    Called outside such a transaction, this function corrupts the
    database.

    Snapshots Membership/Role state, Role Assignment mismatch flags and
    per-Song Role Requirement fill status *before* calling
    `apply_roster_edits()` (with a copy of `buffer` whose
    `semester_updated_at` is swapped for the Semester's current value, so
    the real function's own staleness check always passes and the write
    actually runs), then re-reads the same state *after* and diffs the
    two — every Fallout line is a real before/after comparison, never a
    guess from the Buffer alone. A `WrongViewingSemesterError` or
    `SelfRemovalError` from `apply_roster_edits()` is reported as
    `is_blocked` with no Fallout computed at all, rather than
    re-implementing either check here.
    """
    if viewing_semester is None:
        return _blocked_roster_fallout(
            "This Roster edit Buffer's Semester doesn't match the Semester you're currently viewing."
        )

    current_semester = Semester.objects.get(pk=viewing_semester.pk)
    is_stale = buffer.semester_updated_at != current_semester.updated_at

    person_ids_in_batch = [entry.person.pk for entry in buffer.entries]
    membership_person_ids_before = frozenset(
        Membership.objects.filter(semester=viewing_semester, person_id__in=person_ids_in_batch)
        .values_list('person_id', flat=True)
    )
    role_ids_before_by_person = {
        person_id: frozenset(
            MembershipRole.objects.filter(
                membership__person_id=person_id, membership__semester=viewing_semester,
            ).values_list('role_id', flat=True)
        )
        for person_id in person_ids_in_batch
    }
    names_before_by_person = {entry.person.pk: entry.person.name for entry in buffer.entries}

    removed_people_by_id = Person.objects.in_bulk(buffer.removed_person_ids)
    removal_counts_before = {
        person_id: (
            SongRoleAssignment.objects.filter(person_id=person_id, song__semester=viewing_semester).count(),
            Conflict.objects.filter(person_id=person_id, rehearsal__semester=viewing_semester).count(),
        )
        for person_id in buffer.removed_person_ids
    }

    songs = list(Song.objects.filter(semester=viewing_semester))
    fill_before = {song.pk: {status.role.pk: status for status in fill_status_for(song)} for song in songs}
    mismatch_before = dict(
        SongRoleAssignment.objects.filter(song__semester=viewing_semester).values_list('pk', 'is_role_mismatch')
    )

    apply_buffer = replace(buffer, semester_updated_at=current_semester.updated_at)
    try:
        apply_roster_edits(apply_buffer, viewing_semester=viewing_semester, requesting_admin=requesting_admin)
    except (WrongViewingSemesterError, SelfRemovalError) as error:
        return _blocked_roster_fallout(str(error), is_stale=is_stale)

    pending_adds = []
    pending_removals = [
        RosterRemoval(person_id=person_id, name=person.name, email=person.email)
        for person_id, person in removed_people_by_id.items()
    ]
    pending_role_changes = []
    pending_name_edits = []
    for entry in buffer.entries:
        person_id = entry.person.pk
        if person_id not in membership_person_ids_before:
            pending_adds.append(entry.name)
            continue
        if entry.name != names_before_by_person[person_id]:
            pending_name_edits.append(f'{names_before_by_person[person_id]} → {entry.name}')
        if entry.role_ids != role_ids_before_by_person[person_id]:
            pending_role_changes.append(entry.name)

    loud = []
    for person_id, (assignment_count, conflict_count) in removal_counts_before.items():
        if assignment_count == 0 and conflict_count == 0:
            continue
        name = removed_people_by_id[person_id].name
        loud.append(
            f"{name}'s removal destroys {assignment_count} Role Assignment{'' if assignment_count == 1 else 's'} "
            f"and deletes {conflict_count} Conflict{'' if conflict_count == 1 else 's'}."
        )

    for song in songs:
        before_map = fill_before[song.pk]
        after_map = {status.role.pk: status for status in fill_status_for(song)}
        for role_id, before_status in before_map.items():
            after_status = after_map.get(role_id)
            if before_status.actual > 0 and after_status is not None and after_status.actual == 0:
                loud.append(
                    f'{song.title} has no one left to fill {before_status.role.name} (target {before_status.target}).'
                )

    quiet = []
    for entry in buffer.entries:
        person_id = entry.person.pk
        after_role_count = MembershipRole.objects.filter(
            membership__person_id=person_id, membership__semester=viewing_semester,
        ).count()
        if after_role_count == 0:
            quiet.append(f'{entry.name} has no declared Roles.')

    after_assignments = {
        assignment.pk: assignment
        for assignment in SongRoleAssignment.objects.filter(
            song__semester=viewing_semester,
        ).select_related('person', 'role', 'song')
    }
    for assignment_id, was_mismatch in mismatch_before.items():
        after_assignment = after_assignments.get(assignment_id)
        if after_assignment is None or was_mismatch:
            continue
        if after_assignment.is_role_mismatch:
            quiet.append(
                f"{after_assignment.person.name}'s change newly flags their {after_assignment.role.name} "
                f'assignment on {after_assignment.song.title} as a mismatch.'
            )

    return RosterEditFallout(
        is_blocked=False,
        block_message='',
        is_stale=is_stale,
        pending_adds=pending_adds,
        pending_removals=pending_removals,
        pending_role_changes=pending_role_changes,
        pending_name_edits=pending_name_edits,
        loud=loud,
        quiet=quiet,
    )


class StaleSetlistSemesterError(ValueError):
    """Raised when a Setlist edit Buffer's Semester changed since the Buffer was loaded (issue #321)."""


@dataclass(frozen=True)
class SetlistEditRow:
    """One setlist edit grid row's target state, in final concert-position order: an existing Song's edit, or a brand-new one (issue #321).

    `song_id` is None for a new row. Unlike `RehearsalEditBuffer`'s rows
    (ordered by `date`, an independent field), a Song's position has no
    field of its own to derive an order from, so a row's position *is*
    its index in the Buffer's own `rows` list — the same "list order is
    the buffer's own row order" convention `SetlistEditView._save_buffer()`
    used to read off `song_order` by hand. Filled identically by a
    hand-edit (from a bound `SetlistEditFormSet`) and a Spotify import
    (`SetlistImportView`'s unsaved rows, appended client-side before Save).
    """

    song_id: int | None
    title: str
    artist: str
    length: timedelta
    notes: str


@dataclass(frozen=True)
class SetlistEditBuffer:
    """The whole diff `apply_setlist_edits()` commits in one transaction (issue #321).

    `semester_id`/`semester_updated_at` back the same two staleness checks
    every other Pending Buffer uses (issue #226's shape): `semester_id` is
    cross-checked against the caller's session-scoped viewing Semester, and
    `semester_updated_at` against the Semester row's current stamp. `rows`
    carries every surviving Song in final concert-position order —
    existing or newly added; a Song not named in `rows` and not in
    `deleted_song_ids` doesn't exist yet and never will.
    `deleted_song_ids` names every existing Song the grid's struck-row
    control marked for a hard delete.
    """

    semester_id: int
    semester_updated_at: datetime
    rows: list[SetlistEditRow]
    deleted_song_ids: frozenset[int] = field(default_factory=frozenset)


def apply_setlist_edits(buffer: SetlistEditBuffer, *, viewing_semester: Semester) -> None:
    """Apply a whole Setlist edit Buffer — adds, edits, deletes and reorder — in one transaction (issue #321).

    The single write the setlist edit grid and its future Preview both
    run (ADR-0008): a failure anywhere leaves nothing applied. Holds the
    Semester row lock for the duration, like every other Song-position
    mutation must — a whole-setlist reorder ends in `reorder_songs()`,
    exactly the write CLAUDE.md's locking rule exists for.

    Deletions (`delete_songs_with_recordings()`) run first, before any
    surviving row is saved — mirroring the prior inline `_save_buffer()`'s
    ordering — so a row moved out from under a doomed Song's old position
    can never collide with it; the deferred
    `unique_song_position_per_semester` constraint makes the sequence
    collision-free either way. Every surviving row is then saved with a
    throwaway `position=0` (a new instance has none yet, and an existing
    one's current position may already collide with another surviving
    row's target slot); `reorder_songs()` renumbers `buffer.rows`' exact
    order to a contiguous `1..N` afterward, on the surviving Song ids
    alone.

    Raises `WrongViewingSemesterError` if `buffer.semester_id` doesn't
    match `viewing_semester`, checked before any transaction opens. Raises
    `StaleSetlistSemesterError` inside the transaction if the Semester's
    `updated_at` no longer matches `buffer.semester_updated_at`, rolling
    back whatever this call had already applied. Makes no external call
    of its own — `delete_songs_with_recordings()` registers its Recording
    object-storage cleanup with `transaction.on_commit()` itself — so
    nothing here needs its own `on_commit()`.
    """
    if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
        raise WrongViewingSemesterError(
            "This Setlist edit Buffer's Semester doesn't match the Semester you're currently viewing."
        )

    with transaction.atomic():
        semester = Semester.objects.select_for_update().get(pk=buffer.semester_id)
        if semester.updated_at != buffer.semester_updated_at:
            raise StaleSetlistSemesterError('The setlist changed while you were editing — reload and reapply.')

        if buffer.deleted_song_ids:
            delete_songs_with_recordings(
                list(Song.objects.filter(semester=semester, pk__in=buffer.deleted_song_ids))
            )

        ordered_ids = [_apply_setlist_edit_row(row, semester).pk for row in buffer.rows]
        reorder_songs(semester, ordered_ids)

        semester.updated_at = timezone.now()
        semester.save(update_fields=['updated_at'])


def _apply_setlist_edit_row(row: SetlistEditRow, semester: Semester) -> Song:
    """Save one Buffer row onto its Song (existing or new) with a throwaway position; return the saved Song."""
    if row.song_id is not None:
        song = Song.objects.get(pk=row.song_id, semester=semester)
    else:
        song = Song(semester=semester)
    song.title = row.title
    song.artist = row.artist
    song.length = row.length
    song.notes = row.notes
    song.position = 0
    song.save()
    return song


@dataclass(frozen=True)
class SetlistSongDeletion:
    """One doomed Song's recording/uploader/Running-Order counts, for the Save popup's escalation block (issue #321).

    Mirrors `SongDeletionSummary`, extended with `running_order_count` —
    the number of Rehearsals whose Running Order this Song currently sits
    in, every one of which loses that row when the Song is deleted (per
    ADR-0003 the Dress Rehearsal never holds a `RehearsalSong`, so it is
    never counted here). This is `song_deletion_summaries()`'s old
    doomed-Recordings content, folded into the Setlist Fallout as the one
    escalation block a destructive Save opens, per #306/#310's "the Save
    popup is the only home for Fallout" rule.
    """

    title: str
    recording_count: int
    uploader_count: int
    running_order_count: int


@dataclass(frozen=True)
class SetlistEditFallout:
    """Every observable consequence of a Setlist edit Buffer, computed without committing it (issue #321, ADR 0008).

    `is_blocked` mirrors `apply_setlist_edits()`'s Validation Errors (wrong
    Semester, stale stamp) with no Fallout computed at all — a Validation
    Error in ADR 0008's terms. `loud`/`quiet` are the two ADR-0002 tiers;
    neither ever blocks a save. `is_stale` flags a `Semester.updated_at`
    mismatch, reported never refused, per ADR 0008. `pending_deletions`
    is non-empty exactly when the Buffer would destroy at least one Song —
    the one condition that should fire a destructive-save escalation on
    Save. `reordered` is true iff the Buffer's final concert-position
    order differs from the surviving Songs' current order — reported as a
    quiet line, since a reorder changes concert position only and never
    touches any Rehearsal's Running Order.
    """

    is_blocked: bool
    block_message: str
    is_stale: bool
    pending_adds: list[str]
    pending_edits: list[str]
    reordered: bool
    pending_deletions: list[SetlistSongDeletion]
    loud: list[str]
    quiet: list[str]


def _blocked_setlist_fallout(block_message: str, *, is_stale: bool = False) -> SetlistEditFallout:
    """Return a SetlistEditFallout reporting a hard block, with every Fallout/pending list empty."""
    return SetlistEditFallout(
        is_blocked=True,
        block_message=block_message,
        is_stale=is_stale,
        pending_adds=[],
        pending_edits=[],
        reordered=False,
        pending_deletions=[],
        loud=[],
        quiet=[],
    )


def preview_setlist_edits(buffer: SetlistEditBuffer, *, viewing_semester: Semester) -> SetlistEditFallout:
    """Run the real `apply_setlist_edits()` for `buffer` and report every observable consequence, without committing it (issue #321, ADR-0008).

    This function's write is real — it must be called inside a
    transaction the *caller* rolls back (a Preview view's `PreviewMixin`
    does this; a test calling this directly must wrap it the same way, per
    `assert_preview_writes_nothing`). Called outside such a transaction,
    this function corrupts the database.

    Snapshots each existing Song named in the Buffer (title/artist/length/
    notes) and the Semester's current position order, plus — for every
    Song `buffer.deleted_song_ids` would destroy — its Recording and
    distinct-uploader counts (via `song_deletion_summaries()`) and how many
    Rehearsals' Running Orders it currently sits in, all *before* calling
    `apply_setlist_edits()` (with a copy of `buffer` whose
    `semester_updated_at` is swapped for the Semester's current value, so
    the real function's own staleness check always passes and the write
    actually runs). A `WrongViewingSemesterError` or
    `StaleSetlistSemesterError` from `apply_setlist_edits()` is reported as
    `is_blocked` with no Fallout computed at all, rather than
    re-implementing either check here.
    """
    if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
        return _blocked_setlist_fallout(
            "This Setlist edit Buffer's Semester doesn't match the Semester you're currently viewing."
        )

    current_semester = Semester.objects.get(pk=viewing_semester.pk)
    is_stale = buffer.semester_updated_at != current_semester.updated_at

    existing_ids = [row.song_id for row in buffer.rows if row.song_id is not None]
    songs_before = {
        song.pk: song for song in Song.objects.filter(semester=current_semester, pk__in=existing_ids)
    }
    surviving_current_order = [
        song_id for song_id in
        Song.objects.filter(semester=current_semester).order_by('position').values_list('pk', flat=True)
        if song_id not in buffer.deleted_song_ids
    ]

    songs_to_delete = list(Song.objects.filter(semester=current_semester, pk__in=buffer.deleted_song_ids))
    deletion_summaries = song_deletion_summaries(songs_to_delete)
    running_order_count_by_song_id = {
        song.pk: RehearsalSong.objects.filter(song=song).count() for song in songs_to_delete
    }
    pending_deletions = [
        SetlistSongDeletion(
            title=summary.song.title,
            recording_count=summary.recording_count,
            uploader_count=summary.uploader_count,
            running_order_count=running_order_count_by_song_id[summary.song.pk],
        )
        for summary in deletion_summaries
    ]

    apply_buffer = replace(buffer, semester_updated_at=current_semester.updated_at)
    try:
        apply_setlist_edits(apply_buffer, viewing_semester=viewing_semester)
    except (WrongViewingSemesterError, StaleSetlistSemesterError) as error:
        return _blocked_setlist_fallout(str(error), is_stale=is_stale)

    pending_adds = []
    pending_edits = []
    for row in buffer.rows:
        before = songs_before.get(row.song_id)
        if before is None:
            pending_adds.append(row.title)
            continue
        if (before.title, before.artist, before.length, before.notes) != (row.title, row.artist, row.length, row.notes):
            pending_edits.append(f'{before.title} → {row.title}' if before.title != row.title else row.title)

    final_order = [row.song_id for row in buffer.rows if row.song_id is not None]
    reordered = final_order != surviving_current_order

    loud = []
    for deletion in pending_deletions:
        parts = []
        if deletion.recording_count:
            parts.append(f"{deletion.recording_count} recording{'' if deletion.recording_count == 1 else 's'}")
        if deletion.running_order_count:
            parts.append(
                f"{deletion.running_order_count} rehearsal Running Order"
                f"{'' if deletion.running_order_count == 1 else 's'}"
            )
        if parts:
            loud.append(f"Deleting {deletion.title} destroys {' and '.join(parts)}.")

    quiet = []
    if reordered:
        quiet.append(
            'Reordering the setlist changes concert position only — it does not change any rehearsal’s Running Order.'
        )

    return SetlistEditFallout(
        is_blocked=False,
        block_message='',
        is_stale=is_stale,
        pending_adds=pending_adds,
        pending_edits=pending_edits,
        reordered=reordered,
        pending_deletions=pending_deletions,
        loud=loud,
        quiet=quiet,
    )


class StaleSongRoleRequirementsError(ValueError):
    """Raised when a Song's Role Requirements changed since the edit Buffer was loaded (issue #209)."""


@dataclass(frozen=True)
class SongRoleRequirementEntry:
    """One Role's desired target count in a Song Role Requirement edit Buffer (issue #209)."""

    role_id: int
    count: int


@dataclass(frozen=True)
class SongRoleRequirementBuffer:
    """The whole diff `apply_song_role_requirements()` commits in one transaction (issue #209).

    `entries` names every Requirement the Song should have afterward —
    existing rows carrying an unchanged or edited `count`, plus brand-new
    rows from "+ Add requirement" — keyed by `role_id`. Any existing
    Requirement whose Role doesn't appear here is deleted. `semester_id`
    and `semester_updated_at` back the same two staleness checks
    `apply_roster_edits()` uses (issue #226): `semester_id` is cross-checked
    against the caller's session-scoped viewing Semester (two open tabs
    editing different terms), and `semester_updated_at` against the
    Semester row's current stamp (another admin's save landed first).
    """

    song_id: int
    semester_id: int
    semester_updated_at: datetime
    entries: list[SongRoleRequirementEntry]


def apply_song_role_requirements(buffer: SongRoleRequirementBuffer, *, viewing_semester: Semester) -> Song:
    """Apply a Song's Role Requirement creates, count changes and deletions in one transaction (issue #209).

    This surface ships no `preview_` sibling, deliberately: applying ADR
    0008's own test — is there fallout only the server can compute? — the
    answer is no on both counts. Deleting a Requirement destroys nothing
    and cascades nowhere (no SongRoleAssignment, Role, or other Song's
    Requirements are touched), and unfilled count is target minus actual,
    which the Song page already renders in read mode via `fill_status_for()`.
    Asking an admin to confirm a computation the page already shows them
    would be ceremony, not safety.

    Takes no Semester row lock: nothing here renumbers positions, the same
    reasoning #130 and `apply_roster_edits()` document.

    Raises `WrongViewingSemesterError` if `buffer.semester_id` doesn't
    match `viewing_semester`, checked before any transaction opens, so two
    open tabs can't write pending edits built against one term into
    another. Raises `StaleSongRoleRequirementsError` if the Semester's
    `updated_at` no longer matches `buffer.semester_updated_at`, checked
    via a conditional `UPDATE ... WHERE updated_at = <buffer's stamp>` —
    not a row lock, a single compare-and-swap statement — so the read of
    the stamp and its bump to a fresh value happen as one atomic operation
    a concurrent call can't interleave with; two overlapping requests
    built from the same stale stamp can no longer both pass the check and
    commit.
    """
    if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
        raise WrongViewingSemesterError(
            "This Requirements edit Buffer's Semester doesn't match the Semester you're currently viewing."
        )

    with transaction.atomic():
        rows_updated = Semester.objects.filter(
            pk=buffer.semester_id, updated_at=buffer.semester_updated_at,
        ).update(updated_at=timezone.now())
        if rows_updated == 0:
            raise StaleSongRoleRequirementsError(
                'The Requirements changed while you were editing — reload and reapply.'
            )

        semester = Semester.objects.get(pk=buffer.semester_id)
        song = Song.objects.get(pk=buffer.song_id, semester=semester)
        existing_by_role_id = {
            requirement.role_id: requirement
            for requirement in SongRoleRequirement.objects.filter(song=song)
        }
        wanted_role_ids = {entry.role_id for entry in buffer.entries}

        stale_role_ids = set(existing_by_role_id) - wanted_role_ids
        if stale_role_ids:
            SongRoleRequirement.objects.filter(song=song, role_id__in=stale_role_ids).delete()

        for entry in buffer.entries:
            existing = existing_by_role_id.get(entry.role_id)
            if existing is None:
                SongRoleRequirement.objects.create(song=song, role_id=entry.role_id, count=entry.count)
            elif existing.count != entry.count:
                existing.count = entry.count
                existing.save(update_fields=['count'])

    return song


class StaleRehearsalSemesterError(ValueError):
    """Raised when a Rehearsal edit Buffer's Semester changed since the Buffer was loaded (issue #219)."""


class PastRehearsalEditError(ValueError):
    """Raised when a Rehearsal edit Buffer names a row that is, or has become, past-dated (issue #219).

    Covers three ways the past/future boundary can move between GET and
    POST, since the edit grid never renders inputs for a past-dated
    Rehearsal (`ScheduleEditView`'s queryset excludes it entirely): (1) the
    row's *submitted* `date` (new or existing) is itself already before
    today, e.g. a Rehearsal dated "today" at render time whose save lands
    after midnight; (2) an existing row's *current stored* `date` has
    slipped into the past under a different edit (its submission may still
    name a future date, but the ground moved out from under it); (3) an
    existing row's Rehearsal no longer exists in this Semester at all.
    Matches the posture of `WrongViewingSemesterError`: a hard failure,
    not Fallout, that writes nothing.
    """


class RunningOrderValidationError(ValueError):
    """Raised when a Rehearsal edit Buffer's Running Order sub-grid can't be saved as submitted (issue #220).

    Covers the two new blocking Validation Errors the sub-grid introduces
    — a row's slot_counts summing past the Semester's `default_song_slot_count`,
    and a Running Order attached to a row flagged Dress (ADR-0003) — plus a
    submitted Song id that doesn't belong to the buffer's own Semester.
    Raised before any write, same posture as `PastRehearsalEditError`: a
    hard failure, not Fallout, that writes nothing.
    """


@dataclass(frozen=True)
class RunningOrderRow:
    """One Running Order sub-grid row's target state: an existing RehearsalSong's edit, or a brand-new one (issue #220).

    `rehearsal_song_id` is None for a row not yet backed by a saved
    RehearsalSong. `song_id` is never attacker-typeable as free text — it
    names a Song picked from the "+ Add song" list, and `apply_rehearsal_edits()`
    rejects one that doesn't belong to the buffer's own Semester.
    """

    rehearsal_song_id: int | None
    song_id: int
    slot_count: int


@dataclass(frozen=True)
class RehearsalEditRow:
    """One Rehearsal edit grid row's target state: an existing Rehearsal's edit, or a brand-new one (issue #219).

    `rehearsal_id` is None for a new row. A None override
    (`setup_grace_minutes`, `teardown_grace_minutes`, `arrival_buffer_minutes`,
    `departure_buffer_minutes`) means "inherit the Semester default";
    `apply_rehearsal_edits()` resolves it to the Semester's current default
    at save time rather than leaving it null, since every other read of
    these fields (e.g. `attendance_suggestion_for`) assumes a concrete
    value. `end_time` is the one field still allowed to reach `apply_*` as
    None (only legal for a new row): `Rehearsal.save()`'s own defaulting
    derives it from the Semester's default duration, exactly as a
    hand-created Rehearsal already does.

    `running_order` (issue #220) is this row's Running Order sub-grid buffer,
    in submitted display order — empty for a Rehearsal left with no songs,
    which is legal. A row still carrying a `running_order` while
    `is_full_setlist=True` is a blocking Validation Error (ADR-0003: the
    Dress Rehearsal holds no RehearsalSong rows), checked before any write.
    """

    rehearsal_id: int | None
    date: date
    start_time: time
    end_time: time | None
    is_full_setlist: bool
    setup_grace_minutes: int | None
    teardown_grace_minutes: int | None
    arrival_buffer_minutes: int | None
    departure_buffer_minutes: int | None
    running_order: list[RunningOrderRow] = field(default_factory=list)


@dataclass(frozen=True)
class RehearsalEditBuffer:
    """The whole diff `apply_rehearsal_edits()` commits in one transaction (issue #219).

    `semester_id`/`semester_updated_at` back the same two staleness checks
    `RosterEditBuffer` and `AssignmentEditBuffer` use. `rows` carries every
    Rehearsal the grid wants saved — existing or newly added — in no
    particular order; a Rehearsal the buffer doesn't mention (and that
    doesn't appear in `deleted_rehearsal_ids` either) is left untouched.
    `deleted_rehearsal_ids` names every Rehearsal the grid's "Remove" row
    control marked for a hard delete (issue #221) — never a flag, since a
    Rehearsal's whole Semester is already hard-deletable (ADR 0001's
    reasoning generalized).
    """

    semester_id: int
    semester_updated_at: datetime
    rows: list[RehearsalEditRow]
    deleted_rehearsal_ids: list[int] = field(default_factory=list)


# Rehearsal override field name -> Semester default field name. Shared by RehearsalEditRowForm's
# placeholders (forms.py) and _apply_rehearsal_edit_row()'s blank-resolution below, so the two lists
# of four fields can't drift apart (issue #219).
REHEARSAL_OVERRIDE_FIELDS = (
    ('setup_grace_minutes', 'default_setup_grace_minutes'),
    ('teardown_grace_minutes', 'default_teardown_grace_minutes'),
    ('arrival_buffer_minutes', 'default_arrival_buffer_minutes'),
    ('departure_buffer_minutes', 'default_departure_buffer_minutes'),
)


def apply_rehearsal_edits(buffer: RehearsalEditBuffer, *, viewing_semester: Semester) -> None:
    """Apply a whole Rehearsal edit Buffer — new rows and edits to existing ones — in one transaction (issue #219).

    The single write the rehearsal editor and its future Preview both run
    (ADR-0008). Holds the Semester row lock for the duration, since this
    surface is the one the Running Order sub-grid (issue #220) and the
    schedule generators land renumbering work onto next.

    Raises `WrongViewingSemesterError` if `buffer.semester_id` doesn't
    match `viewing_semester`, checked before any transaction opens. Raises
    `StaleRehearsalSemesterError` inside the transaction if the Semester's
    `updated_at` no longer matches `buffer.semester_updated_at`. Raises
    `PastRehearsalEditError` for any row that is, or has become, past-dated
    — see that error's docstring for the three cases — and for any id in
    `deleted_rehearsal_ids` whose Rehearsal has slipped into the past under
    a different edit. `deleted_rehearsal_ids` (issue #221) are hard-deleted
    via `delete_rehearsals_with_recordings()` before any row is saved, so a
    deleted Rehearsal's date can never collide with a surviving or new
    row's. Raises
    `RunningOrderValidationError` (issue #220) for a row whose Running Order
    slot_counts sum past the Semester's `default_song_slot_count`, whose
    Running Order is non-empty while `is_full_setlist=True`, or whose
    Running Order names a Song outside this Semester's setlist. All of the
    above roll back whatever this call had already applied.
    """
    if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
        raise WrongViewingSemesterError(
            "This Rehearsal edit Buffer's Semester doesn't match the Semester you're currently viewing."
        )

    with transaction.atomic():
        semester = Semester.objects.select_for_update().get(pk=buffer.semester_id)
        if semester.updated_at != buffer.semester_updated_at:
            raise StaleRehearsalSemesterError('The rehearsals changed while you were editing — reload and reapply.')

        today = timezone.localdate()
        existing_ids = [row.rehearsal_id for row in buffer.rows if row.rehearsal_id is not None]
        current_dates_by_id = dict(
            Rehearsal.objects.filter(
                semester=semester, pk__in=[*existing_ids, *buffer.deleted_rehearsal_ids],
            ).values_list('pk', 'date')
        )
        for row in buffer.rows:
            if row.date < today:
                raise PastRehearsalEditError(
                    'A Rehearsal in this Buffer is dated in the past — reload and reapply.'
                )
            if row.rehearsal_id is not None:
                current_date = current_dates_by_id.get(row.rehearsal_id)
                if current_date is None or current_date < today:
                    raise PastRehearsalEditError(
                        'A Rehearsal in this Buffer is dated in the past — reload and reapply.'
                    )
        for deleted_id in buffer.deleted_rehearsal_ids:
            current_date = current_dates_by_id.get(deleted_id)
            if current_date is None or current_date < today:
                raise PastRehearsalEditError(
                    'A Rehearsal in this Buffer is dated in the past — reload and reapply.'
                )

        if buffer.deleted_rehearsal_ids:
            delete_rehearsals_with_recordings(
                Rehearsal.objects.filter(semester=semester, pk__in=buffer.deleted_rehearsal_ids)
            )

        valid_song_ids = set(
            Song.objects.filter(
                semester=semester,
                pk__in={running_order_row.song_id for row in buffer.rows for running_order_row in row.running_order},
            ).values_list('pk', flat=True)
        )
        for row in buffer.rows:
            if row.running_order and row.is_full_setlist:
                raise RunningOrderValidationError(
                    'A Running Order cannot be attached to a Rehearsal flagged as the Dress Rehearsal — '
                    'its songs are derived live from the setlist instead.'
                )
            if sum(running_order_row.slot_count for running_order_row in row.running_order) > semester.default_song_slot_count:
                raise RunningOrderValidationError(
                    "A Rehearsal's Running Order slot counts exceed the Semester's default_song_slot_count."
                )
            if any(running_order_row.song_id not in valid_song_ids for running_order_row in row.running_order):
                raise RunningOrderValidationError(
                    "A Running Order names a Song outside this Semester's setlist — reload and reapply."
                )

        # Parking every existing row at a unique, unreachable sentinel date first means two rows
        # swapping dates with each other can never collide with `unique_rehearsal_date_per_semester`
        # mid-batch — sequential saves would otherwise hit the other row's not-yet-updated date.
        for rehearsal_id in existing_ids:
            Rehearsal.objects.filter(pk=rehearsal_id, semester=semester).update(
                date=_sentinel_parking_date(rehearsal_id)
            )

        for row in buffer.rows:
            rehearsal = _apply_rehearsal_edit_row(row, semester)
            _apply_running_order(rehearsal, row.running_order)

        semester.updated_at = timezone.now()
        semester.save(update_fields=['updated_at'])


def _sentinel_parking_date(rehearsal_id: int) -> date:
    """A date far enough in the future to collide with no real Rehearsal, unique per `rehearsal_id` (issue #219)."""
    return date(9999, 12, 31) - timedelta(days=rehearsal_id)


def _apply_rehearsal_edit_row(row: RehearsalEditRow, semester: Semester) -> Rehearsal:
    """Save one Buffer row onto its Rehearsal (existing or new), resolving blank overrides to the Semester's current defaults; return it."""
    if row.rehearsal_id is not None:
        rehearsal = Rehearsal.objects.get(pk=row.rehearsal_id, semester=semester)
    else:
        rehearsal = Rehearsal(semester=semester)
    rehearsal.date = row.date
    rehearsal.start_time = row.start_time
    rehearsal.end_time = row.end_time
    rehearsal.is_full_setlist = row.is_full_setlist
    for field_name, default_field_name in REHEARSAL_OVERRIDE_FIELDS:
        value = getattr(row, field_name)
        setattr(rehearsal, field_name, value if value is not None else getattr(semester, default_field_name))
    rehearsal.save()
    return rehearsal


def _apply_running_order(rehearsal: Rehearsal, rows: list[RunningOrderRow]) -> None:
    """Save one Rehearsal's Running Order buffer — adds, edits and removals — then hand the final order to `reorder_rehearsal_songs()` (issue #220).

    `reorder_rehearsal_songs()` is the single place the reorder/re-derive
    logic exists (issue #220's spec), so this function's job is only to
    make every row it names *exist* with the right `slot_count` first:
    removed rows are deleted via `delete_rehearsal_songs_with_recordings()`;
    a surviving existing row's `slot_count` is updated with a bulk
    `.update()` (bypassing `RehearsalSong.save()`'s own validation, which
    is redundant here — see below); a brand-new row (no `rehearsal_song_id`)
    is created at a throwaway placeholder `order` clear of every other
    row's current or soon-to-be-placeholder value, purely so its `INSERT`
    doesn't collide with `unique_order_per_rehearsal` before
    `reorder_rehearsal_songs()` moves everything to its final position.
    Slot-count overflow is pre-validated by the caller against the *sum*
    of every row's slot_count, which holds at every intermediate
    arrangement this function and `reorder_rehearsal_songs()` produce (a
    row's `_prior_slots()` can only sum a subset of the other rows'
    slot_counts, whatever their current `order`), so no individual
    `.save()` anywhere in this sequence can spuriously trip
    `RehearsalSong._overruns_rehearsal_window()`. Must run inside the
    caller's `transaction.atomic()`, same as `reorder_rehearsal_songs()`.
    """
    existing_by_id = {rehearsal_song.pk: rehearsal_song for rehearsal_song in RehearsalSong.objects.filter(rehearsal=rehearsal)}
    submitted_ids = {row.rehearsal_song_id for row in rows if row.rehearsal_song_id is not None}
    # A row here can be Recording-bearing or manually re-slotted -- unlike `deal_running_orders()`/
    # `shuffle_rehearsal_running_order()` (issue #223), which refuse to ever move or delete such a row,
    # this manual path (a hand-typed Buffer, saved through apply_rehearsal_edits()) allows exactly that.
    # That asymmetry is intentional: an admin editing the grid by hand is making a deliberate, reviewable
    # choice a bulk generator never gets to make blind.
    removed = [rehearsal_song for pk, rehearsal_song in existing_by_id.items() if pk not in submitted_ids]
    if removed:
        delete_rehearsal_songs_with_recordings(removed)

    for row in rows:
        if row.rehearsal_song_id is not None:
            RehearsalSong.objects.filter(pk=row.rehearsal_song_id).update(slot_count=row.slot_count)

    placeholder_base = max([len(rows), *(rehearsal_song.order for rehearsal_song in existing_by_id.values())], default=len(rows))
    ordered_ids = []
    for offset, row in enumerate(rows, start=1):
        if row.rehearsal_song_id is not None:
            ordered_ids.append(row.rehearsal_song_id)
        else:
            new_rehearsal_song = RehearsalSong(
                rehearsal=rehearsal, song_id=row.song_id, slot_count=row.slot_count, order=placeholder_base + offset,
            )
            new_rehearsal_song.save()
            ordered_ids.append(new_rehearsal_song.pk)

    reorder_rehearsal_songs(rehearsal, ordered_ids)


@dataclass(frozen=True)
class DoomedRecordingGroup:
    """One Rehearsal's destroyed-Recording tally for the destructive-save confirmation dialog (issue #221).

    Captured from *before* `apply_rehearsal_edits()` runs: a whole-Rehearsal
    delete leaves nothing to look display fields up from afterward, so
    `label` (its date) travels here instead of a live FK. Per ADR 0005 this
    never names who declared a Conflict, and a Conflict destroyed alongside
    a deleted Rehearsal is never counted here at all — only Recordings are.
    """

    label: str
    recording_count: int
    uploader_count: int


@dataclass(frozen=True)
class RehearsalEditFallout:
    """Every observable consequence of a Rehearsal edit Buffer, computed without committing it (issue #221, ADR 0008).

    `is_blocked` mirrors `apply_rehearsal_edits()`'s Validation Errors
    (wrong Semester, stale stamp, a past-dated row, a malformed Running
    Order) with no Fallout computed at all — a Validation Error in ADR
    0008's terms, rendered in a region kept visually separate from Fallout.
    `loud`/`quiet` are the two ADR-0002 tiers; neither ever blocks a save.
    `is_stale` flags a `Semester.updated_at` mismatch, reported never
    refused, per ADR 0008. `doomed_recording_groups` is non-empty exactly
    when the buffer would destroy at least one Recording — across all
    three destructive causes (a deleted Rehearsal, a removed recorded
    Running Order row, or a Rehearsal flipped to Dress, which removes its
    Running Order per ADR 0003) — the one condition that fires the single
    destructive-save confirmation dialog on Save.
    """

    is_blocked: bool
    block_message: str
    is_stale: bool
    loud: list[str]
    quiet: list[str]
    doomed_recording_groups: list[DoomedRecordingGroup]


def _blocked_rehearsal_fallout(block_message: str, *, is_stale: bool = False) -> RehearsalEditFallout:
    """Return a RehearsalEditFallout reporting a hard block, with every Fallout/doomed list empty."""
    return RehearsalEditFallout(
        is_blocked=True, block_message=block_message, is_stale=is_stale,
        loud=[], quiet=[], doomed_recording_groups=[],
    )


def _format_slot(start_time, end_time) -> str:
    """Return a "H:MM–H:MM" rendering of one RehearsalSong slot, for a Fallout line naming an old/new time."""
    return f'{start_time:%-I:%M}–{end_time:%-I:%M}'


def preview_rehearsal_edits(buffer: RehearsalEditBuffer, *, viewing_semester: Semester) -> RehearsalEditFallout:
    """Run the real `apply_rehearsal_edits()` for `buffer` and report every observable consequence, without committing it (issue #221, ADR-0008).

    This function's write is real — it must be called inside a transaction
    the *caller* rolls back, exactly like `preview_roster_edits()`. Called
    outside such a transaction, this function corrupts the database.

    Snapshots, for every Rehearsal the buffer touches (edited or deleted),
    its Recordings' object identities/uploaders and each surviving
    RehearsalSong's persisted slot *before* calling `apply_rehearsal_edits()`
    (with a copy of `buffer` whose `semester_updated_at` is swapped for the
    Semester's current value, so the real function's own staleness check
    always passes and the write actually runs), then re-reads the same
    state *after* and diffs the two: a Recording present before and gone
    after is destroyed (grouped by its original Rehearsal, for the
    destructive-save dialog); a RehearsalSong that survives but whose slot
    moved is a re-timed Recording, named old-slot-to-new. Every other
    edited-or-new Rehearsal's post-apply Running Order is handed to
    `_assignment_fallout_lines()` (issue #212) for the loud Conflict/Conflict
    Window overlap and quiet unfilled-Requirement/mismatch tiers ADR-0009
    built that function to raise, plus this issue's own checks: a non-Dress
    Rehearsal left with zero songs, and a partial Conflict Window that used
    to overlap the Rehearsal's window and no longer does (an inert
    notification, never a call to act — the window itself is untouched).
    A `WrongViewingSemesterError`, `StaleRehearsalSemesterError`,
    `PastRehearsalEditError` or `RunningOrderValidationError` from
    `apply_rehearsal_edits()` is reported as `is_blocked` with no Fallout
    computed at all, rather than re-implementing any of those checks here.
    """
    if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
        return _blocked_rehearsal_fallout(
            "This Rehearsal edit Buffer's Semester doesn't match the Semester you're currently viewing."
        )

    current_semester = Semester.objects.get(pk=viewing_semester.pk)
    is_stale = buffer.semester_updated_at != current_semester.updated_at

    touched_ids = [
        *(row.rehearsal_id for row in buffer.rows if row.rehearsal_id is not None),
        *buffer.deleted_rehearsal_ids,
    ]
    rehearsals_before = {
        rehearsal.pk: rehearsal
        for rehearsal in Rehearsal.objects.filter(semester=current_semester, pk__in=touched_ids)
    }
    conflicts_before = {
        rehearsal_id: [
            (window.unavailable_start, window.unavailable_end)
            for conflict in Conflict.objects.filter(rehearsal_id=rehearsal_id, type=Conflict.PARTIAL)
            .prefetch_related('conflictwindow_set')
            for window in conflict.conflictwindow_set.all()
        ]
        for rehearsal_id in touched_ids
    }

    recordings_before = list(
        Recording.objects.filter(rehearsal_song__rehearsal_id__in=touched_ids)
        .select_related('rehearsal_song__song')
    )
    rehearsal_id_by_recording_id = {
        recording.pk: recording.rehearsal_song.rehearsal_id for recording in recordings_before
    }
    uploader_id_by_recording_id = {recording.pk: recording.uploaded_by_id for recording in recordings_before}
    recording_ids_by_rehearsal_song_id = defaultdict(set)
    for recording in recordings_before:
        recording_ids_by_rehearsal_song_id[recording.rehearsal_song_id].add(recording.pk)
    rehearsal_song_before_by_id = {
        rehearsal_song.pk: (rehearsal_song.start_time, rehearsal_song.end_time, rehearsal_song.song.title)
        for rehearsal_song in RehearsalSong.objects.filter(rehearsal_id__in=touched_ids).select_related('song')
    }

    apply_buffer = replace(buffer, semester_updated_at=current_semester.updated_at)
    try:
        apply_rehearsal_edits(apply_buffer, viewing_semester=viewing_semester)
    except (
        WrongViewingSemesterError, StaleRehearsalSemesterError,
        PastRehearsalEditError, RunningOrderValidationError,
    ) as error:
        return _blocked_rehearsal_fallout(str(error), is_stale=is_stale)

    surviving_recording_ids = frozenset(
        Recording.objects.filter(pk__in=rehearsal_id_by_recording_id).values_list('pk', flat=True)
    )
    destroyed_by_rehearsal_id = defaultdict(list)
    for recording_id, rehearsal_id in rehearsal_id_by_recording_id.items():
        if recording_id not in surviving_recording_ids:
            destroyed_by_rehearsal_id[rehearsal_id].append(recording_id)

    doomed_recording_groups = []
    loud = []
    for rehearsal_id, recording_ids in destroyed_by_rehearsal_id.items():
        rehearsal = rehearsals_before[rehearsal_id]
        uploader_count = len({uploader_id_by_recording_id[recording_id] for recording_id in recording_ids})
        count = len(recording_ids)
        doomed_recording_groups.append(DoomedRecordingGroup(
            label=str(rehearsal.date), recording_count=count, uploader_count=uploader_count,
        ))
        loud.append(f"{count} recording{'' if count == 1 else 's'} on {rehearsal.date} will be destroyed.")

    surviving_rehearsal_song_times = {
        pk: (start_time, end_time)
        for pk, start_time, end_time
        in RehearsalSong.objects.filter(pk__in=rehearsal_song_before_by_id).values_list('pk', 'start_time', 'end_time')
    }
    for rehearsal_song_id, (old_start, old_end, song_title) in rehearsal_song_before_by_id.items():
        new_times = surviving_rehearsal_song_times.get(rehearsal_song_id)
        if new_times is None or new_times == (old_start, old_end):
            continue
        recording_ids = recording_ids_by_rehearsal_song_id.get(rehearsal_song_id) or set()
        if not recording_ids:
            continue
        count = len(recording_ids)
        new_start, new_end = new_times
        loud.append(
            f"{count} recording{'' if count == 1 else 's'} on {song_title} "
            f"{'was' if count == 1 else 'were'} made against "
            f'{_format_slot(old_start, old_end)}, now {_format_slot(new_start, new_end)}.'
        )

    quiet = []
    surviving_rehearsals = Rehearsal.objects.filter(
        semester=current_semester, date__in={row.date for row in buffer.rows},
    )
    for rehearsal in surviving_rehearsals:
        songs, _, _ = _matrix_songs(rehearsal)
        assignment_loud, assignment_quiet = _assignment_fallout_lines(rehearsal, songs)
        loud.extend(assignment_loud)
        quiet.extend(assignment_quiet)

        if not rehearsal.is_full_setlist and not songs:
            quiet.append(f'{rehearsal.date} has no songs scheduled.')

        old_windows = conflicts_before.get(rehearsal.pk, [])
        if old_windows and (rehearsal.pk not in rehearsals_before or (
            rehearsals_before[rehearsal.pk].start_time != rehearsal.start_time
            or rehearsals_before[rehearsal.pk].end_time != rehearsal.end_time
        )):
            old_rehearsal = rehearsals_before.get(rehearsal.pk)
            if old_rehearsal is not None:
                for window_start, window_end in old_windows:
                    was_overlapping = _windows_overlap(
                        window_start, window_end, old_rehearsal.start_time, old_rehearsal.end_time,
                    )
                    still_overlapping = _windows_overlap(
                        window_start, window_end, rehearsal.start_time, rehearsal.end_time,
                    )
                    if was_overlapping and not still_overlapping:
                        quiet.append(
                            f"A declared Conflict Window no longer overlaps {rehearsal.date}'s rehearsal time "
                            'after this re-time.'
                        )

    return RehearsalEditFallout(
        is_blocked=False, block_message='', is_stale=is_stale,
        loud=loud, quiet=quiet, doomed_recording_groups=doomed_recording_groups,
    )


class StaleSemesterDefaultsError(ValueError):
    """Raised when a Semester's timing defaults changed since a reapply confirmation was opened (issue #291)."""


class SemesterDefaultsReapplyBlockedError(ValueError):
    """Raised when reapplying a Semester's current timing defaults would leave inconsistent data (issue #291).

    Covers several independent hazards a bulk reapply could otherwise
    create: the target Semester no longer existing; a default duration too
    short to leave any playable time once setup/teardown grace is
    subtracted; a Rehearsal's end_time wrapping past midnight; and
    `default_song_slot_count` having shrunk since a Rehearsal's songs were
    scheduled — reapplying never touches `slot_count`, so a row that used
    to fit can stop fitting, the same invariant `RehearsalSong.save()`
    already enforces via `_overruns_rehearsal_window()`. Raised before any
    commit so the whole bulk reapply writes nothing, rather than applying
    to some Rehearsals and stopping mid-batch at the first one that fails.
    """


@dataclass(frozen=True)
class SemesterDefaultsReapplyBuffer:
    """The Semester identity `apply_semester_defaults_reapply()`/`preview_semester_defaults_reapply()` share (issue #291).

    Carries no per-row data, unlike `RehearsalEditBuffer` — this bulk action
    reads its input straight off the Semester's already-persisted `default_*`
    fields and its existing Rehearsals. Addressed by `semester_id` alone,
    the way `SemesterPublishView`/`SemesterDeleteView` are — this action has
    no session-scoped Viewing Semester ambiguity to guard against, since its
    target is always the pk named in the URL. `semester_updated_at` backs
    the one staleness check that does apply: the Semester's defaults (or
    another admin's concurrent reapply) may have changed between this
    confirmation's GET and its POST.
    """

    semester_id: int
    semester_updated_at: datetime


def apply_semester_defaults_reapply(buffer: SemesterDefaultsReapplyBuffer) -> None:
    """Push a Semester's current timing defaults onto its non-past Rehearsals in one transaction (issue #291).

    `Rehearsal._apply_semester_defaults()` only fires at creation time, so
    editing a Semester's `default_*` fields afterward never reaches an
    already-created Rehearsal — this is the bulk push that does. For every
    Rehearsal dated today or later, overwrites `setup_grace_minutes`,
    `teardown_grace_minutes`, `arrival_buffer_minutes`, `departure_buffer_minutes`
    and `end_time` with the Semester's current defaults via
    `Rehearsal.overwrite_semester_defaults()`, then re-derives every
    surviving RehearsalSong's persisted slot by handing `reorder_rehearsal_songs()`
    its own current order — the same "identity permutation forces a
    re-derive" trick that Rehearsal window edits already rely on — since
    `default_song_slot_count` may also have changed. A past Rehearsal
    (`date < today`) is excluded outright, mirroring `apply_rehearsal_edits()`'s
    `PastRehearsalEditError` posture.

    Raises `StaleSemesterDefaultsError` inside the transaction if the
    Semester's `updated_at` no longer matches `buffer.semester_updated_at`.
    Raises `SemesterDefaultsReapplyBlockedError` — see its docstring — if
    the Semester no longer exists, its default duration leaves no playable
    time after setup/teardown grace, any Rehearsal's end_time would wrap
    past midnight, or any RehearsalSong would overrun the Semester's
    `default_song_slot_count`; any of these rolls back whatever this call
    had already applied. A declared Conflict Window that stops overlapping
    a re-timed Rehearsal is deliberately *not* one of these — see
    `preview_semester_defaults_reapply()`'s quiet Fallout tier, the same
    tolerance `apply_rehearsal_edits()` already gives a manual edit.
    """
    with transaction.atomic():
        try:
            semester = Semester.objects.select_for_update().get(pk=buffer.semester_id)
        except Semester.DoesNotExist as error:
            raise SemesterDefaultsReapplyBlockedError('This Semester no longer exists.') from error
        if semester.updated_at != buffer.semester_updated_at:
            raise StaleSemesterDefaultsError(
                "The Semester's defaults changed while this confirmation was open — reload and try again."
            )

        today = timezone.localdate()
        rehearsals = list(Rehearsal.objects.filter(semester=semester, date__gte=today).order_by('pk'))
        for rehearsal in rehearsals:
            try:
                rehearsal.overwrite_semester_defaults()
            except ValueError as error:
                raise SemesterDefaultsReapplyBlockedError(f'{rehearsal.date}: {error}') from error
            rehearsal.save()

        grace_total = timedelta(
            minutes=semester.default_setup_grace_minutes + semester.default_teardown_grace_minutes,
        )
        playable_duration = timedelta(minutes=semester.default_rehearsal_duration_minutes) - grace_total

        for rehearsal in rehearsals:
            ordered_ids = list(
                RehearsalSong.objects.filter(rehearsal=rehearsal).order_by('order').values_list('pk', flat=True)
            )
            if not ordered_ids:
                continue
            if playable_duration <= timedelta(0):
                raise SemesterDefaultsReapplyBlockedError(
                    f'{rehearsal.date}: the default duration leaves no playable time after setup/teardown grace.'
                )
            try:
                reorder_rehearsal_songs(rehearsal, ordered_ids)
            except ValueError as error:
                raise SemesterDefaultsReapplyBlockedError(f'{rehearsal.date}: {error}') from error

        semester.updated_at = timezone.now()
        semester.save(update_fields=['updated_at'])


@dataclass(frozen=True)
class SemesterDefaultsFallout:
    """Every observable consequence of reapplying a Semester's timing defaults, computed without committing it (issue #291, ADR-0008).

    `is_blocked` mirrors `apply_semester_defaults_reapply()`'s
    `SemesterDefaultsReapplyBlockedError` — see its docstring for every
    condition that raises it — with no Fallout computed at all. `is_stale`
    flags a `Semester.updated_at`
    mismatch, reported never refused, per ADR-0008. `changed_rehearsal_count`
    is how many upcoming Rehearsals this reapply would touch (0 renders as
    "nothing to reapply" rather than a block). `loud`/`quiet` are the two
    ADR-0002 tiers: a Recording whose RehearsalSong slot moved is loud (its
    performers should know their recorded slot re-timed); a declared
    Conflict Window that no longer overlaps its Rehearsal after the re-time
    is quiet (an inert notification, never a call to act).
    """

    is_blocked: bool
    block_message: str
    is_stale: bool
    changed_rehearsal_count: int
    loud: list[str]
    quiet: list[str]


def _blocked_semester_defaults_fallout(block_message: str, *, is_stale: bool = False) -> SemesterDefaultsFallout:
    """Return a SemesterDefaultsFallout reporting a hard block, with every Fallout list empty."""
    return SemesterDefaultsFallout(
        is_blocked=True, block_message=block_message, is_stale=is_stale,
        changed_rehearsal_count=0, loud=[], quiet=[],
    )


def preview_semester_defaults_reapply(buffer: SemesterDefaultsReapplyBuffer) -> SemesterDefaultsFallout:
    """Run the real `apply_semester_defaults_reapply()` for `buffer` and report every observable consequence (issue #291, ADR-0008).

    This function's write is real — it must be called inside a transaction
    the *caller* rolls back, exactly like `preview_rehearsal_edits()`.
    Called outside such a transaction, this function corrupts the database.

    Snapshots every upcoming Rehearsal's declared Conflict Windows and each
    of its RehearsalSong's persisted slot before calling
    `apply_semester_defaults_reapply()` (with a copy of `buffer` whose
    `semester_updated_at` is swapped for the Semester's current value, so
    the real function's own staleness check always passes and the write
    actually runs), then re-reads the same state after and diffs the two:
    a RehearsalSong carrying a Recording whose slot moved is a loud
    re-timed-Recording line; a Conflict Window that used to overlap its
    Rehearsal's window and no longer does is a quiet line. A
    `StaleSemesterDefaultsError` or `SemesterDefaultsReapplyBlockedError`
    from `apply_semester_defaults_reapply()` is reported as `is_blocked`
    with no Fallout computed at all, rather than re-implementing either
    check here.
    """
    current_semester = Semester.objects.filter(pk=buffer.semester_id).first()
    if current_semester is None:
        return _blocked_semester_defaults_fallout('This Semester no longer exists.')
    is_stale = buffer.semester_updated_at != current_semester.updated_at

    today = timezone.localdate()
    touched_ids = list(
        Rehearsal.objects.filter(semester=current_semester, date__gte=today).values_list('pk', flat=True)
    )
    conflicts_before = {
        rehearsal_id: [
            (window.unavailable_start, window.unavailable_end)
            for conflict in Conflict.objects.filter(rehearsal_id=rehearsal_id, type=Conflict.PARTIAL)
            .prefetch_related('conflictwindow_set')
            for window in conflict.conflictwindow_set.all()
        ]
        for rehearsal_id in touched_ids
    }
    rehearsals_before = {rehearsal.pk: rehearsal for rehearsal in Rehearsal.objects.filter(pk__in=touched_ids)}

    recordings_before = list(
        Recording.objects.filter(rehearsal_song__rehearsal_id__in=touched_ids)
        .select_related('rehearsal_song__song')
    )
    recording_ids_by_rehearsal_song_id = defaultdict(set)
    for recording in recordings_before:
        recording_ids_by_rehearsal_song_id[recording.rehearsal_song_id].add(recording.pk)
    rehearsal_song_before_by_id = {
        rehearsal_song.pk: (rehearsal_song.start_time, rehearsal_song.end_time, rehearsal_song.song.title)
        for rehearsal_song in RehearsalSong.objects.filter(rehearsal_id__in=touched_ids).select_related('song')
    }

    apply_buffer = replace(buffer, semester_updated_at=current_semester.updated_at)
    try:
        apply_semester_defaults_reapply(apply_buffer)
    except (StaleSemesterDefaultsError, SemesterDefaultsReapplyBlockedError) as error:
        return _blocked_semester_defaults_fallout(str(error), is_stale=is_stale)

    loud = []
    surviving_rehearsal_song_times = {
        pk: (start_time, end_time)
        for pk, start_time, end_time
        in RehearsalSong.objects.filter(pk__in=rehearsal_song_before_by_id).values_list('pk', 'start_time', 'end_time')
    }
    for rehearsal_song_id, (old_start, old_end, song_title) in rehearsal_song_before_by_id.items():
        new_times = surviving_rehearsal_song_times.get(rehearsal_song_id)
        if new_times is None or new_times == (old_start, old_end):
            continue
        recording_ids = recording_ids_by_rehearsal_song_id.get(rehearsal_song_id) or set()
        if not recording_ids:
            continue
        count = len(recording_ids)
        new_start, new_end = new_times
        loud.append(
            f"{count} recording{'' if count == 1 else 's'} on {song_title} "
            f"{'was' if count == 1 else 'were'} made against "
            f'{_format_slot(old_start, old_end)}, now {_format_slot(new_start, new_end)}.'
        )

    quiet = []
    for rehearsal in Rehearsal.objects.filter(pk__in=touched_ids):
        old_rehearsal = rehearsals_before.get(rehearsal.pk)
        if old_rehearsal is None:
            continue
        old_windows = conflicts_before.get(rehearsal.pk, [])
        if not old_windows:
            continue
        if old_rehearsal.start_time == rehearsal.start_time and old_rehearsal.end_time == rehearsal.end_time:
            continue
        for window_start, window_end in old_windows:
            was_overlapping = _windows_overlap(
                window_start, window_end, old_rehearsal.start_time, old_rehearsal.end_time,
            )
            still_overlapping = _windows_overlap(
                window_start, window_end, rehearsal.start_time, rehearsal.end_time,
            )
            if was_overlapping and not still_overlapping:
                quiet.append(
                    f"A declared Conflict Window no longer overlaps {rehearsal.date}'s rehearsal time "
                    'after this reapply.'
                )

    return SemesterDefaultsFallout(
        is_blocked=False, block_message='', is_stale=is_stale,
        changed_rehearsal_count=len(touched_ids), loud=loud, quiet=quiet,
    )


@dataclass(frozen=True)
class RehearsalTimeInput:
    """One Rehearsal Time row as entered in the Pattern editor (issue #222): a day-of-week plus start/end."""

    day_of_week: int
    start_time: time
    end_time: time


@dataclass(frozen=True)
class SkipDateInput:
    """One Skip Date row as entered in the Pattern editor (issue #222): a single date, or an inclusive range."""

    start_date: date
    end_date: date | None


@dataclass(frozen=True)
class RehearsalPatternInput:
    """A whole Rehearsal Pattern as entered in the Pattern editor (issue #222), before or instead of being saved.

    Mirrors `RehearsalPattern`/`RehearsalTime`/`SkipDate` field-for-field as
    plain dataclasses rather than model instances, so `preview_rehearsal_generation()`
    can diff a Pattern the admin is still editing and hasn't saved yet —
    per CONTEXT.md, "editing a Pattern changes nothing until it is used to
    generate," and a Preview must not force a save first to be explorable.
    """

    start_date: date
    end_date: date
    rehearsal_times: list[RehearsalTimeInput] = field(default_factory=list)
    skip_dates: list[SkipDateInput] = field(default_factory=list)


class RehearsalPatternCollisionError(ValueError):
    """Raised when two Rehearsal Times in a Pattern share a day-of-week (issue #222).

    Two Rehearsal Times on the same day of the week would both try to
    generate a Rehearsal onto the very same date, which can never coexist
    under `unique_rehearsal_date_per_semester` — so this is a Pattern-level
    error, raised by `save_rehearsal_pattern()` before anything is written,
    rather than left to surface obliquely as a generation-time collision.
    """


def _rehearsal_time_collision_message(day_of_week: int) -> str:
    """Name which day-of-week two Rehearsal Times collide on, for `RehearsalPatternCollisionError`."""
    day_name = dict(RehearsalTime.DAY_OF_WEEK_CHOICES).get(day_of_week, day_of_week)
    return f'Two Rehearsal Times are both set for {day_name} — they would collide on the same generated date.'


def _check_no_rehearsal_time_collisions(rehearsal_times: list[RehearsalTimeInput]) -> None:
    """Raise `RehearsalPatternCollisionError` if two `rehearsal_times` share a `day_of_week` (issue #222).

    Shared by `save_rehearsal_pattern()` and `preview_rehearsal_generation()`
    so the same Pattern-level error is caught the same way regardless of
    which one runs first — the acceptance criterion is "caught before
    generation runs", not "caught only on save".
    """
    seen_days = set()
    for rehearsal_time in rehearsal_times:
        if rehearsal_time.day_of_week in seen_days:
            raise RehearsalPatternCollisionError(_rehearsal_time_collision_message(rehearsal_time.day_of_week))
        seen_days.add(rehearsal_time.day_of_week)


def save_rehearsal_pattern(semester: Semester, pattern: RehearsalPatternInput) -> RehearsalPattern:
    """Persist `pattern` as `semester`'s one RehearsalPattern, replacing its Rehearsal Times and Skip Dates wholesale (issue #222).

    Writes no Rehearsal — this is input history with no downstream
    authority (CONTEXT.md's "Rehearsal Pattern"); only a Pattern's diff,
    once hand-applied into the Pending Buffer and saved through
    `apply_rehearsal_edits()`, ever creates one. Raises
    `RehearsalPatternCollisionError` before any write if two
    `rehearsal_times` share a `day_of_week` — both would generate onto the
    same date, which can never coexist under
    `unique_rehearsal_date_per_semester`. Replaces the Pattern's Rehearsal
    Times and Skip Dates wholesale (delete then recreate) rather than
    diffing row by row: neither carries any other referent, so there is
    nothing an in-place edit would preserve that a replace loses.
    """
    _check_no_rehearsal_time_collisions(pattern.rehearsal_times)

    with transaction.atomic():
        db_pattern, _ = RehearsalPattern.objects.get_or_create(
            semester=semester, defaults={'start_date': pattern.start_date, 'end_date': pattern.end_date},
        )
        db_pattern.start_date = pattern.start_date
        db_pattern.end_date = pattern.end_date
        db_pattern.save()
        RehearsalTime.objects.filter(pattern=db_pattern).delete()
        SkipDate.objects.filter(pattern=db_pattern).delete()
        for rehearsal_time in pattern.rehearsal_times:
            RehearsalTime.objects.create(
                pattern=db_pattern,
                day_of_week=rehearsal_time.day_of_week,
                start_time=rehearsal_time.start_time,
                end_time=rehearsal_time.end_time,
            )
        for skip_date in pattern.skip_dates:
            SkipDate.objects.create(
                pattern=db_pattern, start_date=skip_date.start_date, end_date=skip_date.end_date,
            )
    return db_pattern


@dataclass(frozen=True)
class PriorRehearsalTimesProposal:
    """The prior Semester's Rehearsal Times, offered as an opt-in prefill for the setup wizard's Pattern step (issue #203).

    Only Rehearsal Times are proposed — the prior Pattern's generation
    range and Skip Dates are deliberately excluded, since both are
    calendar-specific to that term and copying them would plant last
    year's spring break into this one. `source_semester` is None when
    there is nothing to offer (no prior Semester, or one with no saved
    Rehearsal Times), in which case `rehearsal_times` is empty.
    """

    source_semester: Semester | None
    rehearsal_times: list[RehearsalTimeInput]


def prior_rehearsal_times_for(semester: Semester) -> PriorRehearsalTimesProposal:
    """Propose `semester`'s prior Semester's Rehearsal Times as an opt-in wizard prefill (issue #203).

    A read, not a write: nothing here is saved, mirroring
    `import_roster_from_semester()`'s shape for the same wizard.
    """
    source = _prior_semester(semester)
    if source is not None:
        prior_pattern = RehearsalPattern.objects.filter(semester=source).prefetch_related('rehearsal_times').first()
        if prior_pattern is not None and prior_pattern.rehearsal_times.exists():
            rehearsal_times = [
                RehearsalTimeInput(
                    day_of_week=rehearsal_time.day_of_week,
                    start_time=rehearsal_time.start_time,
                    end_time=rehearsal_time.end_time,
                )
                for rehearsal_time in prior_pattern.rehearsal_times.all()
            ]
            return PriorRehearsalTimesProposal(source_semester=source, rehearsal_times=rehearsal_times)
    return PriorRehearsalTimesProposal(source_semester=None, rehearsal_times=[])


@dataclass(frozen=True)
class GenerationCreateItem:
    """One date the Pattern would generate a brand-new Rehearsal for (issue #222)."""

    date: date
    start_time: time
    end_time: time
    is_dress_rehearsal: bool


@dataclass(frozen=True)
class GenerationKeepItem:
    """One date whose existing Rehearsal already matches the Pattern exactly — a re-run's no-op case (issue #222)."""

    rehearsal_id: int
    date: date
    start_time: time
    end_time: time


@dataclass(frozen=True)
class GenerationRetimeItem:
    """One date whose existing Rehearsal's hours would change (issue #222). Opt-in; unchecked by default.

    `song_count`/`conflict_count` are this outcome's blast radius — how
    many scheduled songs and how many members' Conflicts the evening
    currently carries — surfaced so an admin can judge the mechanical cost
    (`reorder_rehearsal_songs()` re-deriving every song's persisted slot)
    before opting in. Conflicts are never shifted or deleted by a re-time
    (a Conflict Window is a member's statement about real life, not an
    offset into the rehearsal); the count here is informational only.
    """

    rehearsal_id: int
    date: date
    old_start_time: time
    old_end_time: time
    new_start_time: time
    new_end_time: time
    song_count: int
    conflict_count: int


@dataclass(frozen=True)
class GenerationOrphanItem:
    """One existing Rehearsal the Pattern no longer produces (issue #222). Never auto-deleted; unchecked by default.

    `recording_count` gates the outcome's delete checkbox
    (`delete_disabled`): the generator is blind and bulk, so — unlike the
    manual per-row delete `delete_rehearsals_with_recordings()` allows
    behind the destructive-save dialog — it refuses to offer deleting an
    orphan that carries at least one Recording at all. That asymmetry is
    intentional (see the mirrored comment on `delete_rehearsals_with_recordings()`).
    """

    rehearsal_id: int
    date: date
    start_time: time
    end_time: time
    song_count: int
    conflict_count: int
    recording_count: int

    @property
    def delete_disabled(self) -> bool:
        """True when this orphan carries at least one Recording — its delete checkbox must stay unavailable."""
        return self.recording_count > 0


@dataclass(frozen=True)
class RehearsalGenerationDiff:
    """The four-bucket diff `preview_rehearsal_generation()` computes: Create, Keep, Re-time, Orphaned (issue #222)."""

    creates: list[GenerationCreateItem]
    keeps: list[GenerationKeepItem]
    retimes: list[GenerationRetimeItem]
    orphans: list[GenerationOrphanItem]


def _generated_dates(pattern: RehearsalPatternInput, start_date: date, end_date: date):
    """Yield (date, RehearsalTimeInput) for every date in the inclusive [start_date, end_date] range whose weekday matches a Rehearsal Time, minus Skip Dates.

    Assumes `pattern.rehearsal_times` carries no two entries sharing a
    `day_of_week` — `save_rehearsal_pattern()`'s collision check already
    guarantees that for a persisted Pattern; a Pattern still being edited
    in the modal and not yet saved is validated by the same check before
    this function is ever reached (issue #222).
    """
    time_by_day = {rehearsal_time.day_of_week: rehearsal_time for rehearsal_time in pattern.rehearsal_times}
    skipped_dates = set()
    for skip_date in pattern.skip_dates:
        skip_end = skip_date.end_date or skip_date.start_date
        current = skip_date.start_date
        while current <= skip_end:
            skipped_dates.add(current)
            current += timedelta(days=1)

    current = start_date
    while current <= end_date:
        rehearsal_time = time_by_day.get(current.weekday())
        if rehearsal_time is not None and current not in skipped_dates:
            yield current, rehearsal_time
        current += timedelta(days=1)


def preview_rehearsal_generation(
    semester: Semester, pattern: RehearsalPatternInput, date_range: tuple[date, date] | None = None,
) -> RehearsalGenerationDiff:
    """Compute the four-bucket diff generating `pattern` against `semester`'s current Rehearsals would produce (issue #222).

    A pure read — writes nothing at all, unlike every other `preview_*()`
    in this module: ADR-0008's run-and-rollback pattern doesn't apply here,
    since there is no `apply_rehearsal_generation` to run (#127 decided the
    diff is a staging modal, not a second buffer — see `RehearsalGenerationDiff`'s
    docstring). `date_range`, when given, narrows the generation range for
    this one run without touching `pattern` itself (CONTEXT.md's Rehearsal
    Pattern: "the range can be narrowed for a single run without changing
    the stored Pattern") — callers pass the admin's typed override; the
    Pattern's own `(start_date, end_date)` is used otherwise.

    Every date the Pattern would produce (`_generated_dates()`) becomes a
    Create, a Keep or a Re-time depending on whether `semester` already has
    a Rehearsal on that date and whether its hours already match. The last
    `semester.default_dress_rehearsal_count` produced dates (across every
    bucket, not just Create) are candidates for the Dress flag, but it is
    only ever attached to a brand-new Create row — a re-run never migrates
    an existing Rehearsal's flag onto or off of it (CONTEXT.md: a Pattern
    "records what was asked for, not what exists"). Every existing
    Rehearsal dated within the run's range that the Pattern does not
    produce is an Orphan — listed, never deleted here or by the diff's
    consumer directly; deletion, like every other outcome, happens only
    once its Buffer entry is saved through `apply_rehearsal_edits()`.

    The first-ever run on a Semester with no Rehearsals goes through this
    exact same code path: `existing` is simply empty, so every produced
    date lands in `creates` and neither `retimes` nor `orphans` has
    anything to report.
    """
    _check_no_rehearsal_time_collisions(pattern.rehearsal_times)
    start_date, end_date = date_range if date_range is not None else (pattern.start_date, pattern.end_date)
    # A past-dated Create would enter the Pending Buffer checked and immediately trip
    # PastRehearsalEditError on save; a past Re-time/Orphan would render but its row is
    # excluded from ScheduleEditView's editable set, so its injection could never find a
    # match. Clamping here keeps every bucket confined to dates apply_rehearsal_edits()
    # can actually act on.
    start_date = max(start_date, timezone.localdate())
    generated = list(_generated_dates(pattern, start_date, end_date)) if start_date <= end_date else []
    generated_dates = [generated_date for generated_date, _ in generated]
    dress_dates = (
        set(generated_dates[-semester.default_dress_rehearsal_count:])
        if semester.default_dress_rehearsal_count
        else set()
    )

    existing_by_date = {
        rehearsal.date: rehearsal
        for rehearsal in Rehearsal.objects.filter(semester=semester, date__range=(start_date, end_date))
    }
    existing_ids = [rehearsal.pk for rehearsal in existing_by_date.values()]
    song_counts = dict(
        RehearsalSong.objects.filter(rehearsal_id__in=existing_ids)
        .values('rehearsal_id').annotate(count=Count('pk')).values_list('rehearsal_id', 'count')
    )
    conflict_counts = dict(
        Conflict.objects.filter(rehearsal_id__in=existing_ids)
        .values('rehearsal_id').annotate(count=Count('pk')).values_list('rehearsal_id', 'count')
    )
    recording_counts = dict(
        Recording.objects.filter(rehearsal_song__rehearsal_id__in=existing_ids)
        .values('rehearsal_song__rehearsal_id').annotate(count=Count('pk'))
        .values_list('rehearsal_song__rehearsal_id', 'count')
    )

    creates: list[GenerationCreateItem] = []
    keeps: list[GenerationKeepItem] = []
    retimes: list[GenerationRetimeItem] = []
    produced_dates = set()
    for generated_date, rehearsal_time in generated:
        produced_dates.add(generated_date)
        rehearsal = existing_by_date.get(generated_date)
        if rehearsal is None:
            creates.append(GenerationCreateItem(
                date=generated_date, start_time=rehearsal_time.start_time, end_time=rehearsal_time.end_time,
                is_dress_rehearsal=generated_date in dress_dates,
            ))
        elif rehearsal.start_time == rehearsal_time.start_time and rehearsal.end_time == rehearsal_time.end_time:
            keeps.append(GenerationKeepItem(
                rehearsal_id=rehearsal.pk, date=generated_date,
                start_time=rehearsal.start_time, end_time=rehearsal.end_time,
            ))
        else:
            retimes.append(GenerationRetimeItem(
                rehearsal_id=rehearsal.pk, date=generated_date,
                old_start_time=rehearsal.start_time, old_end_time=rehearsal.end_time,
                new_start_time=rehearsal_time.start_time, new_end_time=rehearsal_time.end_time,
                song_count=song_counts.get(rehearsal.pk, 0), conflict_count=conflict_counts.get(rehearsal.pk, 0),
            ))

    orphans = sorted(
        (
            GenerationOrphanItem(
                rehearsal_id=rehearsal.pk, date=rehearsal_date,
                start_time=rehearsal.start_time, end_time=rehearsal.end_time,
                song_count=song_counts.get(rehearsal.pk, 0), conflict_count=conflict_counts.get(rehearsal.pk, 0),
                recording_count=recording_counts.get(rehearsal.pk, 0),
            )
            for rehearsal_date, rehearsal in existing_by_date.items()
            if rehearsal_date not in produced_dates
        ),
        key=lambda orphan: orphan.date,
    )

    return RehearsalGenerationDiff(creates=creates, keeps=keeps, retimes=retimes, orphans=orphans)


@dataclass(frozen=True)
class DealtRow:
    """One Running Order sub-grid row `deal_running_orders()`/`shuffle_rehearsal_running_order()` propose (issue #223).

    `rehearsal_song_id` is non-None exactly for an existing Recording-bearing
    row the deal/shuffle leaves untouched at its own identity and
    `slot_count` — everything else is a freshly dealt Song at `slot_count=1`
    (a shuffle's non-pinned rows are also real RehearsalSong rows, but their
    identity travels here too since a shuffle never creates or destroys a
    row, only reorders existing ones). Mirrors `RunningOrderRow`'s shape
    deliberately, so a caller can hand this straight to the Pending Buffer.
    """

    rehearsal_song_id: int | None
    song_id: int
    slot_count: int


@dataclass(frozen=True)
class DealtRehearsal:
    """One Rehearsal's proposed Running Order rows, in final target order (issue #223)."""

    rehearsal_id: int
    rows: list[DealtRow]


@dataclass(frozen=True)
class RehearsalDeal:
    """The whole proposed deal `deal_running_orders()` computes across every eligible Rehearsal (issue #223).

    A pure read — writes nothing at all, same posture as
    `preview_rehearsal_generation()`. There is no `apply_schedule_generation`:
    #128 proposed one, then in the same resolution ruled that its output
    simply fills the Rehearsal editor's existing Pending Buffer with no
    consent step of its own — the only writer this Running Order ever
    reaches is `apply_rehearsal_edits()`. Unlike the date generator's
    Pattern, nothing here is persisted between runs: a deal's inputs (the
    setlist, the eligible Rehearsals, which rows are Recording-pinned) all
    already live in the database, so there is nothing a "Deal Pattern"
    would remember that isn't re-derivable from a fresh run, and no seed is
    kept either — the undo for a deal an admin dislikes is simply re-rolling
    before Save, never an un-audit-able "was this generated" flag.
    """

    rehearsals: list[DealtRehearsal]


class EmptySetlistError(ValueError):
    """Raised by `deal_running_orders()` when the Semester's setlist has no Songs to deal (issue #223)."""


class NoEligibleRehearsalsError(ValueError):
    """Raised by `deal_running_orders()` when the Semester has no non-Dress, non-past Rehearsal to deal into (issue #223)."""


class DealInfeasibleError(ValueError):
    """Raised by `deal_running_orders()`/`shuffle_rehearsal_running_order()` when the pinned rows themselves make a valid deal impossible (issue #223 review fix).

    Two distinct causes share this one error, since both mean the same
    thing to a caller: "don't propose this, the pins already broke it".
    Either a pinned row's own `order` no longer fits within the rehearsal's
    current row count (the setlist or the Semester's `default_song_slot_count`
    shrank since it was pinned, so honoring both "leave it at its own order"
    and "never exceed the slot budget" is impossible at once), or the pinned
    rows alone already spread a Song's term-wide appearance count more than
    one away from another's, with no remaining free slot anywhere left to
    close the gap. Silently relocating the row (the first case) or silently
    returning an unbalanced deal (the second) would both violate this
    function's contract more than refusing does.
    """


def _eligible_rehearsals_for_deal(semester: Semester) -> list[Rehearsal]:
    """Return `semester`'s non-Dress Rehearsals dated today or later, in schedule order (issue #223).

    Shared boundary with `ScheduleEditView`'s own editable queryset (minus
    the Dress exclusion, which that grid renders but never deals into) —
    the dealer must never touch a Dress Rehearsal (ADR-0003 forbids the
    rows outright) or a past one (generation cannot rewrite history).
    """
    today = timezone.localdate()
    return list(
        Rehearsal.objects.filter(semester=semester, is_full_setlist=False, date__gte=today)
        .order_by('date', 'start_time')
    )


def _pinned_rows_by_rehearsal(rehearsals: list[Rehearsal]) -> dict[int, list[RehearsalSong]]:
    """Return `{rehearsal_id: [RehearsalSong, ...]}` for every row across `rehearsals` the dealer must leave alone (issue #223).

    Two independent reasons pin a row: it carries at least one Recording
    (so a bulk run can never invalidate an upload's timing), or its
    `slot_count` has been hand-raised above the dealt default of 1 (a
    dealt row is *always* `slot_count=1`, so any row that isn't is
    necessarily a deliberate admin edit — "the generator never raises and
    never clobbers" it, per this issue's spec). Either way, "the manual
    path deliberately allows what the generator refuses" — an admin can
    still delete, move or re-slot this exact row by hand through the
    Running Order sub-grid; only the dealer treats it as untouchable.
    """
    by_rehearsal = defaultdict(list)
    rehearsal_songs = (
        RehearsalSong.objects.filter(rehearsal__in=rehearsals)
        .filter(Q(recording__isnull=False) | Q(slot_count__gt=1))
        .distinct().order_by('rehearsal_id', 'order')
    )
    for rehearsal_song in rehearsal_songs:
        by_rehearsal[rehearsal_song.rehearsal_id].append(rehearsal_song)
    return by_rehearsal


def _pin_and_fill(
    total: int, pinned: list[tuple[int, DealtRow]], free: list[DealtRow], rng: random.Random,
) -> list[DealtRow]:
    """Return a length-`total` list of `DealtRow`s: each `pinned` row parked at its own current order, `free` rows filling every remaining position in random order (issue #223).

    Shared by `deal_running_orders()` (whose `free` rows are freshly dealt
    Songs) and `shuffle_rehearsal_running_order()` (whose `free` rows are
    the Rehearsal's own existing non-pinned rows) — the "hold pinned rows
    fixed, randomize the rest" shape is identical either way. `pinned`'s
    `order` is 1-indexed and must already fall within `[1, total]`: a
    pinned row's `order` can only exceed `total` if the setlist or the
    Semester's slot budget shrank since it was placed, and relocating it to
    fit would be exactly the "moves a pinned row" this function exists to
    never do — so that case raises `DealInfeasibleError` rather than
    silently clamping the index. A same-target collision (two pinned rows
    landing on the same index) probes forward to the next free slot rather
    than raising, since that's a genuine tie the caller can always discard
    by not saving, not a forced relocation.
    """
    slots: list[DealtRow | None] = [None] * total
    for order, row in sorted(pinned, key=lambda pair: pair[0]):
        if order > total:
            raise DealInfeasibleError(
                'A pinned Running Order row no longer fits within its Rehearsal — the setlist or slot budget '
                'shrank since it was placed. Resolve this by hand before dealing or shuffling again.'
            )
        index = order - 1
        while slots[index] is not None:
            index = (index + 1) % total
        slots[index] = row
    shuffled_free = list(free)
    rng.shuffle(shuffled_free)
    free_iter = iter(shuffled_free)
    return [slot if slot is not None else next(free_iter) for slot in slots]


def deal_running_orders(semester: Semester) -> RehearsalDeal:
    """Propose a balanced, randomized Running Order for every eligible Rehearsal in `semester`, writing nothing (issue #223).

    A read, not a write — `RehearsalDeal`'s docstring explains why there is
    no `apply_schedule_generation`. Deals the setlist across every eligible
    Rehearsal (`_eligible_rehearsals_for_deal()`: non-Dress, dated today or
    later) via a greedy round-robin: repeatedly, for each still-unfilled
    slot (in random order across the whole term, so no one Rehearsal is
    systematically favored), pick uniformly at random among whichever
    Song(s) currently have the *fewest* total appearances across the term
    and aren't already dealt into that particular slot's Rehearsal. This
    keeps every Song's final appearance count within one of every other's
    (a classic property of greedy-least-used selection) while still
    randomizing which Song lands where. A pinned row (Recording-bearing, or
    hand-raised above `slot_count=1` — `_pinned_rows_by_rehearsal()`'s
    docstring explains why both count) is never a candidate for this greedy
    fill at all — it's excluded up front, counted toward its Song's running
    total from the start (so the balance target already accounts for it),
    and `_pin_and_fill()` parks it back at its own current order afterward,
    so "the deal fills around it" rather than through it.

    Each Rehearsal's target song count is `min(remaining_slots, available_songs)`
    where `remaining_slots` is the Semester's `default_song_slot_count` minus
    however many slots its pinned rows already consume, and `available_songs`
    excludes Songs already pinned into that same Rehearsal — so a dealt row
    is always `slot_count=1` and a Rehearsal never receives a Song twice. A
    setlist smaller than the slot budget simply deals fewer rows, leaving
    the rest empty (no row ever repeats a Song to pad it out).

    Raises `EmptySetlistError` if `semester` has no Songs,
    `NoEligibleRehearsalsError` if it has no eligible Rehearsal (a silent
    no-op would read as a bug, per this issue's spec), and
    `DealInfeasibleError` if the pinned rows alone already spread some
    Song's term-wide count more than one away from another's with no free
    slot left anywhere to close the gap — the greedy fill above can only
    ever narrow that gap, never widen it, so this can only be detected
    after the fact, not prevented by the fill itself.
    """
    rehearsals = _eligible_rehearsals_for_deal(semester)
    songs = list(Song.objects.filter(semester=semester))
    if not songs:
        raise EmptySetlistError("This Semester's setlist has no Songs to deal.")
    if not rehearsals:
        raise NoEligibleRehearsalsError('This Semester has no eligible Rehearsal to deal a Running Order into.')

    song_ids = [song.pk for song in songs]
    pinned_by_rehearsal = _pinned_rows_by_rehearsal(rehearsals)

    counts: dict[int, int] = defaultdict(int)
    for pinned_rows in pinned_by_rehearsal.values():
        for rehearsal_song in pinned_rows:
            counts[rehearsal_song.song_id] += 1

    used_in_rehearsal: dict[int, set[int]] = {
        rehearsal.pk: {row.song_id for row in pinned_by_rehearsal.get(rehearsal.pk, [])} for rehearsal in rehearsals
    }
    capacity_by_rehearsal: dict[int, int] = {}
    for rehearsal in rehearsals:
        pinned_rows = pinned_by_rehearsal.get(rehearsal.pk, [])
        remaining_slots = max(0, semester.default_song_slot_count - sum(row.slot_count for row in pinned_rows))
        available_songs = len(song_ids) - len(used_in_rehearsal[rehearsal.pk])
        capacity_by_rehearsal[rehearsal.pk] = max(0, min(remaining_slots, available_songs))

    rng = random.Random()
    pending_slots = [
        rehearsal.pk for rehearsal in rehearsals for _ in range(capacity_by_rehearsal[rehearsal.pk])
    ]
    rng.shuffle(pending_slots)

    dealt_song_ids: dict[int, list[int]] = defaultdict(list)
    for rehearsal_id in pending_slots:
        available = [song_id for song_id in song_ids if song_id not in used_in_rehearsal[rehearsal_id]]
        min_count = min(counts[song_id] for song_id in available)
        chosen = rng.choice([song_id for song_id in available if counts[song_id] == min_count])
        dealt_song_ids[rehearsal_id].append(chosen)
        used_in_rehearsal[rehearsal_id].add(chosen)
        counts[chosen] += 1

    final_counts = [counts[song_id] for song_id in song_ids]
    if max(final_counts) - min(final_counts) > 1:
        raise DealInfeasibleError(
            "The pinned rows already spread some Song's appearance count more than one away from another's, "
            'with no free slot left to close the gap. Resolve this by hand before dealing again.'
        )

    dealt_rehearsals = []
    for rehearsal in rehearsals:
        pinned_rows = pinned_by_rehearsal.get(rehearsal.pk, [])
        pinned = [
            (rehearsal_song.order, DealtRow(
                rehearsal_song_id=rehearsal_song.pk, song_id=rehearsal_song.song_id, slot_count=rehearsal_song.slot_count,
            ))
            for rehearsal_song in pinned_rows
        ]
        free = [DealtRow(rehearsal_song_id=None, song_id=song_id, slot_count=1) for song_id in dealt_song_ids[rehearsal.pk]]
        total = len(pinned) + len(free)
        rows = _pin_and_fill(total, pinned, free, rng) if total else []
        dealt_rehearsals.append(DealtRehearsal(rehearsal_id=rehearsal.pk, rows=rows))

    return RehearsalDeal(rehearsals=dealt_rehearsals)


def shuffle_rehearsal_running_order(rehearsal: Rehearsal) -> list[DealtRow]:
    """Propose a random reordering of `rehearsal`'s existing Running Order, writing nothing (issue #223).

    The single-Rehearsal sibling of `deal_running_orders()`, sharing its
    "hold pinned rows fixed, randomize the rest" shape via `_pin_and_fill()`
    — the difference is every row here is already a real, saved
    `RehearsalSong`, so nothing is added or removed: this reorders the
    Rehearsal's *own already-dealt Songs* rather than redealing the term,
    which is exactly why calling it can never unbalance the ±1 spread
    `deal_running_orders()` established. Returns `[]` for a Rehearsal with
    no Running Order rows at all — a no-op, not a refusal, since there is
    nothing to shuffle and nothing an admin could be trying to fix. A row
    is pinned (held at its current order, never moved) for the same two
    reasons `_pinned_rows_by_rehearsal()` names: it carries a Recording, or
    its `slot_count` was hand-raised above 1.
    """
    rehearsal_songs = list(RehearsalSong.objects.filter(rehearsal=rehearsal).order_by('order'))
    if not rehearsal_songs:
        return []

    pinned_ids = frozenset(
        RehearsalSong.objects.filter(rehearsal=rehearsal)
        .filter(Q(recording__isnull=False) | Q(slot_count__gt=1))
        .distinct().values_list('pk', flat=True)
    )
    pinned = []
    free = []
    for rehearsal_song in rehearsal_songs:
        row = DealtRow(
            rehearsal_song_id=rehearsal_song.pk, song_id=rehearsal_song.song_id, slot_count=rehearsal_song.slot_count,
        )
        if rehearsal_song.pk in pinned_ids:
            pinned.append((rehearsal_song.order, row))
        else:
            free.append(row)

    return _pin_and_fill(len(rehearsal_songs), pinned, free, random.Random())
