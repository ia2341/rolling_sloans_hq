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

from django.utils import timezone

from identity.serializers import serialize_viewer
from scheduling import services
from scheduling.fields import format_song_length
from scheduling.models import Conflict, Rehearsal, Song
from scheduling.services import (
    SetlistEditBuffer,
    SetlistEditFallout,
    SetlistSongDeletion,
    SpotifyImportCandidate,
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


def _serialize_spotify_import_candidate(candidate: SpotifyImportCandidate) -> dict:
    """Return one `SpotifyImportCandidate`: its display fields plus the server-computed duplicate flag (issue #335).

    `length` crosses as its display string like every other Song length on
    the wire; a candidate whose track carried no usable duration (never
    seen from `scheduling.spotify` today, which always derives one from
    `duration_ms`, but not guaranteed by its contract) crosses as `''`
    rather than a fabricated `0:00`, per issue #335 user story 33.
    """
    return {
        'title': candidate.title,
        'artist': candidate.artist,
        'length': format_song_length(candidate.length) if candidate.length else '',
        'already_in_setlist': candidate.already_in_setlist,
    }


def serialize_spotify_import(candidates: list[SpotifyImportCandidate], *, skipped_count: int, skipped_reasons: dict, message: str) -> dict:
    """Return the `/api/setlist/spotify/` `data` shape (issue #335): answers its own question, not the write envelope.

    `message` is `''` on a successful fetch and a readable explanation
    otherwise (an invalid link, an unconfigured credential, a Spotify-side
    failure) — the sheet renders it as a plain message rather than an
    error state, and `candidates`/`skipped_*` are empty whenever it's set.
    """
    return {
        'songs': [_serialize_spotify_import_candidate(candidate) for candidate in candidates],
        'skipped_count': skipped_count,
        'skipped_reasons': dict(skipped_reasons),
        'message': message,
    }


def serialize_availability(rehearsal, conflict_row) -> dict:
    """Return `/api/schedule/`'s "Your availability" block for one Rehearsal (issue #331).

    Carries only the viewer's own Conflict, never a teammate's (ADR 0005):
    `conflict_row` is that Rehearsal's `ConflictHistoryRow` for the viewer,
    from `services.conflict_rows_by_rehearsal()`, or None when nothing is
    declared. `admin_note` is the one piece of Conflict data that travels
    to someone other than an admin — its owner reads it here. Shared by
    the read view and the declare/withdraw write endpoints, so a
    successful write's response carries the same shape a follow-up read
    would.
    """
    conflict = conflict_row.conflict if conflict_row is not None else None
    return {
        'declaration_type': conflict_row.declaration_type if conflict_row is not None else None,
        'type_label': conflict_row.type_label if conflict_row is not None else None,
        'declared_time': conflict_row.declared_time.isoformat() if conflict_row and conflict_row.declared_time else None,
        'reason': conflict.reason if conflict is not None else None,
        'status': conflict.status if conflict is not None else None,
        'admin_note': conflict.adjudication_note if conflict is not None else None,
        'is_dress': rehearsal.is_full_setlist,
        'is_editable': not rehearsal.is_full_setlist and rehearsal.date >= timezone.localdate(),
    }


def _serialize_timeline_slot(slot) -> dict:
    """Return one `TimelineSlot`: the Song's title and span, and whether the viewer is on it."""
    return {
        'song_id': slot.song.pk,
        'song_title': slot.song.title,
        'start_time': slot.start_time.isoformat(),
        'end_time': slot.end_time.isoformat(),
        'is_viewer': slot.is_viewer,
    }


def _serialize_timeline(timeline) -> dict:
    """Return `services.Timeline` as the "You at this rehearsal" wire shape."""
    return {
        'slots': [_serialize_timeline_slot(slot) for slot in timeline.slots],
        'window_start': timeline.window_start.isoformat(),
        'window_end': timeline.window_end.isoformat(),
        'viewer_song_count': timeline.viewer_song_count,
        'total_song_count': timeline.total_song_count,
        'viewer_start_time': timeline.viewer_start_time.isoformat() if timeline.viewer_start_time else None,
        'viewer_end_time': timeline.viewer_end_time.isoformat() if timeline.viewer_end_time else None,
        'is_dress_rehearsal': timeline.is_dress_rehearsal,
    }


def _serialize_matrix_entry(entry, *, is_admin, conflicted_person_ids) -> dict:
    """Return one `AssignmentMatrixEntry`: the Person by name (never email), never `covering_for` for a member (ADR 0007).

    `has_conflict` is a marker only — never a reason, a declaration type
    or a time (ADR 0005) — true when the entry's Person has declared any
    Conflict against this Rehearsal.
    """
    data = {
        'id': entry.id,
        'kind': entry.kind,
        'person_id': entry.person.pk,
        'person_name': entry.person.name,
        'is_role_mismatch': entry.is_role_mismatch,
        'has_conflict': entry.person.pk in conflicted_person_ids,
    }
    if is_admin:
        data['covering_for_name'] = entry.covering_for.name if entry.covering_for is not None else None
    return data


def _serialize_matrix_cell(cell, *, is_admin, conflicted_person_ids) -> dict:
    """Return one `AssignmentMatrixCell`: its Role id and ordered entries."""
    return {
        'role_id': cell.role.pk,
        'entries': [
            _serialize_matrix_entry(entry, is_admin=is_admin, conflicted_person_ids=conflicted_person_ids)
            for entry in cell.entries
        ],
    }


def _serialize_matrix_row(row, *, is_admin, conflicted_person_ids) -> dict:
    """Return one `AssignmentMatrixRow`: the Song, its slot start_time (null for the Dress Rehearsal), and its cells."""
    return {
        'song_id': row.song.pk,
        'song_title': row.song.title,
        'start_time': row.start_time.isoformat() if row.start_time else None,
        'cells': [
            _serialize_matrix_cell(cell, is_admin=is_admin, conflicted_person_ids=conflicted_person_ids)
            for cell in row.cells
        ],
    }


def _serialize_rehearsal_summary(rehearsal, *, today) -> dict:
    """Return one Rehearsal's quick-jump/list identity: id, date, window and whether it's the Dress Rehearsal or past."""
    return {
        'id': rehearsal.pk,
        'date': rehearsal.date.isoformat(),
        'start_time': rehearsal.start_time.isoformat(),
        'end_time': rehearsal.end_time.isoformat(),
        'is_dress': rehearsal.is_full_setlist,
        'is_past': rehearsal.date < today,
    }


def _serialize_your_state(rehearsal, conflict_row, attendance_suggestion) -> dict:
    """Return the All-rehearsals row's one-chip summary of the viewer's own state for `rehearsal` (issue #331).

    `mandatory` for the Dress Rehearsal outranks everything else — it
    takes no Conflict (ADR 0006) — else a declared Conflict, else a
    suggested arrival/departure window, else "not needed".
    """
    if rehearsal.is_full_setlist:
        return {'kind': 'mandatory'}
    if conflict_row is not None:
        return {
            'kind': 'conflict',
            'type_label': conflict_row.type_label,
            'declared_time': conflict_row.declared_time.isoformat() if conflict_row.declared_time else None,
        }
    if attendance_suggestion is not None:
        return {
            'kind': 'window',
            'arrival_time': attendance_suggestion.arrival_time.isoformat(),
            'departure_time': attendance_suggestion.departure_time.isoformat(),
        }
    return {'kind': 'not_needed'}


def _serialize_schedule_list_row(row, *, conflict_rows, is_admin, pending_counts, today) -> dict:
    """Return one `RehearsalListRow` for the All-rehearsals sub-view: identity, song count, the viewer's state, and (admin) a pending count."""
    rehearsal = row.rehearsal
    data = {
        **_serialize_rehearsal_summary(rehearsal, today=today),
        'song_count': len(services.assignment_matrix_for(rehearsal).rows),
        'your_state': _serialize_your_state(rehearsal, conflict_rows.get(rehearsal.pk), row.attendance_suggestion),
    }
    if is_admin and rehearsal.pk in pending_counts:
        data['pending_count'] = pending_counts[rehearsal.pk]
    return data


def _serialize_rehearsal_detail(rehearsal, *, viewer, is_admin, today) -> dict:
    """Return `/api/schedule/`'s "This rehearsal" sub-view detail for `rehearsal` (issue #331).

    `can_edit_assignments` is the ADR-0009 gate: true only for an admin on
    an editable grid (`services.assignment_grid_is_editable()`), never
    re-derived by the client.
    """
    matrix = services.assignment_matrix_for(rehearsal)
    roles = matrix.roles
    codes = services.role_codes_for(roles)
    conflicted_person_ids = set(
        Conflict.objects.filter(rehearsal=rehearsal).values_list('person_id', flat=True),
    )
    conflict_row = services.conflict_rows_by_rehearsal(rehearsal.semester, viewer).get(rehearsal.pk)
    return {
        **_serialize_rehearsal_summary(rehearsal, today=today),
        'can_edit_assignments': is_admin and services.assignment_grid_is_editable(rehearsal),
        'timeline': _serialize_timeline(services.timeline_for(rehearsal, viewer)),
        'availability': serialize_availability(rehearsal, conflict_row),
        'roles': [_serialize_role_legend_entry(role, codes) for role in roles],
        'rows': [
            _serialize_matrix_row(row, is_admin=is_admin, conflicted_person_ids=conflicted_person_ids)
            for row in matrix.rows
        ],
    }


def serialize_schedule(request, semester, *, rehearsal_id=None) -> dict:
    """Return the `/api/schedule/` `data` shape for `semester` (issue #331): one round trip for both sub-views.

    Carries the whole `RehearsalSchedule` (for the All-rehearsals sub-view
    and the quick-jump row) plus one selected Rehearsal's full detail (for
    the This-rehearsal sub-view) — the sub-view toggle is client-side
    state, never a second fetch. `rehearsal_id` selects which Rehearsal to
    detail; omitted, it falls back to `services.landing_rehearsal_for()`.
    Raises `Rehearsal.DoesNotExist` for a `rehearsal_id` outside `semester`,
    left for the view to turn into a 404 (ADR 0001).
    """
    viewer = request.user
    is_admin = bool(getattr(viewer, 'is_admin', False))
    if semester is None:
        return {'semester_name': None, 'schedule': {'past': [], 'future': []}, 'selected': None}
    today = timezone.localdate()
    if rehearsal_id is not None:
        selected_rehearsal = Rehearsal.objects.get(pk=rehearsal_id, semester=semester)
    else:
        selected_rehearsal = services.landing_rehearsal_for(viewer, semester)
    conflict_rows = services.conflict_rows_by_rehearsal(semester, viewer)
    pending_counts = (
        {row.rehearsal.pk: row.pending_count for row in services.conflict_adjudication_index_for(semester)}
        if is_admin
        else {}
    )
    schedule = services.rehearsal_schedule_for(semester, viewer)
    return {
        'semester_name': semester.name,
        'schedule': {
            section: [
                _serialize_schedule_list_row(
                    row, conflict_rows=conflict_rows, is_admin=is_admin, pending_counts=pending_counts, today=today,
                )
                for row in rows
            ]
            for section, rows in (('past', schedule.past), ('future', schedule.future))
        },
        'selected': (
            _serialize_rehearsal_detail(selected_rehearsal, viewer=viewer, is_admin=is_admin, today=today)
            if selected_rehearsal is not None
            else None
        ),
    }


def _serialize_roster_entry(membership):
    """Return one Band-page row: `Person.name` (never the object, per `.name`-not-`Person` rule), declared Role names, and the annotated Song count (issue #333)."""
    return {
        'id': membership.person_id,
        'name': membership.person.name,
        'roles': [role.role.name for role in membership.membershiprole_set.all()],
        'song_count': membership.songs_count,
    }


def serialize_band(memberships, semester) -> dict:
    """Return the `/api/members/` `data` shape (issue #333): the viewing Semester's active Roster, or the empty/no-Semester shape.

    Carries no admin-only field — `can_edit_roster` isn't needed on the
    wire since the "Edit roster" button is unconditionally rendered for an
    admin viewer by `context.viewer.is_admin`, matching how Setlist's "Edit
    setlist" button reads that same flag rather than a per-payload one.
    """
    if semester is None:
        return {'semester_name': None, 'member_count': 0, 'members': []}
    entries = list(memberships)
    return {
        'semester_name': semester.name,
        'member_count': len(entries),
        'members': [_serialize_roster_entry(membership) for membership in entries],
    }


def _serialize_role(role) -> dict:
    """Return one Role as `id`/`name`, for a Person page's declared-Roles chips and its editable Role catalog (issue #333)."""
    return {'id': role.pk, 'name': role.name}


def _serialize_person_song(assignment) -> dict:
    """Return one Person-page Songs row: the Song's title and the Role filled — never `is_role_mismatch` (ADR 0002, issue #333)."""
    return {
        'song_id': assignment.song_id,
        'song_title': assignment.song.title,
        'artist': assignment.song.artist,
        'role_name': assignment.role.name,
    }


def _serialize_person_recording(recording) -> dict:
    """Return one row of a Person's own Recordings list: everything but the object key (ADR 0004, issue #333)."""
    return {
        'id': recording.id,
        'song_title': recording.song_title,
        'rehearsal_date': recording.rehearsal_date.isoformat(),
        'start_time': recording.start_time.isoformat() if recording.start_time else None,
        'end_time': recording.end_time.isoformat() if recording.end_time else None,
        'note': recording.note,
        'file_size': recording.file_size,
        'uploaded_at': recording.uploaded_at.isoformat(),
        'playback_url': recording.playback_url,
    }


def _serialize_slot_option(option) -> dict:
    """Return one Upload-a-take picker option, naming the Song and Rehearsal slot it belongs to (issue #333)."""
    return {
        'id': option.id,
        'song_id': option.song_id,
        'song_title': option.song_title,
        'rehearsal_date': option.rehearsal_date.isoformat(),
        'start_time': option.start_time.isoformat() if option.start_time else None,
        'end_time': option.end_time.isoformat() if option.end_time else None,
    }


def serialize_person(person, *, semester, is_self: bool, can_edit_roles: bool, membership) -> dict:
    """Return the `/api/members/<pk>/` `data` shape for `person` (issue #333), computed for exactly one of the three viewer states.

    Follows `docs/person-page-visibility.md`'s "absent, not null" contract
    strictly: `email` and the whole `recordings` block are present only in
    the self payload, `available_roles` only when `can_edit_roles`, and
    `roles`/`songs` only when `person` holds a saved `Membership` in
    `semester` — the not-yet-rostered self case renders name, email and an
    editable (empty) Roles card with no declared-Roles list and no Songs
    section at all, never a zero (issue #333 user stories 23-24). Carries
    no `Conflict`, `Backup`, `is_role_mismatch` or attendance-inference
    field anywhere, for any viewer, including an admin (ADR 0005, ADR
    0007, ADR 0002) — the boundary is drawn around this surface, not the
    viewer.
    """
    has_membership = membership is not None and membership.pk is not None
    data = {
        'id': person.pk,
        'name': person.name,
        'is_self': is_self,
        'can_edit_roles': can_edit_roles,
        'has_membership': has_membership,
        'semester_name': semester.name if semester is not None else None,
    }
    if is_self:
        data['email'] = person.email
    if can_edit_roles:
        data['available_roles'] = [_serialize_role(role) for role in services.active_roles_for(semester)] if semester is not None else []
    if has_membership:
        data['roles'] = [_serialize_role(role) for role in services.declared_roles_for(membership)]
        data['songs'] = [_serialize_person_song(assignment) for assignment in services.assigned_songs_for(person, semester)]
    if is_self and has_membership:
        data['recordings'] = serialize_person_recordings(person, semester)
    return data


def serialize_person_recordings(person, semester) -> dict:
    """Return the self-only Recordings block (issue #333): its count, its rows, and the Upload-a-take slot picker's options.

    Shared by `serialize_person()` and the upload-confirm/delete `/api/`
    endpoints, which both return this same shape as their "updated state"
    after a write — so a confirm or delete never has to disagree with what
    a fresh page load would show.
    """
    recordings = services.person_recordings_for(person, semester)
    upload_slots = services.recording_slot_options_for(semester)
    return {
        'count': len(recordings),
        'items': [_serialize_person_recording(recording) for recording in recordings],
        'upload_slots': [_serialize_slot_option(option) for option in upload_slots],
    }
