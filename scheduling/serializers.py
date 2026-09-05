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
