"""Hand-written `/api/` wire serializers for `scheduling` (issue #326), mirroring `scheduling/services.py`.

Each function names every field it emits — no `dataclasses.asdict()`,
`model_to_dict()`, or other emit-everything helper, on ADR 0005 grounds: a
convenience that serializes a whole object is a rule that says "emit every
field", and the day a new field lands on a dataclass here it would ship to
a member-facing payload with no line of code deciding that was safe.
`scheduling/tests/test_prohibited_serializer_helpers.py` enforces this
mechanically for both serializer modules. Joining, deriving and privacy
filtering all stay in `services.py`; a serializer names fields and
nothing more.
"""

from identity.serializers import serialize_viewer
from scheduling import services
from scheduling.fields import format_song_length
from scheduling.models import Song
from scheduling.services import (
    SetlistEditBuffer,
    SetlistEditFallout,
    SetlistSongDeletion,
)

# The Semester status set crosses the wire as lowercase snake-case,
# mirroring `services._semester_status()`'s three internal labels.
_STATUS_WIRE_VALUES = {
    services.SEMESTER_STATUS_LIVE: 'live',
    services.SEMESTER_STATUS_DRAFT: 'draft',
    services.SEMESTER_STATUS_PREVIOUSLY_PUBLISHED: 'previously_published',
}


def _serialize_semester(semester, status):
    """Return `semester` as the context block's `viewing_semester` shape: `id`, `name`, `status`, `published_at`, `updated_at`."""
    return {
        'id': semester.pk,
        'name': semester.name,
        'status': status,
        'published_at': semester.published_at,
        'updated_at': semester.updated_at,
    }


def _serialize_live_semester(semester):
    """Return `semester` as the context block's `live_semester` shape: `id`, `name`."""
    return {'id': semester.pk, 'name': semester.name}


def _serialize_semester_option(option):
    """Return one `SemesterOption` as a `semester_options` entry, including its member/song/rehearsal counts."""
    return {
        'id': option.semester.pk,
        'name': option.semester.name,
        'status': _STATUS_WIRE_VALUES[option.status],
        'is_viewing': option.is_viewing,
        'member_count': option.member_count,
        'song_count': option.song_count,
        'rehearsal_count': option.rehearsal_count,
    }


def serialize_context(request) -> dict:
    """Return the six-key `context` block every `/api/` response carries (issue #326).

    Reads `get_viewing_semester()`, `get_live_semester()`,
    `semester_banner_for()` and `semester_options_for()` and re-derives
    none of them — "which Semester is this request scoped to" stays
    answered in exactly one place (`services.get_viewing_semester()`), for
    reads and writes alike. The viewing Semester's wire `status` is read
    off its matching `semester_options_for()` entry rather than
    recomputed, for the same reason.

    `pending_conflict_count` is `null` for a member and an integer for an
    admin — the one count an admin wants ambient, and never a name or a
    reason, so no member-facing payload carries it (ADR 0005).
    """
    person = request.user
    is_admin = bool(getattr(person, 'is_admin', False))
    viewing = services.get_viewing_semester(request)
    live = services.get_live_semester()
    options = services.semester_options_for(request)

    if viewing is None:
        viewing_payload = None
    elif is_admin:
        matched_option = next(option for option in options if option.is_viewing)
        viewing_payload = _serialize_semester(viewing, _STATUS_WIRE_VALUES[matched_option.status])
    else:
        # A non-admin's viewing Semester is always the Live Semester
        # (services.get_viewing_semester()'s member branch), so its status
        # is always "live" without consulting semester_options_for(),
        # which returns nothing for a member.
        viewing_payload = _serialize_semester(viewing, 'live')

    return {
        'viewer': serialize_viewer(person),
        'viewing_semester': viewing_payload,
        'live_semester': _serialize_live_semester(live) if live is not None else None,
        'semester_warning': services.semester_banner_for(request) is not None,
        'semester_options': [_serialize_semester_option(option) for option in options],
        'pending_conflict_count': services.pending_conflict_count_for(viewing) if is_admin and viewing is not None else None,
    }


def _serialize_role_legend_entry(role, codes):
    """Return one Role as a `roles` legend entry: `id`, `name`, `code`."""
    return {'id': role.pk, 'name': role.name, 'code': codes[role.id]}


def _serialize_cast_performer(performer):
    """Return one `CastPerformer` by name only (never `Person.email`, ADR 0005), plus the ADR-0002 mismatch flag."""
    return {
        'id': performer.person.pk,
        'name': performer.person.name,
        'is_role_mismatch': performer.is_role_mismatch,
    }


def _serialize_cast_entry(entry):
    """Return one `CastRoleEntry`: the Role's id/name/code and its performers, empty when the Role is unfilled."""
    return {
        'role_id': entry.role.pk,
        'role_name': entry.role.name,
        'code': entry.code,
        'performers': [_serialize_cast_performer(performer) for performer in entry.performers],
    }


def _serialize_setlist_song(song, roles, codes):
    """Return one Setlist row: the Song's own fields, its role-by-role cast line, and its take count."""
    return {
        'id': song.pk,
        'title': song.title,
        'artist': song.artist,
        'length': format_song_length(song.length),
        'position': song.position,
        'notes': song.notes,
        'cast': [_serialize_cast_entry(entry) for entry in services.cast_line_for(song, roles, codes)],
        'recording_count': services.recording_count_for(song),
    }


def serialize_setlist(semester) -> dict:
    """Return the `/api/setlist/` `data` shape for `semester` (issue #330), or its empty-Semester/no-Semester shape when there's nothing to show.

    Carries no `Conflict`, `ConflictWindow` or `Backup` field of any kind,
    and no attendance inference (ADR 0005) — this surface has no Rehearsal
    in scope. `is_role_mismatch` is the deliberate exception (ADR 0002):
    `docs/person-page-visibility.md`'s `never` verdict for it is scoped to
    `/members/` and `/members/<pk>/`, not to this surface.
    """
    if semester is None:
        return {'semester_name': None, 'song_count': 0, 'total_running_time': '0:00', 'roles': [], 'songs': []}
    songs = list(Song.objects.filter(semester=semester).order_by('position'))
    roles = services.active_roles_for(semester)
    codes = services.role_codes_for(roles)
    return {
        'semester_name': semester.name,
        'song_count': len(songs),
        'total_running_time': services.setlist_total_running_time(semester),
        'roles': [_serialize_role_legend_entry(role, codes) for role in roles],
        'songs': [_serialize_setlist_song(song, roles, codes) for song in songs],
    }


def _serialize_recording(recording):
    """Return one Recording by its uploader's name (never email) and its short-lived signed playback URL (ADR 0004)."""
    return {
        'id': recording.pk,
        'uploaded_by_name': recording.uploaded_by.name,
        'note': recording.note,
        'playback_url': services.create_recording_playback_url(recording),
    }


def _serialize_recording_group(group):
    """Return one `RecordingSlotGroup`: the slot's Rehearsal date and window, its take count, and its Recordings."""
    rehearsal_song = group.rehearsal_song
    return {
        'rehearsal_id': rehearsal_song.rehearsal_id,
        'date': rehearsal_song.rehearsal.date.isoformat(),
        'start_time': rehearsal_song.start_time.isoformat() if rehearsal_song.start_time else None,
        'end_time': rehearsal_song.end_time.isoformat() if rehearsal_song.end_time else None,
        'take_count': len(group.recordings),
        'recordings': [_serialize_recording(recording) for recording in group.recordings],
    }


def _serialize_rehearsed_at_row(row):
    """Return one `RehearsedAtRow`: its Rehearsal's date, whether it's the live-derived Dress Rehearsal row, and its slot times (null for the Dress Rehearsal)."""
    return {
        'rehearsal_id': row.rehearsal.pk,
        'date': row.rehearsal.date.isoformat(),
        'is_dress_rehearsal': row.is_dress_rehearsal,
        'start_time': row.start_time.isoformat() if row.start_time else None,
        'end_time': row.end_time.isoformat() if row.end_time else None,
    }


def _serialize_next_rehearsal(rehearsal):
    """Return the admin-only "Cast on …" pointer's target Rehearsal: `id` and `date`."""
    return {'id': rehearsal.pk, 'date': rehearsal.date.isoformat()}


def serialize_song(song, *, is_admin: bool, next_rehearsal) -> dict:
    """Return the `/api/songs/<pk>/` `data` shape for `song` (issue #330).

    `next_rehearsal` is the admin-only ADR-0009 pointer's target — pass
    `None` for a member viewer or when there's nothing upcoming, and it's
    omitted from the payload rather than emitted as a stray null so a
    member's payload carries no admin-only key at all. Carries no
    `Conflict`, `ConflictWindow` or `Backup` field, and no attendance
    inference (ADR 0005); `is_role_mismatch` is rendered here deliberately
    (ADR 0002) — see `serialize_setlist()`'s docstring.
    """
    roles = services.active_roles_for(song.semester)
    codes = services.role_codes_for(roles)
    data = {
        'id': song.pk,
        'title': song.title,
        'artist': song.artist,
        'length': format_song_length(song.length),
        'position': song.position,
        'notes': song.notes,
        'cast': [_serialize_cast_entry(entry) for entry in services.cast_line_for(song, roles, codes)],
        'recording_groups': [_serialize_recording_group(group) for group in services.recording_groups_for(song)],
        'rehearsed_at': [_serialize_rehearsed_at_row(row) for row in services.rehearsed_at_for(song)],
    }
    if is_admin:
        data['next_rehearsal'] = _serialize_next_rehearsal(next_rehearsal) if next_rehearsal is not None else None
    return data


def _serialize_setlist_song_deletion(deletion: SetlistSongDeletion) -> dict:
    """Return one `SetlistSongDeletion`: the doomed Song's title and its Recording/uploader/Running-Order counts."""
    return {
        'title': deletion.title,
        'recording_count': deletion.recording_count,
        'uploader_count': deletion.uploader_count,
        'running_order_count': deletion.running_order_count,
    }


def serialize_setlist_edit_fallout(fallout: SetlistEditFallout) -> dict:
    """Return a `SetlistEditFallout` as the `/api/setlist/preview/` response's `fallout` value (issue #334).

    Named field-by-field, matching every other serializer in this module
    — `is_blocked`/`block_message` are included so a caller can tell a
    genuinely-computed (if empty) Fallout apart from one that never ran,
    even though the `/api/setlist/preview/` view itself only ever calls
    this function on a *non*-blocked Fallout (a `WrongViewingSemesterError`
    is checked for and answered as its own 4xx before `preview_setlist_edits()`
    is even called, per the issue's "wrong semester_id hard-fails" rule).
    """
    return {
        'is_blocked': fallout.is_blocked,
        'block_message': fallout.block_message,
        'is_stale': fallout.is_stale,
        'pending_adds': list(fallout.pending_adds),
        'pending_edits': list(fallout.pending_edits),
        'reordered': fallout.reordered,
        'pending_deletions': [_serialize_setlist_song_deletion(deletion) for deletion in fallout.pending_deletions],
        'loud': list(fallout.loud),
        'quiet': list(fallout.quiet),
    }


def _serialize_setlist_edit_row_echo(row, index: int) -> dict:
    """Return one `SetlistEditRow` echoed back in `build_setlist_buffer_from_request()`'s wire shape.

    `row_key` isn't reconstructable from a `SetlistEditRow` — it was never
    stored on the Buffer, only used transiently to key a validation
    failure — so a *successfully built* Buffer's echo indexes positionally
    (`row-0`, `row-1`, ...). A validation failure's echo takes a different
    path entirely (the view echoes `SetlistBufferValidationError.raw_rows`
    directly, which does carry the client's own `row_key`s), since
    normalization never finished long enough to reach this function.
    """
    return {
        'row_key': f'row-{index}',
        'song_id': row.song_id,
        'title': row.title,
        'artist': row.artist,
        'length': format_song_length(row.length),
        'notes': row.notes,
    }


def serialize_setlist_edit_buffer(buffer: SetlistEditBuffer) -> dict:
    """Return a `SetlistEditBuffer` echoed back in `build_setlist_buffer_from_request()`'s wire shape (issue #334).

    Used only by `/api/setlist/preview/`'s `values` field on a *successful*
    build — every submitted value, normalized — never by `/api/setlist/save/`,
    which drops `values` per #326's rule that a write response echoes
    nothing back.
    """
    return {
        'semester_id': buffer.semester_id,
        'semester_updated_at': buffer.semester_updated_at.isoformat() if buffer.semester_updated_at else None,
        'rows': [_serialize_setlist_edit_row_echo(row, index) for index, row in enumerate(buffer.rows)],
        'deleted_song_ids': sorted(buffer.deleted_song_ids),
    }
