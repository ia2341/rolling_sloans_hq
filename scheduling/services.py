"""Application services for the scheduling domain."""

import logging
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from itertools import pairwise
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from django.core.files.storage import storages
from django.db import IntegrityError, models, transaction
from django.db.models import Count, Q
from django.utils import timezone

from identity.models import Person
from scheduling.models import (
    Conflict,
    ConflictWindow,
    Membership,
    MembershipRole,
    Recording,
    Rehearsal,
    RehearsalSong,
    Role,
    Semester,
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
    """One entry in the admin's Semester dropdown: a Semester, its Live/Draft/Previously-published label, and whether it's the one on screen."""

    semester: Semester
    status: str
    is_viewing: bool


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
    return [
        SemesterOption(
            semester=semester,
            status=_semester_status(semester, live),
            is_viewing=viewing is not None and semester.pk == viewing.pk,
        )
        for semester in Semester.objects.order_by('-created_at', '-id')
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
    """The kinds of thing an AssignmentMatrixEntry can wrap (issue #208).

    Only ASSIGNMENT exists today; a later ticket (ADR-0007's Backup) adds a
    second kind to the same shape rather than a parallel list on the cell.
    """

    ASSIGNMENT = 'assignment'


@dataclass(frozen=True)
class AssignmentMatrixEntry:
    """One chip in an assignment matrix cell: a Person plus what kind of thing put them there (issue #208).

    `id` is a stable identity for the underlying row (e.g. a
    SongRoleAssignment's pk) that an edit-mode chip can buffer removals
    against; it is not necessarily unique across kinds.
    """

    id: int
    kind: str
    person: Person
    is_role_mismatch: bool


@dataclass(frozen=True)
class AssignmentMatrixCell:
    """One (Song, Role) cell in an assignment matrix: its ordered chip entries (issue #95, #208)."""

    role: Role
    entries: list[AssignmentMatrixEntry]


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
    Songs, ordered by name. Each cell lists an AssignmentMatrixEntry per
    SongRoleAssignment for that (Song, Role) pair, ordered by person name,
    each carrying is_role_mismatch (issue #208).
    """
    songs, start_times = _matrix_songs(rehearsal)
    roles = list(Role.objects.filter(songrolerequirement__song__in=songs).distinct().order_by('name'))
    entries_by_song_role = _matrix_entries_by_song_role(songs, roles)
    rows = [
        AssignmentMatrixRow(
            song=song,
            start_time=start_times.get(song.id),
            cells=[
                AssignmentMatrixCell(role=role, entries=entries_by_song_role.get((song.id, role.id), []))
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


def _matrix_entries_by_song_role(songs, roles):
    """Return {(song_id, role_id): [AssignmentMatrixEntry, ...]} for every assignment among `songs`/`roles` (issue #208).

    Ordered by person name, matching the prior raw-assignment ordering.
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
    return result


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
    """The Pending Buffer `apply_song_role_assignments()` commits in one transaction (issue #210).

    Removal-only for this slice (ADR-0009): `removed_assignment_ids` names
    every SongRoleAssignment row to delete, wherever on the grid its chip's
    ✕ was clicked. `semester_id` and `semester_updated_at` back the same
    two staleness checks `RosterEditBuffer` uses — `semester_id` against
    the caller's session-scoped viewing Semester, `semester_updated_at`
    against the Semester row's current stamp.
    """

    semester_id: int
    semester_updated_at: datetime
    removed_assignment_ids: frozenset[int]


def apply_song_role_assignments(buffer: AssignmentEditBuffer, *, viewing_semester: Semester) -> None:
    """Apply a Buffer of SongRoleAssignment removals in one transaction (issue #210, ADR-0009).

    Removal is semester-wide: SongRoleAssignment is (song, role, person)
    with no rehearsal FK, so deleting a row here removes that Person from
    that Song at every Rehearsal and at the concert, not only the Rehearsal
    whose grid the admin was viewing. Takes no Semester row lock — nothing
    here renumbers Song positions or RehearsalSong order, so there is no
    ordering constraint to serialize against. Registers no
    `transaction.on_commit()` call — nothing here reaches outside the
    Semester (no mail, no object storage).

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

        SongRoleAssignment.objects.filter(
            pk__in=buffer.removed_assignment_ids, song__semester=semester,
        ).delete()

        semester.updated_at = timezone.now()
        semester.save(update_fields=['updated_at'])


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
    another. Raises `StaleSongRoleRequirementsError` inside the transaction
    if the Semester's `updated_at` no longer matches
    `buffer.semester_updated_at`, rolling back whatever this call had
    already applied.
    """
    if viewing_semester is None or buffer.semester_id != viewing_semester.pk:
        raise WrongViewingSemesterError(
            "This Requirements edit Buffer's Semester doesn't match the Semester you're currently viewing."
        )

    with transaction.atomic():
        semester = Semester.objects.get(pk=buffer.semester_id)
        if semester.updated_at != buffer.semester_updated_at:
            raise StaleSongRoleRequirementsError(
                'The Requirements changed while you were editing — reload and reapply.'
            )

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

        semester.updated_at = timezone.now()
        semester.save(update_fields=['updated_at'])

    return song
