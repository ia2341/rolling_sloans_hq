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

from collections import defaultdict

from django.db.models import Count
from django.utils import timezone

from identity.serializers import serialize_viewer
from identity.services import invite_status_for
from scheduling import services
from scheduling.fields import format_song_length
from scheduling.models import (
    Conflict,
    Recording,
    Rehearsal,
    RehearsalPattern,
    RehearsalSong,
    Song,
)
from scheduling.services import (
    AssignmentEditBuffer,
    AssignmentEditFallout,
    AssignmentPickerResult,
    RoleCreationResult,
    RosterEditBuffer,
    RosterEditFallout,
    RosterImportProposal,
    SemesterDefaultsFallout,
    SemesterDeletionSummary,
    SemesterManagementRow,
    SemesterPublishImpact,
    SetlistEditBuffer,
    SetlistEditFallout,
    SetlistSongDeletion,
    SongRoleRequirementBuffer,
    SongRoleRequirementFallout,
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
    """Return `semester` as the context block's `viewing_semester` shape: `id`, `name`, `status`, `published_at`, `updated_at`.

    `published_at`/`updated_at` are explicitly `.isoformat()`'d, like every
    other timestamp field in this file: left as raw `datetime` objects,
    `DjangoJSONEncoder` truncates microseconds to milliseconds on encode,
    and `updated_at` round-tripped back through the client is exactly what
    `apply_roster_edits()`'s staleness check compares against the
    full-precision DB value (issue #409).
    """
    return {
        'id': semester.pk,
        'name': semester.name,
        'status': status,
        'published_at': semester.published_at.isoformat() if semester.published_at else None,
        'updated_at': semester.updated_at.isoformat(),
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


def _serialize_semester_management_row(row: SemesterManagementRow) -> dict:
    """Return one `SemesterManagementRow` as a Manage-semesters sheet row: label, viewing flag, and four counts (issue #329).

    Counts only, per ADR 0005 — no Conflict text, reason, note or person
    identity ever reaches this payload, only aggregate row counts.
    `updated_at` is a staleness token, not member data, so it carries no
    such restriction: it lets the sheet build a Reapply-defaults request
    for a row other than the one currently being viewed.
    """
    return {
        'id': row.semester.pk,
        'name': row.semester.name,
        'status': _STATUS_WIRE_VALUES[row.status],
        'is_viewing': row.is_viewing,
        'member_count': row.member_count,
        'song_count': row.song_count,
        'rehearsal_count': row.rehearsal_count,
        'recording_count': row.recording_count,
        'updated_at': row.updated_at.isoformat(),
    }


def serialize_semester_management_rows(rows: list[SemesterManagementRow]) -> list[dict]:
    """Return every `SemesterManagementRow` as the management-rows endpoint's `data` value (issue #329)."""
    return [_serialize_semester_management_row(row) for row in rows]


def serialize_semester_publish_impact(impact: SemesterPublishImpact) -> dict:
    """Return a `SemesterPublishImpact` as the Publish popup's `data` value (issue #329).

    `incumbent` is `None` (rather than an object with zeroed fields) when
    nothing is published or the target is already live — the popup's own
    job to render "nothing to supersede" from a null. Counts only, per
    ADR 0005: no Conflict text, reason, note or person identity here.
    """
    return {
        'target_semester_id': impact.target_semester.pk,
        'target_semester_name': impact.target_semester.name,
        'is_already_live': impact.is_already_live,
        'incumbent': (
            {'id': impact.incumbent.pk, 'name': impact.incumbent.name} if impact.incumbent is not None else None
        ),
        'incumbent_rehearsal_count': impact.incumbent_rehearsal_count,
        'incumbent_song_count': impact.incumbent_song_count,
        'has_no_setlist': impact.has_no_setlist,
        'has_no_rehearsals': impact.has_no_rehearsals,
    }


def serialize_semester_deletion_summary(summary: SemesterDeletionSummary) -> dict:
    """Return a `SemesterDeletionSummary` as the Delete popup's `data` value (issue #329).

    Reuses `semester_deletion_summary()`'s already-computed counts
    unchanged — the four counts must not be recomputed anywhere else, per
    the issue. Counts only, per ADR 0005.
    """
    return {
        'member_count': summary.member_count,
        'song_count': summary.song_count,
        'rehearsal_count': summary.rehearsal_count,
        'recording_count': summary.recording_count,
    }


def serialize_semester_defaults_fallout(fallout: SemesterDefaultsFallout) -> dict:
    """Return a `SemesterDefaultsFallout` as the Reapply-defaults preview's `fallout` value (issue #329, ADR 0008).

    Named field-by-field, matching `serialize_setlist_edit_fallout()`/
    `serialize_rehearsal_edit_fallout()`. `loud`/`quiet` are already plain
    strings (`preview_semester_defaults_reapply()` composes them, unlike
    the row-shaped surfaces' structured deletions), so no per-entry
    sub-serializer is needed here.
    """
    return {
        'is_blocked': fallout.is_blocked,
        'block_message': fallout.block_message,
        'is_stale': fallout.is_stale,
        'changed_rehearsal_count': fallout.changed_rehearsal_count,
        'loud': list(fallout.loud),
        'quiet': list(fallout.quiet),
    }


def _serialize_role_legend_entry(role, codes):
    """Return one Role as a `roles` legend entry: `id`, `name`, `code`, and its RoleGroup (issue #457, #462).

    `group_name`/`group_order`/`group_is_catch_all` replace the frontend's
    retired `classifyRole()` keyword match as the Setlist/Schedule cast
    tables' column-grouping source: `group_order` fixes column order
    (independent of `group_name`'s alphabetical order), and
    `group_is_catch_all` tells the client to render this Role its own
    column rather than merging it with its groupmates, mirroring how an
    unmatched Role name used to get its own column. `group_id` (issue
    #462) lets the Add Songs role-count step build a `role_group_counts`
    wire entry (`SetlistRoleGroupCount.role_group_id`) straight from this
    already-loaded legend, with no second request needed to learn a
    RoleGroup's id.
    """
    return {
        'id': role.pk,
        'name': role.name,
        'code': codes[role.id],
        'group_id': role.group_id,
        'group_name': role.group.name,
        'group_order': role.group.display_order,
        'group_is_catch_all': role.group.is_catch_all,
    }


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


def _serialize_setlist_song(song, cast, recording_count):
    """Return one Setlist row: the Song's own fields, its role-by-role cast line, and its take count."""
    return {
        'id': song.pk,
        'title': song.title,
        'artist': song.artist,
        'length': format_song_length(song.length),
        'position': song.position,
        'notes': song.notes,
        'cast': [_serialize_cast_entry(entry) for entry in cast],
        'recording_count': recording_count,
    }


def serialize_setlist(semester) -> dict:
    """Return the `/api/setlist/` `data` shape for `semester` (issue #330), or its empty-Semester/no-Semester shape when there's nothing to show.

    Carries no `Conflict`, `ConflictWindow` or `Backup` field of any kind,
    and no attendance inference (ADR 0005) — this surface has no Rehearsal
    in scope. `is_role_mismatch` is the deliberate exception (ADR 0002):
    `docs/person-page-visibility.md`'s `never` verdict for it is scoped to
    `/members/` and `/members/<pk>/`, not to this surface.

    Cast lines and recording counts come from `services.cast_lines_for_semester()`/
    `recording_counts_for_semester()` — computed once for every Song in
    `semester` (issue #394), rather than `cast_line_for()`/
    `recording_count_for()` once per Song, which made this list's cost
    scale with the Semester's Song count.
    """
    if semester is None:
        return {'semester_name': None, 'song_count': 0, 'total_running_time': '0:00', 'roles': [], 'songs': []}
    songs = list(Song.objects.filter(semester=semester).order_by('position'))
    roles = services.active_roles_for(semester)
    codes = services.role_codes_for(roles)
    cast_lines = services.cast_lines_for_semester(semester, roles, codes)
    recording_counts = services.recording_counts_for_semester(semester)
    return {
        'semester_name': semester.name,
        'song_count': len(songs),
        'total_running_time': services.setlist_total_running_time(semester),
        'roles': [_serialize_role_legend_entry(role, codes) for role in roles],
        'songs': [
            _serialize_setlist_song(song, cast_lines.get(song.id, []), recording_counts.get(song.id, 0))
            for song in songs
        ],
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


def _serialize_role_fill_status(status) -> dict:
    """Return one `RoleFillStatus`: the Role's name and its target-vs-actual fill state (issue #207, #339).

    Includes a Requirement naming a retired Role (`is_retired_role`),
    never filtered out — real data an admin may want to clear (issue
    #207) — and is rendered to every viewer, not just an admin: a member
    reads it to notice an under-staffed Role and volunteer (issue #339
    user story 35).
    """
    return {
        'role_id': status.role.pk,
        'role_name': status.role.name,
        'target': status.target,
        'actual': status.actual,
        'is_understaffed': status.is_understaffed,
        'is_retired_role': status.is_retired_role,
    }


def _serialize_addable_role(role) -> dict:
    """Return one Role offered by the Requirements editor's "+ Add role requirement" control: `id`/`name`."""
    return {'id': role.pk, 'name': role.name}


def serialize_song(song, *, is_admin: bool, next_rehearsal) -> dict:
    """Return the `/api/songs/<pk>/` `data` shape for `song` (issue #330, #339).

    `next_rehearsal` is the admin-only ADR-0009 pointer's target — pass
    `None` for a member viewer or when there's nothing upcoming, and it's
    omitted from the payload rather than emitted as a stray null so a
    member's payload carries no admin-only key at all. Carries no
    `Conflict`, `ConflictWindow` or `Backup` field, and no attendance
    inference (ADR 0005); `is_role_mismatch` is rendered here deliberately
    (ADR 0002) — see `serialize_setlist()`'s docstring. `role_requirements`
    is rendered for every viewer (issue #339 user story 35); `available_roles`
    — the Requirements editor's "+ Add role requirement" candidates — is
    admin-only, omitted entirely for a member (issue #339 user story 34).
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
        'role_requirements': [
            _serialize_role_fill_status(status) for status in services.fill_status_for(song)
        ],
        'recording_groups': [_serialize_recording_group(group) for group in services.recording_groups_for(song)],
        'rehearsed_at': [_serialize_rehearsed_at_row(row) for row in services.rehearsed_at_for(song)],
    }
    if is_admin:
        data['next_rehearsal'] = _serialize_next_rehearsal(next_rehearsal) if next_rehearsal is not None else None
        data['available_roles'] = [
            _serialize_addable_role(role) for role in services.addable_roles_for_song(song)
        ]
    return data


def _serialize_setlist_song_deletion(deletion: SetlistSongDeletion) -> dict:
    """Return one `SetlistSongDeletion`: the doomed Song's title and its Recording/uploader/Running-Order counts."""
    return {
        'title': deletion.title,
        'recording_count': deletion.recording_count,
        'uploader_count': deletion.uploader_count,
        'running_order_count': deletion.running_order_count,
    }


def _serialize_setlist_role_requirement_addition(addition) -> dict:
    """Return one `SetlistRoleRequirementAddition`: the new Song's title, the resolved Role's name, and the target count."""
    return {
        'song_title': addition.song_title,
        'role_name': addition.role_name,
        'count': addition.count,
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
        'pending_role_requirements': [
            _serialize_setlist_role_requirement_addition(addition)
            for addition in fallout.pending_role_requirements
        ],
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
        'role_group_counts': [
            {'role_group_id': entry.role_group_id, 'count': entry.count} for entry in row.role_group_counts
        ],
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


def _serialize_song_role_requirement_entry_echo(entry) -> dict:
    """Return one `SongRoleRequirementEntry` echoed back in `build_song_role_requirement_buffer_from_request()`'s wire shape."""
    return {'role_id': entry.role_id, 'count': entry.count}


def serialize_song_role_requirement_buffer(buffer: SongRoleRequirementBuffer) -> dict:
    """Return a `SongRoleRequirementBuffer` echoed back in the Requirements editor's wire shape (issue #339).

    Used only by the Preview endpoint's `values` field on a *successful*
    build — every submitted value, normalized — never by the Save
    endpoint, which drops `values` per #326's rule that a write response
    echoes nothing back.
    """
    return {
        'song_id': buffer.song_id,
        'semester_id': buffer.semester_id,
        'semester_updated_at': buffer.semester_updated_at.isoformat() if buffer.semester_updated_at else None,
        'entries': [_serialize_song_role_requirement_entry_echo(entry) for entry in buffer.entries],
    }


def _serialize_song_role_requirement_addition(addition) -> dict:
    """Return one `SongRoleRequirementAddition`: the Role name and its target count."""
    return {'role_name': addition.role_name, 'count': addition.count}


def _serialize_song_role_requirement_count_change(change) -> dict:
    """Return one `SongRoleRequirementCountChange`: the Role name and its before/after target count."""
    return {'role_name': change.role_name, 'before': change.before, 'after': change.after}


def _serialize_song_role_requirement_removal(removal) -> dict:
    """Return one `SongRoleRequirementRemoval`: the Role name and whether it's since been retired."""
    return {'role_name': removal.role_name, 'is_retired_role': removal.is_retired_role}


def serialize_song_role_requirement_fallout(fallout: SongRoleRequirementFallout) -> dict:
    """Return a `SongRoleRequirementFallout` as the Requirements editor Preview response's `fallout` value (issue #339).

    Named field-by-field, matching every other serializer in this module.
    `is_blocked`/`block_message` are included so a caller can tell a
    genuinely-computed (if empty) Fallout apart from one that never ran,
    even though the Preview view itself only ever calls this function on a
    *non*-blocked Fallout (a `WrongViewingSemesterError` is checked for and
    answered as its own 4xx before `preview_song_role_requirements()` is
    even called, per #334's "wrong semester_id hard-fails" rule).
    """
    return {
        'is_blocked': fallout.is_blocked,
        'block_message': fallout.block_message,
        'is_stale': fallout.is_stale,
        'pending_adds': [_serialize_song_role_requirement_addition(addition) for addition in fallout.pending_adds],
        'pending_edits': [_serialize_song_role_requirement_count_change(change) for change in fallout.pending_edits],
        'pending_removals': [
            _serialize_song_role_requirement_removal(removal) for removal in fallout.pending_removals
        ],
        'loud': list(fallout.loud),
        'quiet': list(fallout.quiet),
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
    """Return one `AssignmentMatrixRow`: the Song, its slot start_time (null for the Dress Rehearsal), its cells, and its RehearsalSong id.

    `rehearsal_song_id` (null on the Dress Rehearsal, ADR-0003) is the
    Running Order reorder surface's row identity — the "Edit Rehearsal"
    drag-and-drop submits the reordered list of these ids, unchanged from
    what this same read already carries, rather than a second fetch.

    `song_position`/`song_length` (issue: UI overhaul round 2) let the
    read-only "Running order & assignments" table share its `#`/`Length`
    columns with the Setlist table's own `SetlistSong` shape, rather than
    this row's own `#` column meaning "position in tonight's Running
    Order" while the Setlist's meant "concert position" — both now name
    the Song's one Setlist position (ADR 0001's `Song` is semester-scoped,
    so there is only one).
    """
    return {
        'song_id': row.song.pk,
        'song_title': row.song.title,
        'song_artist': row.song.artist,
        'song_position': row.song.position,
        'song_length': format_song_length(row.song.length),
        'start_time': row.start_time.isoformat() if row.start_time else None,
        'rehearsal_song_id': row.rehearsal_song_id,
        'cells': [
            _serialize_matrix_cell(cell, is_admin=is_admin, conflicted_person_ids=conflicted_person_ids)
            for cell in row.cells
        ],
    }


def _serialize_available_song_option(option, *, is_admin, conflicted_person_ids) -> dict:
    """Return one `AvailableSongOption` for the Assignments table's song-swap dropdown (issue #406): identity plus its previewed cells.

    Each cell carries its own `role_name` (unlike `_serialize_matrix_cell`,
    which leaves a client to look the name up by `role_id` against the
    shared `roles` column list) — an option's cells cover only that Song's
    own Roles, which may include one the Rehearsal's *current* columns
    don't, so the client can render that column's header without a second
    read even before the swap is saved.
    """
    return {
        'id': option.song.pk,
        'title': option.song.title,
        'cells': [
            {
                'role_id': cell.role.pk,
                'role_name': cell.role.name,
                'entries': [
                    _serialize_matrix_entry(entry, is_admin=is_admin, conflicted_person_ids=conflicted_person_ids)
                    for entry in cell.entries
                ],
            }
            for cell in option.cells
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


def _serialize_your_song_entry(rehearsal_song) -> dict:
    """Return one `your_songs` entry: the Song's id and title only (issue: All-rehearsals per-date song list)."""
    return {'id': rehearsal_song.song.pk, 'title': rehearsal_song.song.title}


def _serialize_schedule_list_row(row, *, viewer, conflict_rows, is_admin, pending_counts, today) -> dict:
    """Return one `RehearsalListRow` for the All-rehearsals sub-view: identity, song count, the viewer's state, their songs, and (admin) a pending count.

    `your_songs`/`songs` both read off `row.songs`/`row.your_rehearsal_songs`
    — precomputed in bulk by `services.rehearsal_schedule_for()` for every
    Rehearsal in the Semester at once (issue #394), rather than this
    function re-deriving them per row via `assignment_matrix_for()`/
    `slots_for_person()` the way it used to (which made the All-rehearsals
    list's cost scale with the Semester's Rehearsal count). `your_songs`
    still carries the same union of standing assignments and Backups that
    decides attendance (ADR 0007) — so this list can never disagree with
    why the viewer is or isn't needed there — and `songs` is still the
    whole Rehearsal's Running Order in `RehearsalSong.order` sequence (the
    live setlist order for the Dress Rehearsal, ADR 0003), so this card can
    never disagree with the per-Rehearsal grid about what plays when.
    `availability` reuses `serialize_availability()` — the viewer's own
    Conflict only, never a teammate's (ADR 0005), same as the
    per-Rehearsal detail's "Your availability" block — so the card's "+
    Conflict" control can open the one Declare dialog in place with no
    second fetch. Conflict-declarability for this row is not a separate
    field: it's exactly `not is_dress and not is_past`, already carried by
    `_serialize_rehearsal_summary`, which is the same rule
    `future_rehearsals_for()`/`declare_conflict()` enforce (ADR 0006 — the
    Dress Rehearsal takes no Conflict; a past Rehearsal is not
    declarable).
    """
    rehearsal = row.rehearsal
    your_songs = sorted(row.your_rehearsal_songs, key=lambda rehearsal_song: rehearsal_song.song.position)
    data = {
        **_serialize_rehearsal_summary(rehearsal, today=today),
        'song_count': len(row.songs),
        'songs': [{'id': song.pk, 'title': song.title} for song in row.songs],
        'your_state': _serialize_your_state(rehearsal, conflict_rows.get(rehearsal.pk), row.attendance_suggestion),
        'availability': serialize_availability(rehearsal, conflict_rows.get(rehearsal.pk)),
        'your_songs': [_serialize_your_song_entry(rehearsal_song) for rehearsal_song in your_songs],
    }
    if is_admin and rehearsal.pk in pending_counts:
        data['pending_count'] = pending_counts[rehearsal.pk]
    return data


def _serialize_assignable_roster_entry(entry) -> dict:
    """Return one `AssignableRosterEntry`: the Person by name and their declared Role ids, for the "+" picker to derive candidates client-side (issue #399)."""
    return {
        'person_id': entry.person.pk,
        'person_name': entry.person.name,
        'declared_role_ids': sorted(entry.declared_role_ids),
    }


def _serialize_rehearsal_detail(rehearsal, *, viewer, is_admin, today) -> dict:
    """Return `/api/schedule/`'s "This rehearsal" sub-view detail for `rehearsal` (issue #331, #338).

    `can_edit_assignments` is the ADR-0009 gate: true only for an admin on
    an editable grid (`services.assignment_grid_is_editable()`), never
    re-derived by the client. Issue #439 removed the grid's ad-hoc "+ Add
    role" column control (and the `addable_roles` field that backed it):
    a Role becomes a matrix column only once an admin has added a
    SongRoleRequirement for it on the Song page, never client-side.
    `available_songs` (admin-only, absent on the Dress Rehearsal, which
    has no RehearsalSong row to swap — ADR-0003) is issue #406's
    song-swap dropdown source: every one of the Semester's setlist Songs,
    each already carrying the cells picking it would show, so a swap
    rerenders instantly with no second read of the grid either.
    `roster`/`conflicted_person_ids` (admin-only, issue #399) are the "+"
    picker's candidate source: paired with the matrix rows' own entries
    (who's already assigned/backed-up per cell), the client derives the
    whole picker with no per-cell fetch. Both are admin-only for the same
    reason: a non-admin viewer gets no Edit-assignments affordance at all
    (`can_edit_assignments`), and `conflicted_person_ids` — unlike the
    per-entry `has_conflict` marker every viewer already sees for an
    assigned/backed-up Person — would otherwise reveal which *unassigned*
    rostered Members declared a Conflict, a disclosure ADR-0005 reserves
    for admin-only surfaces.
    """
    matrix = services.assignment_matrix_for(rehearsal)
    roles = matrix.roles
    codes = services.role_codes_for(roles)
    conflicted_person_ids = set(
        Conflict.objects.filter(rehearsal=rehearsal).values_list('person_id', flat=True),
    )
    conflict_row = services.conflict_rows_by_rehearsal(rehearsal.semester, viewer).get(rehearsal.pk)
    data = {
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
    if is_admin:
        if not rehearsal.is_full_setlist:
            data['available_songs'] = [
                _serialize_available_song_option(option, is_admin=is_admin, conflicted_person_ids=conflicted_person_ids)
                for option in services.available_song_options_for(rehearsal)
            ]
        data['roster'] = [
            _serialize_assignable_roster_entry(entry)
            for entry in services.assignable_roster_for(rehearsal.semester)
        ]
        data['conflicted_person_ids'] = sorted(conflicted_person_ids)
    return data


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
                    row, viewer=viewer, conflict_rows=conflict_rows, is_admin=is_admin, pending_counts=pending_counts, today=today,
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


def _serialize_roster_entry(membership, *, is_admin: bool):
    """Return one Band-page row: `Person.name` (never the object, per `.name`-not-`Person` rule), declared Role names, and the annotated Song count (issue #333).

    Carries `invite_status` (issue #455) only for an admin viewer — every
    Membership is on this list regardless of invite state, so an admin
    needs a way to tell a not-yet-invited row apart from an active one;
    a non-admin viewer has no business seeing a teammate's invite
    lifecycle, per the "absent, not null" wire contract.
    """
    entry = {
        'id': membership.person_id,
        'name': membership.person.name,
        'roles': [person_role.role.name for person_role in membership.person.personrole_set.all()],
        'song_count': membership.songs_count,
    }
    if is_admin:
        entry['invite_status'] = invite_status_for(membership.person)
    return entry


def serialize_band(memberships, semester, *, unassigned_role_holders=None, is_admin: bool = False) -> dict:
    """Return the `/api/members/` `data` shape (issue #333): the viewing Semester's whole Roster, or the empty/no-Semester shape.

    Every Membership is included regardless of invite/password state
    (issue #455) — see `BandApiView`'s docstring for why. `is_admin` gates
    only the per-row `invite_status` key (see `_serialize_roster_entry`),
    not which rows appear.

    Carries one admin-only key, `unassigned_role_holders` — the count and
    names of people with a `SongRoleAssignment` this Semester but no
    `Membership` row (see `services.unassigned_role_holders_for`). Per the
    "absent, not null" wire contract, it's included only when the caller
    passes a queryset (an admin viewer); passing `None` (a member viewer,
    or no Semester) omits the key entirely rather than sending an empty
    list, since a member has no business seeing casting/roster gaps.
    Names are shown, not just a count — these are roster facts about who's
    cast, not the free-text Conflict data ADR 0005 restricts.

    `can_edit_roster` isn't needed on the wire since the "Edit roster"
    button is unconditionally rendered for an admin viewer by
    `context.viewer.is_admin`, matching how Setlist's "Edit setlist" button
    reads that same flag rather than a per-payload one.
    """
    if semester is None:
        return {'semester_name': None, 'member_count': 0, 'members': []}
    entries = list(memberships)
    data = {
        'semester_name': semester.name,
        'member_count': len(entries),
        'members': [_serialize_roster_entry(membership, is_admin=is_admin) for membership in entries],
    }
    if unassigned_role_holders is not None:
        holders = list(unassigned_role_holders)
        data['unassigned_role_holders'] = {
            'count': len(holders),
            'names': [person.name for person in holders],
        }
    return data


def _serialize_role(role) -> dict:
    """Return one Role as `id`/`name`, for a Person page's declared-Roles chips and its editable Role catalog (issue #333)."""
    return {'id': role.pk, 'name': role.name}


def _serialize_roster_edit_member(membership, *, mismatched_person_ids: frozenset[int]) -> dict:
    """Return one Roster editor row: name, Song count, mismatch flag and invite status (issue #336, narrowed by #379, tri-state by #397).

    No `email` (ADR 0005 — it stays off every Roster surface but the
    removal lines in the Save popup). No Role data at all (issue #379):
    the Roster editor is add/remove-only now, and a Person's declared
    Roles are set only on their Person page (#378). `is_role_mismatch` is
    the ADR 0002 soft flag, never a block; `invite_status` (issue #397) is
    `identity.services.invite_status_for()`'s three-way read, letting the
    editor show "not yet invited" / "invited · not active yet" and offer
    the right action for each without a second query per row.
    """
    return {
        'id': membership.person_id,
        'name': membership.person.name,
        'song_count': membership.songs_count,
        'is_role_mismatch': membership.person_id in mismatched_person_ids,
        'invite_status': invite_status_for(membership.person),
    }


def serialize_roster_edit(semester, memberships, *, mismatched_person_ids: frozenset[int]) -> dict:
    """Return the `/api/members/roster/` `data` shape (issue #336): every Membership in the viewing Semester, invited-but-inactive included.

    Like `serialize_band()` (issue #455), every Membership is included
    regardless of invite state — this view additionally needs to rename
    and offer "Invite again" on a not-yet-active Person, which
    `serialize_band()` doesn't need since it's read-only. Carries no
    `available_roles` (issue #379): the editor no longer offers any
    Role-editing control, so there is no Role catalog for it to pick from.
    """
    entries = list(memberships)
    active_count = sum(1 for membership in entries if membership.person.has_usable_password())
    return {
        'semester_id': semester.pk,
        'semester_updated_at': semester.updated_at.isoformat(),
        'active_count': active_count,
        'invited_count': len(entries) - active_count,
        'members': [
            _serialize_roster_edit_member(membership, mismatched_person_ids=mismatched_person_ids)
            for membership in entries
        ],
    }


def _serialize_roster_removal(removal) -> dict:
    """Return one `RosterRemoval`: the Person's name and email — the one place a Roster surface shows an email (ADR 0005, issue #228)."""
    return {'person_id': removal.person_id, 'name': removal.name, 'email': removal.email}


def serialize_roster_edit_fallout(fallout: RosterEditFallout) -> dict:
    """Return a `RosterEditFallout` as the `/api/members/roster/preview/` response's `fallout` value (issue #336).

    Named field-by-field like every other serializer here — `dataclasses.asdict()`
    is rejected on this surface specifically (issue #336's Implementation
    Decisions): `preview_roster_edits()` snapshots `Conflict` counts, and a
    blanket "emit every field" rule would ship a future Conflict-derived
    field to this member-facing payload with no test failing. The removal
    Conflict figure stays a count (`RosterEditFallout.loud`'s own wording),
    never a reason or a date (ADR 0005).
    """
    return {
        'is_blocked': fallout.is_blocked,
        'block_message': fallout.block_message,
        'is_stale': fallout.is_stale,
        'pending_adds': list(fallout.pending_adds),
        'pending_invites': list(fallout.pending_invites),
        'pending_added_without_invite': list(fallout.pending_added_without_invite),
        'pending_removals': [_serialize_roster_removal(removal) for removal in fallout.pending_removals],
        'loud': list(fallout.loud),
        'quiet': list(fallout.quiet),
    }


def _serialize_roster_edit_entry_echo(entry, index: int) -> dict:
    """Return one `RosterEditEntry` echoed back in `build_roster_buffer_from_request()`'s wire shape (issue #336, narrowed by #379).

    `row_key` isn't reconstructable from a `RosterEditEntry` (never stored
    on the Buffer, only used transiently to key a validation failure), so a
    successfully built Buffer's echo indexes positionally. No `role_ids`
    (issue #379) — this Buffer carries no Role data at all.
    """
    return {
        'row_key': f'entry-{index}',
        'person_id': entry.person.pk,
        'name': entry.name,
    }


def _serialize_roster_invite_echo(invite, index: int) -> dict:
    """Return one `RosterInvite` echoed back in `build_roster_buffer_from_request()`'s wire shape (issue #336)."""
    return {'row_key': f'invite-{index}', 'name': invite.name, 'email': invite.email}


def serialize_roster_edit_buffer(buffer: RosterEditBuffer) -> dict:
    """Return a `RosterEditBuffer` echoed back in `build_roster_buffer_from_request()`'s wire shape (issue #336).

    Used only by `/api/members/roster/preview/`'s `values` field on a
    successful build — every submitted value, normalized — never by
    `/api/members/roster/save/`, which drops `values` per #326's rule that
    a write response echoes nothing back.
    """
    return {
        'semester_id': buffer.semester_id,
        'semester_updated_at': buffer.semester_updated_at.isoformat() if buffer.semester_updated_at else None,
        'entries': [_serialize_roster_edit_entry_echo(entry, index) for index, entry in enumerate(buffer.entries)],
        'removed_person_ids': sorted(buffer.removed_person_ids),
        'invites': [_serialize_roster_invite_echo(invite, index) for index, invite in enumerate(buffer.pending_invites)],
    }


def _serialize_roster_import_candidate(candidate) -> dict:
    """Return one `RosterImportPerson`: the Person's name and their current, person-level declared Roles (ADR-0014, issue #336)."""
    return {
        'id': candidate.person.pk,
        'name': candidate.person.name,
        'roles': [_serialize_role(role) for role in candidate.roles],
    }


def _serialize_unrostered_person(person) -> dict:
    """Return one active, unrostered Person as a `+ Add people` sheet candidate: `id`/`name` only (issue #336)."""
    return {'id': person.pk, 'name': person.name}


def serialize_roster_candidates(proposal: RosterImportProposal, unrostered_people) -> dict:
    """Return the `/api/members/roster/candidates/` `data` shape (issue #336): the `+ Add people` sheet's two ticket-source lists.

    Answers a question rather than taking a Buffer, so per the envelope
    boundary rule (#307) this is its own shape, not the write envelope.
    `import_source_semester_name` is `None` when there is no prior
    Semester, backing the sheet's explanatory empty state (issue #336 user
    story 28) rather than a broken one.
    """
    return {
        'import_source_semester_name': proposal.source_semester.name if proposal.source_semester else None,
        'import_candidates': [_serialize_roster_import_candidate(candidate) for candidate in proposal.people],
        'unrostered_people': [_serialize_unrostered_person(person) for person in unrostered_people],
    }


def serialize_role_declaration(result: RoleCreationResult) -> dict:
    """Return the `/api/members/roster/roles/` `data` shape (issue #336): the Role plus whether it was created, matched or reactivated.

    Wraps `create_or_reactivate_role()` unchanged. Its own shape, not the
    write envelope, per the envelope boundary rule (#307) — this answers
    "what Role resulted from this name", it doesn't apply a Buffer.
    """
    return {
        'role': _serialize_role(result.role),
        'created': result.created,
        'reactivated': result.reactivated,
    }


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
    `songs` only when `person` holds a saved `Membership` in `semester` —
    the not-yet-rostered self case renders name, email and an editable
    Roles card (with no Songs section at all, never a zero — issue #333
    user stories 23-24). `roles` (issue #378, ADR-0014) is unconditional:
    a standing `PersonRole` declaration doesn't need a Membership to exist,
    so it renders even for a not-yet-rostered Person. Carries no
    `Conflict`, `Backup`, `is_role_mismatch` or attendance-inference field
    anywhere, for any viewer, including an admin (ADR 0005, ADR 0007, ADR
    0002) — the boundary is drawn around this surface, not the viewer.

    `invite_status` (issue #397) is present only for an admin viewing a
    teammate, never for `is_self` (a session implies a usable password, so
    it's always `'accepted'` with nothing useful to show or do) and never
    for a non-admin teammate viewer, per this same "absent, not null" rule.

    `is_admin` (issue #467, reversing `docs/person-page-visibility.md`'s
    old "never" verdict) is present under that identical condition —
    an admin viewing a teammate — so the same grant/revoke control this
    payload feeds can read the target's current status and never for
    `is_self` (an admin can't act on their own row, per
    `identity.services.apply_admin_status_change`'s self-revoke guard) or a
    non-admin teammate viewer, who has no business seeing anyone's admin
    status at all.
    """
    has_membership = membership is not None and membership.pk is not None
    data = {
        'id': person.pk,
        'name': person.name,
        'is_self': is_self,
        'can_edit_roles': can_edit_roles,
        'has_membership': has_membership,
        'semester_name': semester.name if semester is not None else None,
        'roles': [_serialize_role(role) for role in services.declared_roles_for_person(person)],
    }
    if is_self:
        data['email'] = person.email
    if can_edit_roles:
        data['available_roles'] = [_serialize_role(role) for role in services.active_roles_for(semester)]
    if not is_self and can_edit_roles:
        data['invite_status'] = invite_status_for(person)
        data['is_admin'] = person.is_admin
    if has_membership:
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


def _pinned_reasons_for(rehearsal_song, recording_counts) -> list[str]:
    """Return which of the two independent pin reasons apply to `rehearsal_song` (issue #223, #337): `recording`, `manual_slot_count`, both, or neither."""
    reasons = []
    if recording_counts.get(rehearsal_song.pk, 0) > 0:
        reasons.append('recording')
    if rehearsal_song.slot_count > 1:
        reasons.append('manual_slot_count')
    return reasons


def _serialize_running_order_row(rehearsal_song, recording_counts) -> dict:
    """Return one Running Order sub-grid row: its Song, slot, derived times, and (issue #223) why it's pinned, if it is."""
    reasons = _pinned_reasons_for(rehearsal_song, recording_counts)
    return {
        'rehearsal_song_id': rehearsal_song.pk,
        'song_id': rehearsal_song.song_id,
        'song_title': rehearsal_song.song.title,
        'slot_count': rehearsal_song.slot_count,
        'start_time': rehearsal_song.start_time.isoformat(),
        'end_time': rehearsal_song.end_time.isoformat(),
        'is_pinned': bool(reasons),
        'pinned_reasons': reasons,
    }


def _serialize_editable_rehearsal(rehearsal, running_order_rows, recording_counts) -> dict:
    """Return one editable-grid Rehearsal row: its own fields (never re-derived), and its Running Order sub-grid (issue #337)."""
    return {
        'id': rehearsal.pk,
        'date': rehearsal.date.isoformat(),
        'start_time': rehearsal.start_time.isoformat(),
        'end_time': rehearsal.end_time.isoformat() if rehearsal.end_time else None,
        'is_full_setlist': rehearsal.is_full_setlist,
        'setup_grace_minutes': rehearsal.setup_grace_minutes,
        'teardown_grace_minutes': rehearsal.teardown_grace_minutes,
        'arrival_buffer_minutes': rehearsal.arrival_buffer_minutes,
        'departure_buffer_minutes': rehearsal.departure_buffer_minutes,
        'running_order': [
            _serialize_running_order_row(rehearsal_song, recording_counts) for rehearsal_song in running_order_rows
        ],
    }


def _serialize_past_rehearsal(rehearsal, song_count: int) -> dict:
    """Return one read-only past-Rehearsal disclosure row: identity and window only, no inputs (issue #337)."""
    return {
        'id': rehearsal.pk,
        'date': rehearsal.date.isoformat(),
        'start_time': rehearsal.start_time.isoformat(),
        'end_time': rehearsal.end_time.isoformat() if rehearsal.end_time else None,
        'is_full_setlist': rehearsal.is_full_setlist,
        'song_count': song_count,
    }


def _serialize_editor_setlist_song(song) -> dict:
    """Return one "+ Add song" picker option: identity only, scoped to the viewing Semester's own setlist (ADR 0001)."""
    return {'id': song.pk, 'title': song.title, 'artist': song.artist, 'position': song.position}


def _serialize_semester_defaults(semester) -> dict:
    """Return the Semester's timing/slot defaults the editor needs to render "inherit" placeholders and the slot budget."""
    return {
        'default_rehearsal_duration_minutes': semester.default_rehearsal_duration_minutes,
        'default_setup_grace_minutes': semester.default_setup_grace_minutes,
        'default_teardown_grace_minutes': semester.default_teardown_grace_minutes,
        'default_song_slot_count': semester.default_song_slot_count,
        'default_arrival_buffer_minutes': semester.default_arrival_buffer_minutes,
        'default_departure_buffer_minutes': semester.default_departure_buffer_minutes,
        'default_dress_rehearsal_count': semester.default_dress_rehearsal_count,
    }


def _serialize_rehearsal_time_row(rehearsal_time) -> dict:
    """Return one saved Rehearsal Time as the Pattern editor's prefill shape."""
    return {
        'day_of_week': rehearsal_time.day_of_week,
        'start_time': rehearsal_time.start_time.isoformat(),
        'end_time': rehearsal_time.end_time.isoformat(),
    }


def _serialize_skip_date_row(skip_date) -> dict:
    """Return one saved Skip Date as the Pattern editor's prefill shape."""
    return {
        'start_date': skip_date.start_date.isoformat(),
        'end_date': skip_date.end_date.isoformat() if skip_date.end_date else None,
    }


def _serialize_rehearsal_pattern(pattern) -> dict | None:
    """Return `semester`'s saved RehearsalPattern as the modal's prefill shape, or `None` if it has never saved one."""
    if pattern is None:
        return None
    return {
        'start_date': pattern.start_date.isoformat(),
        'end_date': pattern.end_date.isoformat(),
        'rehearsal_times': [_serialize_rehearsal_time_row(rehearsal_time) for rehearsal_time in pattern.rehearsal_times.all()],
        'skip_dates': [_serialize_skip_date_row(skip_date) for skip_date in pattern.skip_dates.all()],
    }


def serialize_schedule_editor(semester) -> dict:
    """Return the `/api/schedule/editor/` `data` shape for `semester` (issue #337): one round trip for the whole rehearsal editor.

    Carries every future-or-today Rehearsal with its Running Order and
    per-row pinned flags, the read-only past-Rehearsal list (no inputs,
    the reason stated once client-side), the Semester's own setlist (for
    the Running Order "+ Add song" picker), its timing/slot defaults, and
    its saved RehearsalPattern (or `None`) for the generation modal's
    prefill. The Semester staleness stamp itself travels on `context`
    (`viewing_semester.updated_at`), not duplicated here.
    """
    if semester is None:
        return {
            'semester_name': None, 'rehearsals': [], 'past_rehearsals': [],
            'setlist_songs': [], 'semester_defaults': None, 'pattern': None,
        }
    today = timezone.localdate()
    rehearsals = list(
        Rehearsal.objects.filter(semester=semester, date__gte=today).order_by('date', 'start_time')
    )
    past_rehearsals = list(
        Rehearsal.objects.filter(semester=semester, date__lt=today).order_by('date', 'start_time')
    )
    rehearsal_ids = [rehearsal.pk for rehearsal in rehearsals]
    rehearsal_songs = list(
        RehearsalSong.objects.filter(rehearsal_id__in=rehearsal_ids)
        .select_related('song').order_by('rehearsal_id', 'order')
    )
    rows_by_rehearsal = defaultdict(list)
    for rehearsal_song in rehearsal_songs:
        rows_by_rehearsal[rehearsal_song.rehearsal_id].append(rehearsal_song)
    recording_counts = dict(
        Recording.objects.filter(rehearsal_song__rehearsal_id__in=rehearsal_ids)
        .values('rehearsal_song_id').annotate(count=Count('pk')).values_list('rehearsal_song_id', 'count')
    )
    past_song_counts = dict(
        RehearsalSong.objects.filter(rehearsal_id__in=[rehearsal.pk for rehearsal in past_rehearsals])
        .values('rehearsal_id').annotate(count=Count('pk')).values_list('rehearsal_id', 'count')
    )
    setlist_songs = Song.objects.filter(semester=semester).order_by('position')
    pattern = RehearsalPattern.objects.filter(semester=semester).prefetch_related(
        'rehearsal_times', 'skip_dates',
    ).first()
    return {
        'semester_name': semester.name,
        'rehearsals': [
            _serialize_editable_rehearsal(rehearsal, rows_by_rehearsal.get(rehearsal.pk, []), recording_counts)
            for rehearsal in rehearsals
        ],
        'past_rehearsals': [
            _serialize_past_rehearsal(rehearsal, past_song_counts.get(rehearsal.pk, 0))
            for rehearsal in past_rehearsals
        ],
        'setlist_songs': [_serialize_editor_setlist_song(song) for song in setlist_songs],
        'semester_defaults': _serialize_semester_defaults(semester),
        'pattern': _serialize_rehearsal_pattern(pattern),
    }


def _serialize_doomed_recording_group(group) -> dict:
    """Return one `DoomedRecordingGroup`: its label and counts only — never a Conflict, a name or a reason (ADR 0005)."""
    return {
        'label': group.label,
        'recording_count': group.recording_count,
        'uploader_count': group.uploader_count,
    }


def serialize_rehearsal_edit_fallout(fallout) -> dict:
    """Return a `RehearsalEditFallout` as the `/api/schedule/editor/preview/` response's `fallout` value (issue #337).

    Named field-by-field, matching `serialize_setlist_edit_fallout()` —
    `doomed_recording_groups` is what the Save popup's destructive block
    reads; there is no second, separately-fetched destructive-confirm
    endpoint (that dialog is deleted by this issue, per its spec).
    """
    return {
        'is_blocked': fallout.is_blocked,
        'block_message': fallout.block_message,
        'is_stale': fallout.is_stale,
        'loud': list(fallout.loud),
        'quiet': list(fallout.quiet),
        'doomed_recording_groups': [
            _serialize_doomed_recording_group(group) for group in fallout.doomed_recording_groups
        ],
    }


def _serialize_running_order_row_echo(row) -> dict:
    """Return one `RunningOrderRow` echoed back in `build_rehearsal_buffer_from_request()`'s wire shape."""
    return {'rehearsal_song_id': row.rehearsal_song_id, 'song_id': row.song_id, 'slot_count': row.slot_count}


def _serialize_rehearsal_edit_row_echo(row, index: int) -> dict:
    """Return one `RehearsalEditRow` echoed back in `build_rehearsal_buffer_from_request()`'s wire shape.

    `row_key` indexes positionally (`row-0`, `row-1`, ...), matching
    `_serialize_setlist_edit_row_echo()` — it was never stored on the
    Buffer, only used transiently to key a validation failure.
    """
    return {
        'row_key': f'row-{index}',
        'rehearsal_id': row.rehearsal_id,
        'date': row.date.isoformat(),
        'start_time': row.start_time.isoformat(),
        'end_time': row.end_time.isoformat() if row.end_time else None,
        'is_full_setlist': row.is_full_setlist,
        'setup_grace_minutes': row.setup_grace_minutes,
        'teardown_grace_minutes': row.teardown_grace_minutes,
        'arrival_buffer_minutes': row.arrival_buffer_minutes,
        'departure_buffer_minutes': row.departure_buffer_minutes,
        'running_order': [_serialize_running_order_row_echo(running_order_row) for running_order_row in row.running_order],
    }


def serialize_rehearsal_edit_buffer(buffer) -> dict:
    """Return a `RehearsalEditBuffer` echoed back in `build_rehearsal_buffer_from_request()`'s wire shape (issue #337).

    Used only by `/api/schedule/editor/preview/`'s `values` field on a
    successful build — `/api/schedule/editor/save/` drops `values` per
    #326's rule that a write response echoes nothing back.
    """
    return {
        'semester_id': buffer.semester_id,
        'semester_updated_at': buffer.semester_updated_at.isoformat() if buffer.semester_updated_at else None,
        'rows': [_serialize_rehearsal_edit_row_echo(row, index) for index, row in enumerate(buffer.rows)],
        'deleted_rehearsal_ids': sorted(buffer.deleted_rehearsal_ids),
    }


def _serialize_generation_create_item(item) -> dict:
    """Return one `GenerationCreateItem`: the date the Pattern would generate a brand-new Rehearsal for."""
    return {
        'date': item.date.isoformat(), 'start_time': item.start_time.isoformat(), 'end_time': item.end_time.isoformat(),
        'is_dress_rehearsal': item.is_dress_rehearsal,
    }


def _serialize_generation_keep_item(item) -> dict:
    """Return one `GenerationKeepItem`: a re-run's no-op case, whose existing Rehearsal already matches the Pattern."""
    return {
        'rehearsal_id': item.rehearsal_id, 'date': item.date.isoformat(),
        'start_time': item.start_time.isoformat(), 'end_time': item.end_time.isoformat(),
    }


def _serialize_generation_retime_item(item) -> dict:
    """Return one `GenerationRetimeItem`, with its blast radius (`song_count`/`conflict_count`) for the opt-in checkbox."""
    return {
        'rehearsal_id': item.rehearsal_id, 'date': item.date.isoformat(),
        'old_start_time': item.old_start_time.isoformat(), 'old_end_time': item.old_end_time.isoformat(),
        'new_start_time': item.new_start_time.isoformat(), 'new_end_time': item.new_end_time.isoformat(),
        'song_count': item.song_count, 'conflict_count': item.conflict_count,
    }


def _serialize_generation_orphan_item(item) -> dict:
    """Return one `GenerationOrphanItem`, including the computed `delete_disabled` gate for a Recording-carrying orphan."""
    return {
        'rehearsal_id': item.rehearsal_id, 'date': item.date.isoformat(),
        'start_time': item.start_time.isoformat(), 'end_time': item.end_time.isoformat(),
        'song_count': item.song_count, 'conflict_count': item.conflict_count,
        'recording_count': item.recording_count, 'delete_disabled': item.delete_disabled,
    }


def serialize_rehearsal_generation_diff(diff) -> dict:
    """Return a `RehearsalGenerationDiff` as the `/api/schedule/editor/generate/preview/` response's `data` value (issue #337).

    A pure read's answer, not a Pending-Buffer write — carries no
    `errors`/`fallout`/`values`, per #307's envelope boundary rule for an
    endpoint that answers a question rather than taking a Buffer.
    """
    return {
        'creates': [_serialize_generation_create_item(item) for item in diff.creates],
        'keeps': [_serialize_generation_keep_item(item) for item in diff.keeps],
        'retimes': [_serialize_generation_retime_item(item) for item in diff.retimes],
        'orphans': [_serialize_generation_orphan_item(item) for item in diff.orphans],
    }


def _serialize_dealt_row(row) -> dict:
    """Return one `DealtRow` proposed by the dealer/shuffle, mirroring `RunningOrderRow`'s wire shape."""
    return {'rehearsal_song_id': row.rehearsal_song_id, 'song_id': row.song_id, 'slot_count': row.slot_count}


def _serialize_dealt_rehearsal(dealt_rehearsal) -> dict:
    """Return one `DealtRehearsal`: its target Rehearsal and its proposed Running Order rows, in final order."""
    return {
        'rehearsal_id': dealt_rehearsal.rehearsal_id,
        'rows': [_serialize_dealt_row(row) for row in dealt_rehearsal.rows],
    }


def serialize_rehearsal_deal(deal) -> dict:
    """Return a `RehearsalDeal` as the `/api/schedule/editor/deal/` response's `data` value (issue #337, #223)."""
    return {'rehearsals': [_serialize_dealt_rehearsal(dealt_rehearsal) for dealt_rehearsal in deal.rehearsals]}


def serialize_shuffle_rows(rows) -> dict:
    """Return a shuffled `list[DealtRow]` as the per-Rehearsal shuffle endpoint's `data` value (issue #337, #223)."""
    return {'rows': [_serialize_dealt_row(row) for row in rows]}


def _serialize_song_slot_total(entry) -> dict:
    """Return one `SongSlotTotal` for the stats panel's busiest/quietest Song lists."""
    return {'song_id': entry.song_id, 'song_title': entry.song_title, 'total_slot_count': entry.total_slot_count}


def serialize_schedule_editor_live_stats(stats) -> dict:
    """Return a `ScheduleEditorLiveStats` as `/api/schedule/editor/stats/`'s `data` value.

    Named field-by-field, per this project's ban on `dataclasses.asdict()`
    (ADR 0005) — `old_max_wait_minutes`/`new_max_wait_minutes` pass through
    `None` untouched (JSON `null`) rather than being coerced to 0, so the
    panel can tell "no gap measured" from "measured, zero minutes".
    """
    return {
        'unresolved_conflict_count': stats.unresolved_conflict_count,
        'old_max_wait_minutes': stats.old_max_wait_minutes,
        'new_max_wait_minutes': stats.new_max_wait_minutes,
        'highest_slot_songs': [_serialize_song_slot_total(entry) for entry in stats.highest_slot_songs],
        'lowest_slot_songs': [_serialize_song_slot_total(entry) for entry in stats.lowest_slot_songs],
    }


def serialize_assignment_edit_fallout(fallout: AssignmentEditFallout) -> dict:
    """Return an `AssignmentEditFallout` as the assignment editor's `preview`/`save` response's `fallout` value (issue #338).

    Named field-by-field like `serialize_roster_edit_fallout()` — `loud`
    and `quiet` are already plain strings (`_assignment_fallout_lines()`
    never emits a `Conflict.reason` or an adjudication verdict, ADR 0005),
    so this is a straight pass-through rather than a per-line shape.
    """
    return {
        'is_blocked': fallout.is_blocked,
        'block_message': fallout.block_message,
        'is_stale': fallout.is_stale,
        'loud': list(fallout.loud),
        'quiet': list(fallout.quiet),
    }


def _serialize_assignment_edit_buffer_entry(entry) -> dict:
    """Return one `(song_id, role_id, person_id)` added-entry tuple as a named object."""
    song_id, role_id, person_id = entry
    return {'song_id': song_id, 'role_id': role_id, 'person_id': person_id}


def _serialize_assignment_edit_buffer_backup_entry(entry) -> dict:
    """Return one `(rehearsal_song_id, role_id, person_id, covering_for_id)` added-Backup-entry tuple as a named object."""
    rehearsal_song_id, role_id, person_id, covering_for_id = entry
    return {
        'rehearsal_song_id': rehearsal_song_id, 'role_id': role_id,
        'person_id': person_id, 'covering_for_id': covering_for_id,
    }


def _serialize_assignment_edit_buffer_covering_for_update(entry) -> dict:
    """Return one `(backup_id, covering_for_id)` pair as a named object."""
    backup_id, covering_for_id = entry
    return {'backup_id': backup_id, 'covering_for_id': covering_for_id}


def serialize_assignment_edit_buffer(buffer: AssignmentEditBuffer) -> dict:
    """Return an `AssignmentEditBuffer` echoed back in `build_assignment_buffer_from_request()`'s wire shape (issue #338).

    Used only by `/api/schedule/<id>/assignments/preview/`'s `values`
    field on a successful build (#308's amendment) — never by `.../save/`,
    which drops `values` per #326's rule that a write response echoes
    nothing back. Ordering within every list is stable but otherwise
    arbitrary — a `frozenset` carries no order of its own, and nothing
    downstream depends on one.
    """
    return {
        'semester_id': buffer.semester_id,
        'semester_updated_at': buffer.semester_updated_at.isoformat() if buffer.semester_updated_at else None,
        'removed_assignment_ids': sorted(buffer.removed_assignment_ids),
        'added_entries': [
            _serialize_assignment_edit_buffer_entry(entry) for entry in sorted(buffer.added_entries)
        ],
        'removed_backup_ids': sorted(buffer.removed_backup_ids),
        'added_backup_entries': [
            _serialize_assignment_edit_buffer_backup_entry(entry)
            for entry in sorted(buffer.added_backup_entries, key=lambda entry: entry[:3])
        ],
        'backup_covering_for_updates': [
            _serialize_assignment_edit_buffer_covering_for_update(entry)
            for entry in sorted(buffer.backup_covering_for_updates, key=lambda entry: entry[0])
        ],
    }


def _picker_conflicted_person_ids_for(rehearsal) -> set:
    """Return the set of Person ids with any Conflict against `rehearsal` (issue #338, user story 15).

    A marker only, never a reason, a declaration type or a time (ADR
    0005 / `_serialize_matrix_entry`'s `has_conflict`). Always empty for
    the Dress Rehearsal, which no Conflict may point at (ADR-0006), so
    this never runs a query that could only return nothing.
    """
    if rehearsal.is_full_setlist:
        return set()
    return set(Conflict.objects.filter(rehearsal=rehearsal).values_list('person_id', flat=True))


def _serialize_picker_option(option, *, conflicted_person_ids) -> dict:
    """Return one `AssignmentPickerOption`: the Person by name, whether they declared the cell's Role, and a bare conflict marker (issue #338, ADR 0005)."""
    return {
        'person_id': option.person.pk,
        'person_name': option.person.name,
        'has_declared_role': option.has_declared_role,
        'has_conflict': option.person.pk in conflicted_person_ids,
    }


def serialize_assignment_picker(picker: AssignmentPickerResult, rehearsal) -> dict:
    """Return an `AssignmentPickerResult` as `/api/schedule/<id>/assignments/picker/<song_id>/<role_id>/`'s `data` value (issue #338).

    Its own shape, not the write envelope: per #307's envelope boundary
    rule, the picker answers a question rather than taking a Pending
    Buffer, so it carries no `errors`/`values`/`fallout` fields that could
    never be populated. `backup_declared`/`backup_others` come back empty
    (with `rehearsal_song_id: None`) for the Dress Rehearsal — the client
    renders that as the structural "no per-song slots to assign against"
    explanation (ADR-0006), never as an empty list with no reason given.
    """
    conflicted_person_ids = _picker_conflicted_person_ids_for(rehearsal)
    return {
        'song_id': picker.song.pk,
        'song_title': picker.song.title,
        'role_id': picker.role.pk,
        'role_name': picker.role.name,
        'rehearsal_song_id': picker.rehearsal_song_id,
        'declared': [
            _serialize_picker_option(option, conflicted_person_ids=conflicted_person_ids) for option in picker.declared
        ],
        'others': [
            _serialize_picker_option(option, conflicted_person_ids=conflicted_person_ids) for option in picker.others
        ],
        'backup_declared': [
            _serialize_picker_option(option, conflicted_person_ids=conflicted_person_ids)
            for option in picker.backup_declared
        ],
        'backup_others': [
            _serialize_picker_option(option, conflicted_person_ids=conflicted_person_ids)
            for option in picker.backup_others
        ],
    }


def _serialize_adjudication_rehearsal_window(rehearsal) -> dict:
    """Return `rehearsal`'s `date`/`start_time`/`end_time` for the Conflict-adjudication surface (issue #340).

    A narrower cousin of `_serialize_rehearsal_summary()`: this surface's
    own key-set test asserts nothing beyond what each endpoint documents,
    so this deliberately omits `is_dress`/`is_past` rather than reusing
    that helper and pruning after the fact.
    """
    return {
        'date': rehearsal.date.isoformat(),
        'start_time': rehearsal.start_time.isoformat(),
        'end_time': rehearsal.end_time.isoformat() if rehearsal.end_time else None,
    }


def serialize_conflict_adjudication_index(rows: list) -> list:
    """Return `conflict_adjudication_index_for()`'s rows as `/api/conflicts/`'s `data.rows` value (issue #191, #340).

    One dict per Rehearsal: its window and its pending/approved/rejected
    Conflict counts — never a Person, a declaration, a reason or a note
    (ADR 0005). Admin-only surface, so nothing here needs an `is_admin`
    branch the way a member-facing serializer would.
    """
    return [
        {
            'rehearsal_id': row.rehearsal.pk,
            **_serialize_adjudication_rehearsal_window(row.rehearsal),
            'pending_count': row.pending_count,
            'approved_count': row.approved_count,
            'rejected_count': row.rejected_count,
        }
        for row in rows
    ]


def _serialize_conflict_feasibility_row(row, *, song_titles_by_id, role_names_by_id) -> dict:
    """Return one `ConflictFeasibilityRow` as a `feasibility` map entry, resolving the overlap Song/Role to display names (issue #194, #340).

    `overlap_song_title`/`overlap_role_name` are `None` whenever there is
    no standing overlap (`overlap_song_id`/`overlap_role_id` are also
    `None` then) — looked up from the caller's batched `song_titles_by_id`/
    `role_names_by_id` dicts rather than querying per row, avoiding an
    N+1 across a Rehearsal's whole Conflict table.
    """
    return {
        'checked': row.checked,
        'verdict': row.verdict,
        'has_standing_overlap': row.has_standing_overlap,
        'overlap_song_id': row.overlap_song_id,
        'overlap_role_id': row.overlap_role_id,
        'overlap_song_title': song_titles_by_id.get(row.overlap_song_id) if row.overlap_song_id else None,
        'overlap_role_name': role_names_by_id.get(row.overlap_role_id) if row.overlap_role_id else None,
    }


def _serialize_feasibility_map(feasibility_by_conflict_id: dict, *, song_titles_by_id, role_names_by_id) -> dict:
    """Return a `dict[int, ConflictFeasibilityRow]` as a JSON-safe `feasibility` map, keyed by the string Conflict id.

    JSON object keys are always strings, so `conflict_id` (an int on the
    Python side) is stringified here rather than asking every consumer of
    this map to remember to do it themselves.
    """
    return {
        str(conflict_id): _serialize_conflict_feasibility_row(
            row, song_titles_by_id=song_titles_by_id, role_names_by_id=role_names_by_id,
        )
        for conflict_id, row in feasibility_by_conflict_id.items()
    }


def _serialize_adjudication_detail_row(row) -> dict:
    """Return one `ConflictAdjudicationDetailRow` for `/api/conflicts/<rehearsal_id>/`'s `data.rows` value (issue #192, #340).

    Admin-only surface (ADR 0005): `person_name` and `reason` are
    legitimately present here, unlike the member-facing Schedule read.
    `note` reads `row.conflict.adjudication_note` directly — the dataclass
    itself carries no `note` field of its own, since `conflict_adjudication_rows_for()`
    is unchanged by this issue and its underlying `Conflict` instance
    already holds the value.
    """
    return {
        'conflict_id': row.conflict.pk,
        'person_id': row.person.pk,
        'person_name': row.person.name,
        'type_label': row.type_label,
        'declared_time': row.declared_time.isoformat() if row.declared_time else None,
        'reason': row.reason,
        'status': row.status,
        'note': row.conflict.adjudication_note,
    }


def serialize_conflict_adjudication_detail(
    rehearsal, detail_rows: list, feasibility_rows: list, *, semester, song_titles_by_id, role_names_by_id,
) -> dict:
    """Return `/api/conflicts/<rehearsal_id>/`'s whole page-shaped `data` value in one round trip (issue #192, #340).

    Per #307's one-round-trip rule: the Rehearsal's identity/window, the
    live `pending_count` (derived from `detail_rows`' own statuses, so it
    can never disagree with what `rows` shows), `semester_updated_at` (the
    stamp a submitted `AdjudicationBuffer` is checked against), every
    Conflict row, and the feasibility map computed against the *currently
    saved* statuses — the ambient read `_current_adjudication_fallout()`
    used to serve pre-SPA.
    """
    feasibility_by_conflict_id = {row.conflict_id: row for row in feasibility_rows}
    return {
        'rehearsal_id': rehearsal.pk,
        **_serialize_adjudication_rehearsal_window(rehearsal),
        'pending_count': sum(1 for row in detail_rows if row.status == Conflict.PENDING),
        'semester_updated_at': semester.updated_at.isoformat(),
        'rows': [_serialize_adjudication_detail_row(row) for row in detail_rows],
        'feasibility': _serialize_feasibility_map(
            feasibility_by_conflict_id, song_titles_by_id=song_titles_by_id, role_names_by_id=role_names_by_id,
        ),
    }


def serialize_adjudication_fallout(fallout, *, song_titles_by_id, role_names_by_id) -> dict:
    """Return an `AdjudicationFallout` as `/api/conflicts/<rehearsal_id>/preview/`'s `fallout` value (issue #194, #340).

    Mirrors `serialize_roster_edit_fallout()`'s shape: named field-by-field,
    never `dataclasses.asdict()`. `feasibility` uses the same string-keyed
    shape `serialize_conflict_adjudication_detail()`'s `feasibility` does,
    so a client can treat the ambient GET and the live Preview response
    identically.
    """
    return {
        'is_blocked': fallout.is_blocked,
        'block_message': fallout.block_message,
        'is_stale': fallout.is_stale,
        'loud': list(fallout.loud),
        'quiet': list(fallout.quiet),
        'feasibility': _serialize_feasibility_map(
            fallout.feasibility_by_conflict_id, song_titles_by_id=song_titles_by_id, role_names_by_id=role_names_by_id,
        ),
    }


def _serialize_next_rehearsal_card(card) -> dict:
    """Return a `NextRehearsalCard`: the Rehearsal's identity, the arrival/departure line, and the shared Timeline (issue #332)."""
    return {
        'rehearsal_id': card.rehearsal.pk,
        'date': card.rehearsal.date.isoformat(),
        'is_dress': card.rehearsal.is_full_setlist,
        'arrival_time': card.attendance_suggestion.arrival_time.isoformat(),
        'departure_time': card.attendance_suggestion.departure_time.isoformat(),
        'timeline': _serialize_timeline(card.timeline),
    }


def _serialize_upcoming_row(rehearsal, attendance_suggestion, *, today) -> dict:
    """Return one Upcoming-rehearsals row: identity plus `your_window`, null when `attendance_suggestion_for` is None (issue #332)."""
    return {
        **_serialize_rehearsal_summary(rehearsal, today=today),
        'your_window': (
            {
                'arrival_time': attendance_suggestion.arrival_time.isoformat(),
                'departure_time': attendance_suggestion.departure_time.isoformat(),
            }
            if attendance_suggestion is not None
            else None
        ),
    }


def _serialize_song_progress_row(song) -> dict:
    """Return one Song-progress row: identity, formatted length, the `song_rehearsal_progress` counts, notes and next rehearsal date."""
    return {
        'id': song.pk,
        'title': song.title,
        'artist': song.artist,
        'length': format_song_length(song.length),
        'position': song.position,
        'completed': song.progress.completed,
        'total': song.progress.total,
        'has_assignment': song.has_assignment,
        'notes': song.notes,
        'next_rehearsal': (
            song.next_rehearsal_date.isoformat() if song.next_rehearsal_date is not None else None
        ),
    }


def _serialize_setup_checklist_item(item) -> dict:
    """Return one `SetupChecklistItem`, field-by-field (issue #332)."""
    return {
        'key': item.key,
        'label': item.label,
        'is_done': item.is_done,
        'status': item.status,
        'destination': item.destination,
        'waiting_on': item.waiting_on,
    }


def serialize_home(request, semester) -> dict:
    """Return the `/api/` `data` shape (issue #332): Home's three member regions plus (admin, draft) the setup checklist.

    The setup-checklist block is included only for an admin viewing a
    draft Semester (null `published_at`, ADR 0010) with at least one item
    still not done — the panel disappears the moment nothing is empty,
    and a member payload never carries it at all. Reuses
    `next_rehearsal_card_for()`, `upcoming_rehearsals_for()`,
    `attendance_suggestion_for()` and `songs_with_progress_for()`
    unchanged; nothing here re-derives them. `just_created` fires the
    one-off "created / Draft" status card exactly once per Semester
    creation (`consume_just_created_semester()` pops the session marker
    unconditionally, so a member's read can never leave it dangling for a
    later admin read to wrongly consume).
    """
    viewer = request.user
    is_admin = bool(getattr(viewer, 'is_admin', False))
    if semester is None:
        services.consume_just_created_semester(request, None)
        return {
            'semester_name': None,
            'next_rehearsal': None,
            'upcoming_rehearsals': [],
            'song_progress': [],
            'setup_checklist': None,
            'just_created': False,
        }
    today = timezone.localdate()
    card = services.next_rehearsal_card_for(viewer, semester)
    upcoming = services.upcoming_rehearsals_for(semester, count=4)
    songs = services.songs_with_progress_for(semester, viewer)
    data = {
        'semester_name': semester.name,
        'next_rehearsal': _serialize_next_rehearsal_card(card) if card is not None else None,
        'upcoming_rehearsals': [
            _serialize_upcoming_row(rehearsal, services.attendance_suggestion_for(rehearsal, viewer), today=today)
            for rehearsal in upcoming
        ],
        'song_progress': [_serialize_song_progress_row(song) for song in songs],
        'setup_checklist': None,
        'just_created': services.consume_just_created_semester(request, semester) and is_admin,
    }
    if is_admin and semester.published_at is None:
        items = services.setup_checklist_for(semester)
        if any(not item.is_done for item in items):
            data['setup_checklist'] = {
                'semester_name': semester.name,
                'items': [_serialize_setup_checklist_item(item) for item in items],
            }
    return data
