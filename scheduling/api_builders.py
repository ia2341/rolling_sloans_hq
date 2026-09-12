"""JSON-body construction for the Setlist admin edit surface's Pending Buffer (issue #334, ADR 0008).

Pre-SPA, the Setlist edit grid's Save and Preview endpoints bound the
identical POST body to the identical `SetlistEditFormSet` via
`scheduling/views.py`'s `_build_setlist_buffer()`, so "preview and save
cannot disagree" came for free from binding one form twice. Once the
Buffer travels as JSON built by a React client, that free enforcement
disappears unless something plays the same role: `build_setlist_buffer_from_request()`
is the ONLY place that parses the setlist JSON body into a
`SetlistEditBuffer` — `/api/setlist/preview/` and `/api/setlist/save/`
both call it, never fork it, so a change to how a row parses can never
land in one endpoint without the other.

Wire shape (the API contract, not merely an implementation detail)::

    {
        "semester_id": 1,
        "semester_updated_at": "2026-01-01T00:00:00.000000+00:00",
        "rows": [
            {
                "row_key": "row-1",
                "song_id": 12,          # int, or null for a brand-new row
                "title": "...",
                "artist": "...",
                "length": "3:45",       # M:SS / H:MM:SS, exactly what a musician types
                "notes": "...",
                "role_group_counts": [  # issue #461; only for a brand-new row (song_id: null)
                    {"role_group_id": 3, "count": 2},
                    ...
                ]
            },
            ...
        ],
        "deleted_song_ids": [12, 13]
    }

`rows`' array order *is* the Buffer's final concert-position order — the
old FormSet's `song_order` token-permutation trick was a workaround for a
limitation (a formset's slot names can't be renamed on every drag) that a
plain JSON array doesn't have, so it is deliberately not reproduced here.
`row_key` is a client-generated, per-row-render key (stable across a
row's reorders/edits, never reused across rows in one submission) that
exists only so a validation failure can be reported and echoed
per-row — it is not persisted anywhere and has no relationship to
`song_id`.
"""

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils.dateparse import parse_date, parse_datetime, parse_time

from identity.models import Person
from scheduling.fields import parse_song_length
from scheduling.models import Conflict, RehearsalSong, Role, RoleGroup, Song
from scheduling.services import (
    AdjudicationBuffer,
    AdjudicationEntry,
    AssignmentEditBuffer,
    RehearsalEditBuffer,
    RehearsalEditRow,
    RehearsalPatternInput,
    RehearsalTimeInput,
    RosterEditBuffer,
    RosterEditEntry,
    RosterInvite,
    RunningOrderRow,
    SemesterDefaultsReapplyBuffer,
    SetlistEditBuffer,
    SetlistEditRow,
    SetlistRoleGroupCount,
    SkipDateInput,
    SongCastEditBuffer,
    SongRoleRequirementBuffer,
    SongRoleRequirementEntry,
)

#: Field-level messages shared by every row/field validation failure below.
_REQUIRED_MESSAGE = 'This field is required.'
_MUST_BE_INTEGER_MESSAGE = 'Enter a whole number.'
_MUST_BE_STRING_MESSAGE = 'Enter a string.'
_MUST_BE_LIST_MESSAGE = 'Expected a list.'
_MUST_BE_OBJECT_MESSAGE = 'Expected an object.'
_SONG_NOT_FOUND_MESSAGE = 'This song no longer exists in the current semester.'
_PERSON_NOT_FOUND_MESSAGE = 'This person could not be found.'
_UNKNOWN_ROLE_MESSAGE = 'This Role no longer exists.'
_INVALID_EMAIL_MESSAGE = 'Enter a valid email address.'
_EMAIL_TAKEN_MESSAGE = (
    'This person already has an account — tick them in "From members with an account" instead.'
)
_EMAIL_STAGED_TWICE_MESSAGE = 'This email is already staged for another invite.'
_UNKNOWN_STATUS_MESSAGE = 'status must be one of: pending, approved, rejected.'
_NOTE_MAX_LENGTH = 255
_NOTE_TOO_LONG_MESSAGE = f'Ensure this note has at most {_NOTE_MAX_LENGTH} characters.'
_COUNT_TOO_LOW_MESSAGE = 'A Requirement must target at least 1 person.'
_DUPLICATE_ROLE_MESSAGE = 'This Role already has a Requirement on this row — remove the duplicate.'
_UNKNOWN_ROLE_GROUP_MESSAGE = 'This Role Group no longer exists.'
_DUPLICATE_ROLE_GROUP_MESSAGE = 'This Role Group is already staged on this row — remove the duplicate.'
_ROLE_GROUP_NO_ACTIVE_ROLE_MESSAGE = 'This Role Group has no active Role to create a Requirement for.'
_ROLE_GROUP_COUNTS_ON_EXISTING_SONG_MESSAGE = (
    'Role Group counts can only be staged on a brand-new song — edit its Requirements instead.'
)


class SetlistBufferValidationError(ValidationError):
    """Raised by `build_setlist_buffer_from_request()` for a JSON body that can't become a `SetlistEditBuffer`.

    Deliberately not built on Django's `message_dict` machinery — that
    only flattens one level of field->messages, and this surface's errors
    are two levels deep (a row key, then a field name). Instead the
    structured payload a `/api/` view actually renders lives on two plain
    attributes set here:

    - `row_errors`: `{<row_key>: {<field>: [messages]}}`
    - `non_field_errors`: `[messages]` for anything not attributable to
      one row/field (a missing `semester_id`, an unparseable `rows` list,
      a duplicate `row_key`, an out-of-range `deleted_song_ids` entry).

    Also carries `raw_body` — the request's own parsed JSON body,
    untouched — so a Preview view can still echo every submitted value on
    a validation failure (issue #334 user story 18) even though
    normalization never finished long enough to build a
    `SetlistEditBuffer`. `raw_rows` is `raw_body['rows']` pulled out for
    convenience (or `[]` when `rows` itself wasn't a list).
    """

    def __init__(self, *, row_errors, non_field_errors, raw_rows, raw_body):
        """Store the structured failure shape and a human-readable summary message."""
        super().__init__('The submitted setlist edit could not be validated.')
        self.row_errors = row_errors
        self.non_field_errors = non_field_errors
        self.raw_rows = raw_rows
        self.raw_body = raw_body


def _expect_int(value):
    """Return `value` as an `int`, or `None` if it isn't cleanly one (bools are rejected: `True`/`1` must stay distinct)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _expect_string(value):
    """Return `value` unchanged if it's a `str`, else `None`."""
    return value if isinstance(value, str) else None


def build_setlist_buffer_from_request(request, *, viewing_semester) -> SetlistEditBuffer:
    """Parse `request`'s JSON body into a `SetlistEditBuffer` (issue #334).

    Delegates the body-parsing itself to `ApiView.parse_json_body()` — a
    plain function of `request` with no other dependency on `self`, so
    calling it off an unbound `ApiView` instance is safe and keeps JSON
    decoding in exactly one place project-wide. A malformed body raises
    `MalformedPayloadError`, which `ApiView.dispatch()` already turns into
    the documented JSON 400 — this function doesn't catch it.

    `viewing_semester` is accepted (rather than read internally) so this
    function stays a pure translation of one request body into one
    Buffer, with no `services.get_viewing_semester()` call of its own.
    It scopes the one row-level existence check this function does perform:
    each row's non-null `song_id` must name a `Song` that actually belongs
    to `viewing_semester`, mirroring the pre-SPA formset's
    `_scoped_to_viewing_semester(Song, semester)` queryset binding — a
    stale or foreign-semester `song_id` is reported as a per-row
    `SetlistBufferValidationError` here rather than reaching
    `_apply_setlist_edit_row()`'s `Song.objects.get()` and raising
    `Song.DoesNotExist` (issue #334 PR #345 review).

    Raises `SetlistBufferValidationError` (a `ValidationError` subclass)
    carrying `row_errors`/`non_field_errors`/`raw_rows` for anything this
    function cannot turn into a well-formed Buffer. Does not check
    `semester_id` against `viewing_semester` itself — that is
    `WrongViewingSemesterError` territory, raised by `apply_setlist_edits()`/
    `preview_setlist_edits()` themselves, a genuine 4xx rather than a
    per-row Validation Error (issue #334).
    """
    from config.views import ApiView

    body = ApiView().parse_json_body(request)

    non_field_errors = []
    raw_body = body if isinstance(body, dict) else {}
    raw_rows = raw_body.get('rows') if isinstance(raw_body.get('rows'), list) else []

    if not isinstance(body, dict):
        non_field_errors.append('Expected a JSON object.')
        raise SetlistBufferValidationError(
            row_errors={}, non_field_errors=non_field_errors, raw_rows=raw_rows, raw_body=raw_body
        )

    semester_id = _expect_int(body.get('semester_id'))
    if semester_id is None:
        non_field_errors.append('semester_id is required and must be an integer.')

    semester_updated_at = None
    raw_stamp = body.get('semester_updated_at')
    if not isinstance(raw_stamp, str) or not raw_stamp:
        non_field_errors.append('semester_updated_at is required and must be an ISO datetime string.')
    else:
        try:
            semester_updated_at = parse_datetime(raw_stamp)
        except ValueError:
            semester_updated_at = None
        if semester_updated_at is None:
            non_field_errors.append('semester_updated_at could not be parsed as an ISO datetime.')

    rows_raw = body.get('rows')
    if not isinstance(rows_raw, list):
        non_field_errors.append('rows must be a list.')
        rows_raw = []

    deleted_song_ids_raw = body.get('deleted_song_ids', [])
    deleted_song_ids = set()
    if not isinstance(deleted_song_ids_raw, list):
        non_field_errors.append('deleted_song_ids must be a list.')
    else:
        for entry in deleted_song_ids_raw:
            song_id = _expect_int(entry)
            if song_id is None:
                non_field_errors.append(f'deleted_song_ids contains a non-integer value: {entry!r}.')
            else:
                deleted_song_ids.add(song_id)

    candidate_song_ids = set()
    for raw_row in rows_raw:
        if isinstance(raw_row, dict) and raw_row.get('song_id') is not None:
            candidate_song_id = _expect_int(raw_row.get('song_id'))
            if candidate_song_id is not None:
                candidate_song_ids.add(candidate_song_id)
    existing_song_ids = set(
        Song.objects.filter(semester=viewing_semester, pk__in=candidate_song_ids).values_list('pk', flat=True)
    ) if candidate_song_ids else set()

    candidate_role_group_ids = set()
    for raw_row in rows_raw:
        if not isinstance(raw_row, dict):
            continue
        role_group_counts_raw = raw_row.get('role_group_counts') or []
        if not isinstance(role_group_counts_raw, list):
            continue
        for raw_count in role_group_counts_raw:
            if isinstance(raw_count, dict):
                candidate_role_group_id = _expect_int(raw_count.get('role_group_id'))
                if candidate_role_group_id is not None:
                    candidate_role_group_ids.add(candidate_role_group_id)
    existing_role_group_ids = set(
        RoleGroup.objects.filter(pk__in=candidate_role_group_ids).values_list('pk', flat=True)
    ) if candidate_role_group_ids else set()
    role_group_ids_with_an_active_role = set(
        Role.objects.filter(
            group_id__in=existing_role_group_ids, is_active=True,
        ).values_list('group_id', flat=True).distinct()
    ) if existing_role_group_ids else set()

    row_errors = {}
    seen_row_keys = set()
    rows = []
    for index, raw_row in enumerate(rows_raw):
        row_key = raw_row.get('row_key') if isinstance(raw_row, dict) else None
        if not isinstance(row_key, str) or not row_key:
            row_key = f'row-{index}'
        if row_key in seen_row_keys:
            non_field_errors.append(f'Duplicate row_key: {row_key}.')
        seen_row_keys.add(row_key)

        if not isinstance(raw_row, dict):
            row_errors[row_key] = {'row': [_MUST_BE_OBJECT_MESSAGE]}
            continue

        field_errors: dict[str, list[str]] = {}

        song_id = None
        if raw_row.get('song_id') is not None:
            song_id = _expect_int(raw_row.get('song_id'))
            if song_id is None:
                field_errors.setdefault('song_id', []).append(_MUST_BE_INTEGER_MESSAGE)
            elif song_id not in existing_song_ids:
                field_errors.setdefault('song_id', []).append(_SONG_NOT_FOUND_MESSAGE)

        title = _expect_string(raw_row.get('title'))
        if title is None:
            field_errors.setdefault('title', []).append(_MUST_BE_STRING_MESSAGE)
        elif not title.strip():
            field_errors.setdefault('title', []).append(_REQUIRED_MESSAGE)

        artist = _expect_string(raw_row.get('artist'))
        if artist is None:
            field_errors.setdefault('artist', []).append(_MUST_BE_STRING_MESSAGE)
        elif not artist.strip():
            field_errors.setdefault('artist', []).append(_REQUIRED_MESSAGE)

        notes = raw_row.get('notes', '')
        if notes is None:
            notes = ''
        if not isinstance(notes, str):
            field_errors.setdefault('notes', []).append(_MUST_BE_STRING_MESSAGE)
            notes = ''

        length = None
        raw_length = raw_row.get('length')
        if not isinstance(raw_length, str) or not raw_length.strip():
            field_errors.setdefault('length', []).append(_REQUIRED_MESSAGE)
        else:
            try:
                length = parse_song_length(raw_length)
            except ValidationError as error:
                field_errors.setdefault('length', []).extend(error.messages)

        role_group_counts_raw = raw_row.get('role_group_counts') or []
        role_group_counts = []
        if not isinstance(role_group_counts_raw, list):
            field_errors.setdefault('role_group_counts', []).append(_MUST_BE_LIST_MESSAGE)
        elif role_group_counts_raw and song_id is not None:
            field_errors.setdefault('role_group_counts', []).append(_ROLE_GROUP_COUNTS_ON_EXISTING_SONG_MESSAGE)
        else:
            seen_role_group_ids = set()
            for count_index, raw_count in enumerate(role_group_counts_raw):
                count_key = f'role_group_counts.{count_index}'
                if not isinstance(raw_count, dict):
                    field_errors.setdefault(count_key, []).append(_MUST_BE_OBJECT_MESSAGE)
                    continue

                role_group_id = _expect_int(raw_count.get('role_group_id'))
                if role_group_id is None:
                    field_errors.setdefault(f'{count_key}.role_group_id', []).append(_MUST_BE_INTEGER_MESSAGE)
                elif role_group_id not in existing_role_group_ids:
                    field_errors.setdefault(f'{count_key}.role_group_id', []).append(_UNKNOWN_ROLE_GROUP_MESSAGE)
                elif role_group_id in seen_role_group_ids:
                    field_errors.setdefault(f'{count_key}.role_group_id', []).append(_DUPLICATE_ROLE_GROUP_MESSAGE)
                elif role_group_id not in role_group_ids_with_an_active_role:
                    field_errors.setdefault(f'{count_key}.role_group_id', []).append(_ROLE_GROUP_NO_ACTIVE_ROLE_MESSAGE)

                group_count = _expect_int(raw_count.get('count'))
                if group_count is None:
                    field_errors.setdefault(f'{count_key}.count', []).append(_MUST_BE_INTEGER_MESSAGE)
                elif group_count < 1:
                    field_errors.setdefault(f'{count_key}.count', []).append(_COUNT_TOO_LOW_MESSAGE)

                if role_group_id is not None and group_count is not None:
                    seen_role_group_ids.add(role_group_id)
                    role_group_counts.append(
                        SetlistRoleGroupCount(role_group_id=role_group_id, count=group_count)
                    )

        if field_errors:
            row_errors[row_key] = field_errors
            continue

        rows.append(SetlistEditRow(
            song_id=song_id,
            title=title.strip(),
            artist=artist.strip(),
            length=length,
            notes=notes,
            role_group_counts=tuple(role_group_counts),
        ))

    if row_errors or non_field_errors:
        raise SetlistBufferValidationError(
            row_errors=row_errors, non_field_errors=non_field_errors, raw_rows=raw_rows, raw_body=raw_body
        )

    return SetlistEditBuffer(
        semester_id=semester_id,
        semester_updated_at=semester_updated_at,
        rows=rows,
        deleted_song_ids=frozenset(deleted_song_ids),
    )


class RehearsalBufferValidationError(ValidationError):
    """Raised by `build_rehearsal_buffer_from_request()` for a JSON body that can't become a `RehearsalEditBuffer` (issue #337).

    Mirrors `SetlistBufferValidationError`'s shape exactly — `row_errors`
    (`{<row_key>: {<field>: [messages]}}`), `non_field_errors` (a flat
    list), and `raw_body` (the request's own parsed JSON, untouched) — so
    a Preview view can still echo every submitted value on a validation
    failure even though normalization never finished. A Running Order
    sub-row's malformed shape (a non-integer `song_id`/`slot_count`) is
    reported under its parent row's `row_key`, keyed `'running_order'`,
    rather than getting its own nested `row_key` — the sub-grid has no
    independent identity of its own on this wire shape, unlike a Setlist
    row.
    """

    def __init__(self, *, row_errors, non_field_errors, raw_rows, raw_body):
        """Store the structured failure shape and a human-readable summary message."""
        super().__init__('The submitted rehearsal edit could not be validated.')
        self.row_errors = row_errors
        self.non_field_errors = non_field_errors
        self.raw_rows = raw_rows
        self.raw_body = raw_body


def _expect_bool(value):
    """Return `value` as a `bool`, or `None` if it isn't cleanly one."""
    return value if isinstance(value, bool) else None


def _expect_nullable_int(value, field_errors, field_name):
    """Return `value` as an `int`, `None` for a JSON `null`, or append `field_name`'s message to `field_errors` and return `False` (a sentinel meaning "drop this row")."""
    if value is None:
        return None
    result = _expect_int(value)
    if result is None:
        field_errors.setdefault(field_name, []).append(_MUST_BE_INTEGER_MESSAGE)
        return False
    return result


def _parse_running_order(raw_running_order, field_errors):
    """Return a list of `RunningOrderRow` parsed from `raw_running_order`, appending to `field_errors['running_order']` for any malformed entry.

    Shape-only validation: whether a `song_id` actually belongs to the
    Buffer's own Semester is `apply_rehearsal_edits()`'s
    `RunningOrderValidationError` territory (a hard Validation Error, per
    issue #337's spec), not a per-row field error this builder computes
    itself — unlike `build_setlist_buffer_from_request()`'s `song_id`
    check, there is no per-row echo need here to justify duplicating it.
    """
    if not isinstance(raw_running_order, list):
        field_errors.setdefault('running_order', []).append(_MUST_BE_LIST_MESSAGE)
        return []

    rows = []
    for entry in raw_running_order:
        if not isinstance(entry, dict):
            field_errors.setdefault('running_order', []).append(_MUST_BE_OBJECT_MESSAGE)
            continue
        song_id = _expect_int(entry.get('song_id'))
        if song_id is None:
            field_errors.setdefault('running_order', []).append('song_id must be an integer.')
            continue
        slot_count = _expect_int(entry.get('slot_count'))
        if slot_count is None or slot_count < 1:
            field_errors.setdefault('running_order', []).append('slot_count must be a positive integer.')
            continue
        rehearsal_song_id = entry.get('rehearsal_song_id')
        if rehearsal_song_id is not None:
            rehearsal_song_id = _expect_int(rehearsal_song_id)
            if rehearsal_song_id is None:
                field_errors.setdefault('running_order', []).append('rehearsal_song_id must be an integer or null.')
                continue
        rows.append(RunningOrderRow(rehearsal_song_id=rehearsal_song_id, song_id=song_id, slot_count=slot_count))
    return rows


def build_rehearsal_buffer_from_request(request, *, viewing_semester) -> RehearsalEditBuffer:
    """Parse `request`'s JSON body into a `RehearsalEditBuffer` (issue #337).

    The ONE place a submitted schedule-editor JSON body becomes a
    `RehearsalEditBuffer` — `/api/schedule/editor/preview/` and
    `/api/schedule/editor/save/` both call this, never a forked parsing
    path (ADR 0008's "preview and save cannot disagree" rule).

    Wire shape::

        {
            "semester_id": 1,
            "semester_updated_at": "2026-01-01T00:00:00.000000+00:00",
            "rows": [
                {
                    "row_key": "row-1",
                    "rehearsal_id": 5,          # int, or null for a brand-new row
                    "date": "2026-03-10",
                    "start_time": "19:00",
                    "end_time": "21:00",        # or null (Rehearsal.save() derives it)
                    "is_full_setlist": false,
                    "setup_grace_minutes": null,        # null means "inherit the Semester default"
                    "teardown_grace_minutes": null,
                    "arrival_buffer_minutes": null,
                    "departure_buffer_minutes": null,
                    "running_order": [
                        {"rehearsal_song_id": 10, "song_id": 3, "slot_count": 1},
                        ...
                    ]
                },
                ...
            ],
            "deleted_rehearsal_ids": [7, 8]
        }

    `row_key` exists only so a validation failure can be reported and
    echoed per-row (mirroring `build_setlist_buffer_from_request()`); it is
    never persisted and has no relationship to `rehearsal_id`. `end_time`
    is the one field allowed to reach a `RehearsalEditRow` as `None` — only
    legal for a brand-new row, matching `Rehearsal.save()`'s own
    defaulting. Delegates body-parsing itself to `ApiView.parse_json_body()`,
    matching `build_setlist_buffer_from_request()`.

    Raises `RehearsalBufferValidationError` for anything this function
    cannot turn into a well-formed Buffer. Does not check `semester_id`
    against `viewing_semester`, and does not check a row's `date` against
    today, or a Running Order's Song against the Semester's own setlist —
    all three are `apply_rehearsal_edits()`/`preview_rehearsal_edits()`
    territory (`WrongViewingSemesterError`, `PastRehearsalEditError`,
    `RunningOrderValidationError`), reported as hard Validation Errors
    rather than per-row field errors, per issue #337's spec.
    """
    from config.views import ApiView

    body = ApiView().parse_json_body(request)

    non_field_errors = []
    raw_body = body if isinstance(body, dict) else {}
    raw_rows = raw_body.get('rows') if isinstance(raw_body.get('rows'), list) else []

    if not isinstance(body, dict):
        non_field_errors.append('Expected a JSON object.')
        raise RehearsalBufferValidationError(
            row_errors={}, non_field_errors=non_field_errors, raw_rows=raw_rows, raw_body=raw_body
        )

    semester_id = _expect_int(body.get('semester_id'))
    if semester_id is None:
        non_field_errors.append('semester_id is required and must be an integer.')

    semester_updated_at = None
    raw_stamp = body.get('semester_updated_at')
    if not isinstance(raw_stamp, str) or not raw_stamp:
        non_field_errors.append('semester_updated_at is required and must be an ISO datetime string.')
    else:
        try:
            semester_updated_at = parse_datetime(raw_stamp)
        except ValueError:
            semester_updated_at = None
        if semester_updated_at is None:
            non_field_errors.append('semester_updated_at could not be parsed as an ISO datetime.')

    rows_raw = body.get('rows')
    if not isinstance(rows_raw, list):
        non_field_errors.append('rows must be a list.')
        rows_raw = []

    deleted_ids_raw = body.get('deleted_rehearsal_ids', [])
    deleted_rehearsal_ids = []
    if not isinstance(deleted_ids_raw, list):
        non_field_errors.append('deleted_rehearsal_ids must be a list.')
    else:
        for entry in deleted_ids_raw:
            rehearsal_id = _expect_int(entry)
            if rehearsal_id is None:
                non_field_errors.append(f'deleted_rehearsal_ids contains a non-integer value: {entry!r}.')
            else:
                deleted_rehearsal_ids.append(rehearsal_id)

    row_errors = {}
    seen_row_keys = set()
    rows = []
    for index, raw_row in enumerate(rows_raw):
        row_key = raw_row.get('row_key') if isinstance(raw_row, dict) else None
        if not isinstance(row_key, str) or not row_key:
            row_key = f'row-{index}'
        if row_key in seen_row_keys:
            non_field_errors.append(f'Duplicate row_key: {row_key}.')
        seen_row_keys.add(row_key)

        if not isinstance(raw_row, dict):
            row_errors[row_key] = {'row': [_MUST_BE_OBJECT_MESSAGE]}
            continue

        field_errors: dict[str, list[str]] = {}

        rehearsal_id = None
        if raw_row.get('rehearsal_id') is not None:
            rehearsal_id = _expect_int(raw_row.get('rehearsal_id'))
            if rehearsal_id is None:
                field_errors.setdefault('rehearsal_id', []).append(_MUST_BE_INTEGER_MESSAGE)

        parsed_date = None
        raw_date = raw_row.get('date')
        if not isinstance(raw_date, str) or not raw_date:
            field_errors.setdefault('date', []).append(_REQUIRED_MESSAGE)
        else:
            parsed_date = parse_date(raw_date)
            if parsed_date is None:
                field_errors.setdefault('date', []).append('Enter a valid date (YYYY-MM-DD).')

        start_time = None
        raw_start_time = raw_row.get('start_time')
        if not isinstance(raw_start_time, str) or not raw_start_time:
            field_errors.setdefault('start_time', []).append(_REQUIRED_MESSAGE)
        else:
            start_time = parse_time(raw_start_time)
            if start_time is None:
                field_errors.setdefault('start_time', []).append('Enter a valid time (HH:MM).')

        end_time = None
        raw_end_time = raw_row.get('end_time')
        if raw_end_time is not None:
            if not isinstance(raw_end_time, str) or not raw_end_time:
                field_errors.setdefault('end_time', []).append('Enter a valid time (HH:MM), or null.')
            else:
                end_time = parse_time(raw_end_time)
                if end_time is None:
                    field_errors.setdefault('end_time', []).append('Enter a valid time (HH:MM).')

        is_full_setlist = _expect_bool(raw_row.get('is_full_setlist', False))
        if is_full_setlist is None:
            field_errors.setdefault('is_full_setlist', []).append('Enter a boolean.')

        override_values = {}
        for field_name in (
            'setup_grace_minutes', 'teardown_grace_minutes', 'arrival_buffer_minutes', 'departure_buffer_minutes',
        ):
            value = _expect_nullable_int(raw_row.get(field_name), field_errors, field_name)
            override_values[field_name] = None if value is False else value

        running_order = _parse_running_order(raw_row.get('running_order', []), field_errors)

        if field_errors:
            row_errors[row_key] = field_errors
            continue

        rows.append(RehearsalEditRow(
            rehearsal_id=rehearsal_id,
            date=parsed_date,
            start_time=start_time,
            end_time=end_time,
            is_full_setlist=is_full_setlist,
            setup_grace_minutes=override_values['setup_grace_minutes'],
            teardown_grace_minutes=override_values['teardown_grace_minutes'],
            arrival_buffer_minutes=override_values['arrival_buffer_minutes'],
            departure_buffer_minutes=override_values['departure_buffer_minutes'],
            running_order=running_order,
        ))

    if row_errors or non_field_errors:
        raise RehearsalBufferValidationError(
            row_errors=row_errors, non_field_errors=non_field_errors, raw_rows=raw_rows, raw_body=raw_body
        )

    return RehearsalEditBuffer(
        semester_id=semester_id,
        semester_updated_at=semester_updated_at,
        rows=rows,
        deleted_rehearsal_ids=deleted_rehearsal_ids,
    )


def build_rehearsal_reorder_buffer_from_request(request, *, rehearsal) -> RehearsalEditBuffer:
    """Parse a pure Running Order reorder request into a one-row `RehearsalEditBuffer` for `rehearsal` (the Schedule surface's "Edit Rehearsal" drag-and-drop).

    Unlike `build_rehearsal_buffer_from_request()` (the bulk multi-Rehearsal
    editor, which submits every `RehearsalEditRow` field explicitly), this
    endpoint's caller only ever submits the new order of `rehearsal`'s
    already-existing `RehearsalSong` rows. Every other `RehearsalEditRow`
    field — `date`, `start_time`, `end_time`, `is_full_setlist`, and each
    of the four overrides — and each Running Order row's own `slot_count`
    are read fresh off the database rather than the request body, so a
    reorder-only save can never silently change a slot_count or reset an
    override to the Semester default the way a hand-crafted body naming
    them explicitly could.

    Wire shape::

        {
            "semester_id": 1,
            "semester_updated_at": "2026-01-01T00:00:00.000000+00:00",
            "ordered_rehearsal_song_ids": [10, 7, 12],
            "song_overrides": [{"rehearsal_song_id": 10, "song_id": 4}]
        }

    `song_overrides` (issue #406's song-swap dropdown) is optional and
    defaults to empty: each entry substitutes a different `song_id` for one
    of `ordered_rehearsal_song_ids`' existing rows, everything else about
    that row (`slot_count`, its position in the order) still read fresh off
    the database exactly as an un-overridden row's `song_id` is. It changes
    what a slot *is*, never how many slots exist or their sequence, so it
    piggybacks on this endpoint rather than earning a second one.

    Raises `RehearsalBufferValidationError` (with no per-row `row_errors`,
    since there is only ever the one row here — everything lands in
    `non_field_errors`) for a missing/malformed `semester_id` or
    `semester_updated_at`, a non-list `ordered_rehearsal_song_ids`, a list
    that doesn't name *exactly* `rehearsal`'s current RehearsalSong ids once
    each — no id dropped, added, or duplicated — or a malformed
    `song_overrides` entry (non-integer fields, or a `rehearsal_song_id` not
    among `rehearsal`'s own rows) — since anything else can't be turned into
    a well-formed reorder of what's actually there. A `song_id` naming a
    Song outside the viewing Semester's setlist is instead refused by
    `apply_rehearsal_edits()`'s own check, shared with every other caller
    that submits a Running Order.
    """
    from config.views import ApiView

    body = ApiView().parse_json_body(request)

    non_field_errors = []
    raw_body = body if isinstance(body, dict) else {}

    if not isinstance(body, dict):
        non_field_errors.append('Expected a JSON object.')
        raise RehearsalBufferValidationError(
            row_errors={}, non_field_errors=non_field_errors, raw_rows=[], raw_body=raw_body
        )

    semester_id = _expect_int(body.get('semester_id'))
    if semester_id is None:
        non_field_errors.append('semester_id is required and must be an integer.')

    semester_updated_at = None
    raw_stamp = body.get('semester_updated_at')
    if not isinstance(raw_stamp, str) or not raw_stamp:
        non_field_errors.append('semester_updated_at is required and must be an ISO datetime string.')
    else:
        try:
            semester_updated_at = parse_datetime(raw_stamp)
        except ValueError:
            semester_updated_at = None
        if semester_updated_at is None:
            non_field_errors.append('semester_updated_at could not be parsed as an ISO datetime.')

    raw_ids = body.get('ordered_rehearsal_song_ids')
    ordered_ids = []
    if not isinstance(raw_ids, list):
        non_field_errors.append('ordered_rehearsal_song_ids must be a list.')
    else:
        for entry in raw_ids:
            rehearsal_song_id = _expect_int(entry)
            if rehearsal_song_id is None:
                non_field_errors.append(f'ordered_rehearsal_song_ids contains a non-integer value: {entry!r}.')
            else:
                ordered_ids.append(rehearsal_song_id)

    raw_overrides = body.get('song_overrides', [])
    song_overrides = {}
    if not isinstance(raw_overrides, list):
        non_field_errors.append('song_overrides must be a list.')
    else:
        for entry in raw_overrides:
            if not isinstance(entry, dict):
                non_field_errors.append(f'song_overrides contains a non-object value: {entry!r}.')
                continue
            override_rehearsal_song_id = _expect_int(entry.get('rehearsal_song_id'))
            override_song_id = _expect_int(entry.get('song_id'))
            if override_rehearsal_song_id is None or override_song_id is None:
                non_field_errors.append(f'song_overrides entry is missing an integer rehearsal_song_id/song_id: {entry!r}.')
                continue
            song_overrides[override_rehearsal_song_id] = override_song_id

    if non_field_errors:
        raise RehearsalBufferValidationError(
            row_errors={}, non_field_errors=non_field_errors, raw_rows=[], raw_body=raw_body
        )

    existing = list(RehearsalSong.objects.filter(rehearsal=rehearsal))
    existing_by_id = {rehearsal_song.pk: rehearsal_song for rehearsal_song in existing}
    if len(ordered_ids) != len(existing) or set(ordered_ids) != set(existing_by_id):
        raise RehearsalBufferValidationError(
            row_errors={},
            non_field_errors=[
                "ordered_rehearsal_song_ids must name exactly this Rehearsal's current Running Order rows, once each — reload and reapply.",
            ],
            raw_rows=[], raw_body=raw_body,
        )

    if any(rehearsal_song_id not in existing_by_id for rehearsal_song_id in song_overrides):
        raise RehearsalBufferValidationError(
            row_errors={},
            non_field_errors=[
                "song_overrides names a RehearsalSong id outside this Rehearsal's current Running Order rows — reload and reapply.",
            ],
            raw_rows=[], raw_body=raw_body,
        )

    running_order = [
        RunningOrderRow(
            rehearsal_song_id=rehearsal_song_id,
            song_id=song_overrides.get(rehearsal_song_id, existing_by_id[rehearsal_song_id].song_id),
            slot_count=existing_by_id[rehearsal_song_id].slot_count,
        )
        for rehearsal_song_id in ordered_ids
    ]

    row = RehearsalEditRow(
        rehearsal_id=rehearsal.pk,
        date=rehearsal.date,
        start_time=rehearsal.start_time,
        end_time=rehearsal.end_time,
        is_full_setlist=rehearsal.is_full_setlist,
        setup_grace_minutes=rehearsal.setup_grace_minutes,
        teardown_grace_minutes=rehearsal.teardown_grace_minutes,
        arrival_buffer_minutes=rehearsal.arrival_buffer_minutes,
        departure_buffer_minutes=rehearsal.departure_buffer_minutes,
        running_order=running_order,
    )
    return RehearsalEditBuffer(semester_id=semester_id, semester_updated_at=semester_updated_at, rows=[row])


class RehearsalPatternInputError(ValidationError):
    """Raised by `build_rehearsal_pattern_input_from_body()` for a JSON body that can't become a `RehearsalPatternInput` (issue #337).

    Shared by the Pattern-save endpoint and the generation-diff endpoint,
    matching `save_rehearsal_pattern()`/`preview_rehearsal_generation()`'s
    own shared `_check_no_rehearsal_time_collisions()` — both surfaces bind
    the identical wire shape the identical way. Carries only
    `non_field_errors`: unlike `RehearsalEditBuffer`'s per-row shape, a
    Pattern has no natural "row" a client renders more than one of in a
    way that needs independent per-row keying on this surface.
    """

    def __init__(self, *, non_field_errors):
        """Store the flat failure message list."""
        super().__init__('The submitted rehearsal pattern could not be validated.')
        self.non_field_errors = non_field_errors


def _parse_pattern_date(raw_value, errors, field_name):
    """Return `raw_value` parsed as a date, or append `field_name`'s message to `errors` and return `None`."""
    if not isinstance(raw_value, str) or not raw_value:
        errors.append(f'{field_name} is required and must be an ISO date string.')
        return None
    parsed = parse_date(raw_value)
    if parsed is None:
        errors.append(f'{field_name} could not be parsed as a date.')
    return parsed


def build_rehearsal_pattern_input_from_body(body) -> RehearsalPatternInput:
    """Parse a JSON body into a `RehearsalPatternInput` (issue #337, #222).

    The one place the generate-rehearsal-dates modal's submitted shape
    becomes a `RehearsalPatternInput` — the Pattern-save endpoint and the
    generation-diff endpoint both call this. Raises
    `RehearsalPatternInputError` for anything malformed; does not itself
    check for a day-of-week collision between two `rehearsal_times`
    entries — `save_rehearsal_pattern()`/`preview_rehearsal_generation()`'s
    shared `_check_no_rehearsal_time_collisions()` already raises
    `RehearsalPatternCollisionError` for that, and this function has no
    reason to duplicate it.

    Wire shape::

        {
            "start_date": "2026-01-01",
            "end_date": "2026-05-01",
            "rehearsal_times": [{"day_of_week": 2, "start_time": "19:00", "end_time": "21:00"}],
            "skip_dates": [{"start_date": "2026-03-10", "end_date": "2026-03-17"}]
        }
    """
    errors: list[str] = []
    if not isinstance(body, dict):
        raise RehearsalPatternInputError(non_field_errors=['Expected a JSON object.'])

    start_date = _parse_pattern_date(body.get('start_date'), errors, 'start_date')
    end_date = _parse_pattern_date(body.get('end_date'), errors, 'end_date')

    rehearsal_times = []
    raw_times = body.get('rehearsal_times', [])
    if not isinstance(raw_times, list):
        errors.append('rehearsal_times must be a list.')
    else:
        for entry in raw_times:
            if not isinstance(entry, dict):
                errors.append('Each rehearsal_times entry must be an object.')
                continue
            day_of_week = _expect_int(entry.get('day_of_week'))
            if day_of_week is None or not (0 <= day_of_week <= 6):
                errors.append('Each rehearsal_times entry needs day_of_week as an integer 0-6.')
                continue
            raw_start_time = entry.get('start_time')
            raw_end_time = entry.get('end_time')
            start_time = parse_time(raw_start_time) if isinstance(raw_start_time, str) else None
            end_time = parse_time(raw_end_time) if isinstance(raw_end_time, str) else None
            if start_time is None or end_time is None:
                errors.append('Each rehearsal_times entry needs valid start_time/end_time.')
                continue
            rehearsal_times.append(RehearsalTimeInput(day_of_week=day_of_week, start_time=start_time, end_time=end_time))

    skip_dates = []
    raw_skip_dates = body.get('skip_dates', [])
    if not isinstance(raw_skip_dates, list):
        errors.append('skip_dates must be a list.')
    else:
        for entry in raw_skip_dates:
            if not isinstance(entry, dict):
                errors.append('Each skip_dates entry must be an object.')
                continue
            raw_start = entry.get('start_date')
            skip_start = parse_date(raw_start) if isinstance(raw_start, str) else None
            if skip_start is None:
                errors.append('Each skip_dates entry needs a valid start_date.')
                continue
            raw_end = entry.get('end_date')
            skip_end = None
            if raw_end is not None:
                skip_end = parse_date(raw_end) if isinstance(raw_end, str) else None
                if skip_end is None:
                    errors.append('A skip_dates entry needs a valid end_date, or null.')
                    continue
            skip_dates.append(SkipDateInput(start_date=skip_start, end_date=skip_end))

    if errors:
        raise RehearsalPatternInputError(non_field_errors=errors)

    return RehearsalPatternInput(
        start_date=start_date, end_date=end_date, rehearsal_times=rehearsal_times, skip_dates=skip_dates,
    )


def build_generation_date_range_from_body(body):
    """Return `(start_date, end_date)` from an optional `date_range` block in a generation-diff request body, or `None` (issue #337, #222).

    Narrows a single generation run without touching the stored Pattern
    (CONTEXT.md's Rehearsal Pattern). `date_range` is optional; when absent
    or `null`, `preview_rehearsal_generation()` falls back to the Pattern's
    own `(start_date, end_date)`.
    """
    raw_range = body.get('date_range') if isinstance(body, dict) else None
    if raw_range is None:
        return None
    if not isinstance(raw_range, dict):
        raise RehearsalPatternInputError(non_field_errors=['date_range must be an object, or null.'])
    errors: list[str] = []
    start_date = _parse_pattern_date(raw_range.get('start_date'), errors, 'date_range.start_date')
    end_date = _parse_pattern_date(raw_range.get('end_date'), errors, 'date_range.end_date')
    if errors:
        raise RehearsalPatternInputError(non_field_errors=errors)
    return (start_date, end_date)


class RosterBufferValidationError(ValidationError):
    """Raised by `build_roster_buffer_from_request()` for a JSON body that can't become a `RosterEditBuffer` (issue #336).

    Mirrors `SetlistBufferValidationError`'s shape: `row_errors`
    (`{<row_key>: {<field>: [messages]}}`, shared across `entries` and
    `invites` rows since every row — hand-edited or staged from the `+ Add`
    sheet — carries one client-generated `row_key`) and `non_field_errors`
    (`[messages]` for anything not attributable to one row/field). Also
    carries `raw_body` — the request's own parsed JSON body, untouched —
    so a Preview view can still echo every submitted value on a validation
    failure even though normalization never finished long enough to build
    a `RosterEditBuffer`.
    """

    def __init__(self, *, row_errors, non_field_errors, raw_body):
        """Store the structured failure shape and a human-readable summary message."""
        super().__init__('The submitted roster edit could not be validated.')
        self.row_errors = row_errors
        self.non_field_errors = non_field_errors
        self.raw_body = raw_body


def build_roster_buffer_from_request(request, *, viewing_semester) -> RosterEditBuffer:
    """Parse `request`'s JSON body into a `RosterEditBuffer` (issue #336).

    The ONE place a submitted Roster edit JSON body becomes a
    `RosterEditBuffer` — `/api/members/roster/preview/` and
    `/api/members/roster/save/` both call it, never fork it, mirroring
    `build_setlist_buffer_from_request()`'s ADR-0008 "preview and save
    cannot disagree" guarantee. Collapses what was, pre-SPA, two divergent
    buffer-building helpers (the edit formset alone for Preview, the edit
    formset plus a separate add-list formset for Save) into one path that
    always sees the whole submission.

    Wire shape (no Role data — issue #379 narrowed this Buffer to
    add/remove-only; a Person's declared Roles are set only on their
    Person page, #378)::

        {
            "semester_id": 1,
            "semester_updated_at": "2026-01-01T00:00:00.000000+00:00",
            "entries": [
                {"row_key": "row-1", "person_id": 5, "name": "..."}
            ],
            "removed_person_ids": [7, 8],
            "invites": [
                {"row_key": "invite-1", "name": "...", "email": "..."}
            ]
        }

    `row_key` is a client-generated, per-row-render key (never reused
    across `entries` or `invites` in one submission) that exists only so a
    validation failure can be reported and echoed per-row; it is not
    persisted anywhere. `entries`' `person_id` is checked for existence but
    not for Roster membership — an entry may name a Person newly added
    from the `+ Add` sheet's other two sections, who holds no Membership
    in `viewing_semester` yet. An `invites` row's email is rejected here
    (a per-row Validation Error, never `apply_roster_edits()`'s problem) if
    it already belongs to an existing Person or is staged twice in the same
    submission — the one duplicate-email check this surface needs, since
    `Person.email`'s own uniqueness constraint would otherwise surface as
    an unhandled `IntegrityError` deep inside the apply.

    Does not check `semester_id` against `viewing_semester`, nor
    `removed_person_ids` against the requesting admin's own pk — both stay
    `WrongViewingSemesterError`/`SelfRemovalError` territory, raised by
    `apply_roster_edits()`/`preview_roster_edits()` themselves.
    """
    from config.views import ApiView

    body = ApiView().parse_json_body(request)

    non_field_errors = []
    raw_body = body if isinstance(body, dict) else {}

    if not isinstance(body, dict):
        non_field_errors.append('Expected a JSON object.')
        raise RosterBufferValidationError(row_errors={}, non_field_errors=non_field_errors, raw_body=raw_body)

    semester_id = _expect_int(body.get('semester_id'))
    if semester_id is None:
        non_field_errors.append('semester_id is required and must be an integer.')

    semester_updated_at = None
    raw_stamp = body.get('semester_updated_at')
    if not isinstance(raw_stamp, str) or not raw_stamp:
        non_field_errors.append('semester_updated_at is required and must be an ISO datetime string.')
    else:
        try:
            semester_updated_at = parse_datetime(raw_stamp)
        except ValueError:
            semester_updated_at = None
        if semester_updated_at is None:
            non_field_errors.append('semester_updated_at could not be parsed as an ISO datetime.')

    entries_raw = body.get('entries')
    if not isinstance(entries_raw, list):
        non_field_errors.append('entries must be a list.')
        entries_raw = []

    removed_raw = body.get('removed_person_ids', [])
    removed_person_ids = set()
    if not isinstance(removed_raw, list):
        non_field_errors.append('removed_person_ids must be a list.')
    else:
        for value in removed_raw:
            person_id = _expect_int(value)
            if person_id is None:
                non_field_errors.append(f'removed_person_ids contains a non-integer value: {value!r}.')
            else:
                removed_person_ids.add(person_id)

    invites_raw = body.get('invites', [])
    if not isinstance(invites_raw, list):
        non_field_errors.append('invites must be a list.')
        invites_raw = []

    row_errors = {}
    seen_row_keys = set()

    candidate_person_ids = set()
    for raw_entry in entries_raw:
        if not isinstance(raw_entry, dict):
            continue
        candidate_person_id = _expect_int(raw_entry.get('person_id'))
        if candidate_person_id is not None:
            candidate_person_ids.add(candidate_person_id)

    people_by_id = Person.objects.in_bulk(candidate_person_ids)

    entries = []
    for index, raw_entry in enumerate(entries_raw):
        row_key = raw_entry.get('row_key') if isinstance(raw_entry, dict) else None
        if not isinstance(row_key, str) or not row_key:
            row_key = f'entry-{index}'
        if row_key in seen_row_keys:
            non_field_errors.append(f'Duplicate row_key: {row_key}.')
        seen_row_keys.add(row_key)

        if not isinstance(raw_entry, dict):
            row_errors[row_key] = {'row': [_MUST_BE_OBJECT_MESSAGE]}
            continue

        field_errors: dict[str, list[str]] = {}

        person_id = _expect_int(raw_entry.get('person_id'))
        if person_id is None:
            field_errors.setdefault('person_id', []).append(_MUST_BE_INTEGER_MESSAGE)
        elif person_id not in people_by_id:
            field_errors.setdefault('person_id', []).append(_PERSON_NOT_FOUND_MESSAGE)

        name = _expect_string(raw_entry.get('name'))
        if name is None:
            field_errors.setdefault('name', []).append(_MUST_BE_STRING_MESSAGE)
        elif not name.strip():
            field_errors.setdefault('name', []).append(_REQUIRED_MESSAGE)

        if field_errors:
            row_errors[row_key] = field_errors
            continue

        entries.append(RosterEditEntry(person=people_by_id[person_id], name=name.strip()))

    existing_emails = {
        email.lower() for email in Person.objects.values_list('email', flat=True)
    }
    seen_invite_emails = set()

    invites = []
    for index, raw_invite in enumerate(invites_raw):
        row_key = raw_invite.get('row_key') if isinstance(raw_invite, dict) else None
        if not isinstance(row_key, str) or not row_key:
            row_key = f'invite-{index}'
        if row_key in seen_row_keys:
            non_field_errors.append(f'Duplicate row_key: {row_key}.')
        seen_row_keys.add(row_key)

        if not isinstance(raw_invite, dict):
            row_errors[row_key] = {'row': [_MUST_BE_OBJECT_MESSAGE]}
            continue

        field_errors = {}

        name = _expect_string(raw_invite.get('name'))
        if name is None:
            field_errors.setdefault('name', []).append(_MUST_BE_STRING_MESSAGE)
        elif not name.strip():
            field_errors.setdefault('name', []).append(_REQUIRED_MESSAGE)

        email = None
        raw_email = _expect_string(raw_invite.get('email'))
        if raw_email is None:
            field_errors.setdefault('email', []).append(_MUST_BE_STRING_MESSAGE)
        elif not raw_email.strip():
            field_errors.setdefault('email', []).append(_REQUIRED_MESSAGE)
        else:
            candidate_email = raw_email.strip()
            try:
                validate_email(candidate_email)
            except ValidationError:
                field_errors.setdefault('email', []).append(_INVALID_EMAIL_MESSAGE)
            else:
                normalized = candidate_email.lower()
                if normalized in existing_emails:
                    field_errors.setdefault('email', []).append(_EMAIL_TAKEN_MESSAGE)
                elif normalized in seen_invite_emails:
                    field_errors.setdefault('email', []).append(_EMAIL_STAGED_TWICE_MESSAGE)
                else:
                    seen_invite_emails.add(normalized)
                    email = candidate_email

        if field_errors:
            row_errors[row_key] = field_errors
            continue

        invites.append(RosterInvite(name=name.strip(), email=email))

    if row_errors or non_field_errors:
        raise RosterBufferValidationError(row_errors=row_errors, non_field_errors=non_field_errors, raw_body=raw_body)

    return RosterEditBuffer(
        semester_id=semester_id,
        semester_updated_at=semester_updated_at,
        entries=entries,
        removed_person_ids=frozenset(removed_person_ids),
        pending_invites=invites,
    )

class AssignmentBufferValidationError(ValidationError):
    """Raised by `build_assignment_buffer_from_request()` for a JSON body that can't become an `AssignmentEditBuffer` (issue #338).

    Simpler than `RosterBufferValidationError`/`SetlistBufferValidationError`:
    every field here is an id, or a flat tuple of ids, never a per-row
    edit a client renders back beside one input — there is no `row_key`
    to attribute a failure to, so a malformed submission is reported as
    `non_field_errors` alone.
    """

    def __init__(self, *, non_field_errors):
        """Store the submission-wide failure messages."""
        super().__init__('The submitted assignment edit could not be validated.')
        self.non_field_errors = non_field_errors


def _assignment_expect_nullable_int(value):
    """Return `value` as an `int`, or `None` for a JSON `null` or anything else that doesn't cleanly parse.

    Unlike `_expect_nullable_int()`, a malformed value here is dropped to
    `None` rather than raising a field error — `covering_for_id` is
    advisory (ADR-0007), so a garbled pick is worth losing on its own,
    never worth failing the whole submission over.
    """
    if value is None:
        return None
    return _expect_int(value)


def _parse_assignment_id_set(raw_values):
    """Return the subset of `raw_values` that parse as ints, as a `frozenset` (issue #338, mirrors `_parse_assignment_ids()`)."""
    if not isinstance(raw_values, list):
        return frozenset()
    return frozenset(parsed for value in raw_values if (parsed := _expect_int(value)) is not None)


def _parse_added_cast_entries(raw_values):
    """Return `raw_values` as a `frozenset` of `(role_id, person_id)` tuples, dropping any malformed entry (issue #499).

    The Song-level cast Buffer's adds carry no `song_id` of their own —
    the whole Buffer describes one Song, named once from the URL.
    """
    if not isinstance(raw_values, list):
        return frozenset()
    entries = set()
    for entry in raw_values:
        if not isinstance(entry, dict):
            continue
        role_id = _expect_int(entry.get('role_id'))
        person_id = _expect_int(entry.get('person_id'))
        if role_id is None or person_id is None:
            continue
        entries.add((role_id, person_id))
    return frozenset(entries)


def _parse_added_backup_entries(raw_values):
    """Return `raw_values` as a `frozenset` of `(rehearsal_song_id, role_id, person_id, covering_for_id)` tuples (issue #338).

    `covering_for_id` may be `null` (ADR-0007: recording it is a choice,
    never a demand) — dropped to `None` the same way
    `_assignment_expect_nullable_int()` drops a garbled one.
    """
    if not isinstance(raw_values, list):
        return frozenset()
    entries = set()
    for entry in raw_values:
        if not isinstance(entry, dict):
            continue
        rehearsal_song_id = _expect_int(entry.get('rehearsal_song_id'))
        role_id = _expect_int(entry.get('role_id'))
        person_id = _expect_int(entry.get('person_id'))
        if rehearsal_song_id is None or role_id is None or person_id is None:
            continue
        covering_for_id = _assignment_expect_nullable_int(entry.get('covering_for_id'))
        entries.add((rehearsal_song_id, role_id, person_id, covering_for_id))
    return frozenset(entries)


def _parse_backup_covering_for_updates(raw_values):
    """Return `raw_values` as a `frozenset` of `(backup_id, covering_for_id)` pairs, dropping any entry with no usable `backup_id` (issue #338)."""
    if not isinstance(raw_values, list):
        return frozenset()
    updates = set()
    for entry in raw_values:
        if not isinstance(entry, dict):
            continue
        backup_id = _expect_int(entry.get('backup_id'))
        if backup_id is None:
            continue
        covering_for_id = _assignment_expect_nullable_int(entry.get('covering_for_id'))
        updates.add((backup_id, covering_for_id))
    return frozenset(updates)


def build_assignment_buffer_from_request(request, *, viewing_semester) -> AssignmentEditBuffer:
    """Parse `request`'s JSON body into a Backup-only `AssignmentEditBuffer` (issue #338, ADR-0019).

    The ONE place a submitted Rehearsal-grid edit JSON body becomes an
    `AssignmentEditBuffer` — `/api/schedule/<id>/assignments/preview/`
    and `/api/schedule/<id>/assignments/save/` both call it, never fork
    it, mirroring `build_setlist_buffer_from_request()`'s ADR-0008 "preview
    and save cannot disagree" guarantee.

    Wire shape::

        {
            "semester_id": 1,
            "semester_updated_at": "2026-01-01T00:00:00.000000+00:00",
            "removed_backup_ids": [4],
            "added_backup_entries": [
                {"rehearsal_song_id": 5, "role_id": 2, "person_id": 6, "covering_for_id": null}
            ],
            "backup_covering_for_updates": [{"backup_id": 7, "covering_for_id": 8}]
        }

    `removed_assignment_ids` and `added_entries` are deliberately **not
    read at all** since ADR-0019 moved casting to the Song-level surface —
    not merely ignored downstream. A stale tab or a hand-crafted POST can
    still send them; never reading the keys is what makes them inert,
    rather than relying on a Buffer field that happens to be unused.

    Every id list/entry is shape-checked only — whether a
    `rehearsal_song_id`, `role_id`, `person_id` or Backup id actually
    names a live row `buffer` can touch is `apply_rehearsal_backups()`'s
    job, which already silently skips anything outside
    `viewing_semester`/`rehearsal`. Only a missing/malformed
    `semester_id` or `semester_updated_at` — both required for either
    staleness check to run at all — raises
    `AssignmentBufferValidationError`.
    """
    from config.views import ApiView

    body = ApiView().parse_json_body(request)
    if not isinstance(body, dict):
        raise AssignmentBufferValidationError(non_field_errors=['Expected a JSON object.'])

    non_field_errors = []

    semester_id = _expect_int(body.get('semester_id'))
    if semester_id is None:
        non_field_errors.append('semester_id is required and must be an integer.')

    semester_updated_at = None
    raw_stamp = body.get('semester_updated_at')
    if not isinstance(raw_stamp, str) or not raw_stamp:
        non_field_errors.append('semester_updated_at is required and must be an ISO datetime string.')
    else:
        semester_updated_at = parse_datetime(raw_stamp)
        if semester_updated_at is None:
            non_field_errors.append('semester_updated_at could not be parsed as an ISO datetime.')

    if non_field_errors:
        raise AssignmentBufferValidationError(non_field_errors=non_field_errors)

    return AssignmentEditBuffer(
        semester_id=semester_id,
        semester_updated_at=semester_updated_at,
        removed_backup_ids=_parse_assignment_id_set(body.get('removed_backup_ids', [])),
        added_backup_entries=_parse_added_backup_entries(body.get('added_backup_entries', [])),
        backup_covering_for_updates=_parse_backup_covering_for_updates(body.get('backup_covering_for_updates', [])),
    )


class SemesterDefaultsReapplyBufferValidationError(ValidationError):
    """Raised by `build_semester_defaults_reapply_buffer_from_request()` for a JSON body that can't become a `SemesterDefaultsReapplyBuffer` (issue #329).

    This surface has no per-row shape (`SemesterDefaultsReapplyBuffer`
    carries only a Semester identity, per its own docstring), so unlike
    `SetlistBufferValidationError`/`RosterBufferValidationError` there is
    no `row_errors` here — only `non_field_errors`, echoed by the Preview
    endpoint the same way the row-shaped surfaces echo theirs.
    """

    def __init__(self, *, non_field_errors):
        """Store the flat list of validation messages."""
        super().__init__('The submitted reapply-defaults request could not be validated.')
        self.non_field_errors = non_field_errors


def build_semester_defaults_reapply_buffer_from_request(request, *, viewing_semester) -> SemesterDefaultsReapplyBuffer:
    """Parse `request`'s JSON body into a `SemesterDefaultsReapplyBuffer` (issue #329).

    The simplest Buffer builder in the module: `SemesterDefaultsReapplyBuffer`
    carries only `semester_id`/`semester_updated_at` (issue #291's bulk
    action reads everything else straight off the Semester's already-
    persisted `default_*` fields and its existing Rehearsals), so there is
    no row-level parsing to do. `viewing_semester` is accepted, not read
    internally, for the same reason every other builder here takes it —
    to stay a pure translation of one request body into one Buffer — but
    is otherwise unused: this action is addressed by `semester_id` alone,
    the way `SemesterPublishView`/`SemesterDeleteView` are, with no
    session-scoped Viewing Semester ambiguity to check here (that stays
    `WrongViewingSemesterError`-shaped territory this surface doesn't
    have, since its target is always the `semester_id` in the body).

    Wire shape::

        {
            "semester_id": 1,
            "semester_updated_at": "2026-01-01T00:00:00.000000+00:00"
        }

    Raises `SemesterDefaultsReapplyBufferValidationError` for a missing or
    non-integer `semester_id`, or a missing/unparseable
    `semester_updated_at` — mirroring the other builders'
    `semester_updated_at` parsing exactly.
    """
    from config.views import ApiView

    body = ApiView().parse_json_body(request)

    non_field_errors = []
    if not isinstance(body, dict):
        raise SemesterDefaultsReapplyBufferValidationError(non_field_errors=['Expected a JSON object.'])

    semester_id = _expect_int(body.get('semester_id'))
    if semester_id is None:
        non_field_errors.append('semester_id is required and must be an integer.')

    semester_updated_at = None
    raw_stamp = body.get('semester_updated_at')
    if not isinstance(raw_stamp, str) or not raw_stamp:
        non_field_errors.append('semester_updated_at is required and must be an ISO datetime string.')
    else:
        try:
            semester_updated_at = parse_datetime(raw_stamp)
        except ValueError:
            semester_updated_at = None
        if semester_updated_at is None:
            non_field_errors.append('semester_updated_at could not be parsed as an ISO datetime.')

    if non_field_errors:
        raise SemesterDefaultsReapplyBufferValidationError(non_field_errors=non_field_errors)

    return SemesterDefaultsReapplyBuffer(semester_id=semester_id, semester_updated_at=semester_updated_at)
class AdjudicationBufferValidationError(ValidationError):
    """Raised by `build_adjudication_buffer_from_request()` for a JSON body that can't become an `AdjudicationBuffer` (issue #340).

    Mirrors `RosterBufferValidationError`'s shape: `row_errors`
    (`{<row_key>: {<field>: [messages]}}`, keyed by `conflict-<conflict_id>`
    when the row's `conflict_id` parsed cleanly, else `entry-<index>` the
    same way `build_roster_buffer_from_request()` falls back for a
    malformed `person_id`) and `non_field_errors` (`[messages]` for
    anything not attributable to one row/field). Also carries `raw_body`
    — the request's own parsed JSON body, untouched — so a Preview view
    can still echo every submitted verdict/note on a validation failure
    (issue #340 user story 42), even though normalization never finished
    long enough to build an `AdjudicationBuffer`.
    """

    def __init__(self, *, row_errors, non_field_errors, raw_body):
        """Store the structured failure shape and a human-readable summary message."""
        super().__init__('The submitted adjudication edit could not be validated.')
        self.row_errors = row_errors
        self.non_field_errors = non_field_errors
        self.raw_body = raw_body


def build_adjudication_buffer_from_request(request, *, rehearsal_id) -> AdjudicationBuffer:
    """Parse `request`'s JSON body into an `AdjudicationBuffer` for `rehearsal_id` (issue #340).

    The ONE place a submitted Conflict-adjudication JSON body becomes an
    `AdjudicationBuffer` — `/api/conflicts/<rehearsal_id>/preview/` and
    `/api/conflicts/<rehearsal_id>/save/` both call it, never fork it,
    mirroring `build_roster_buffer_from_request()`'s ADR-0008 "preview and
    save cannot disagree" guarantee. `rehearsal_id` always comes from the
    URL, never the body — there is no per-row Rehearsal to disagree about,
    since this Buffer always describes one Rehearsal's whole table.

    Wire shape::

        {
            "semester_id": 1,
            "semester_updated_at": "2026-01-01T00:00:00.000000+00:00",
            "entries": [
                {"conflict_id": 12, "status": "approved", "note": "..."}
            ]
        }

    Each entry's `status` must be one of `Conflict.STATUS_CHOICES`'
    values, and `note` must be at most 255 characters — the same limit
    `AdjudicationRowForm.note` enforced pre-SPA. A validation failure on
    one entry is reported as a per-row field error keyed by
    `conflict-<conflict_id>` (or `entry-<index>` when `conflict_id` itself
    doesn't parse), preserving every other submitted entry rather than
    failing the whole batch (issue #340 user story 42) — the caller
    reconstructs `values` from `raw_body`, not from a partially-built
    Buffer. Does not check `conflict_id` against `rehearsal_id`'s actual
    Conflicts, nor `semester_id` against the viewing Semester: both stay
    `UnknownConflictError`/`WrongAdjudicationSemesterError` territory,
    raised by `apply_adjudications()`/`preview_adjudications()` themselves.
    """
    from config.views import ApiView

    body = ApiView().parse_json_body(request)

    non_field_errors = []
    raw_body = body if isinstance(body, dict) else {}

    if not isinstance(body, dict):
        non_field_errors.append('Expected a JSON object.')
        raise AdjudicationBufferValidationError(row_errors={}, non_field_errors=non_field_errors, raw_body=raw_body)

    semester_id = _expect_int(body.get('semester_id'))
    if semester_id is None:
        non_field_errors.append('semester_id is required and must be an integer.')

    semester_updated_at = None
    raw_stamp = body.get('semester_updated_at')
    if not isinstance(raw_stamp, str) or not raw_stamp:
        non_field_errors.append('semester_updated_at is required and must be an ISO datetime string.')
    else:
        try:
            semester_updated_at = parse_datetime(raw_stamp)
        except ValueError:
            semester_updated_at = None
        if semester_updated_at is None:
            non_field_errors.append('semester_updated_at could not be parsed as an ISO datetime.')

    entries_raw = body.get('entries')
    if not isinstance(entries_raw, list):
        non_field_errors.append('entries must be a list.')
        entries_raw = []

    valid_statuses = {value for value, _label in Conflict.STATUS_CHOICES}
    row_errors = {}
    entries = []
    for index, raw_entry in enumerate(entries_raw):
        conflict_id = _expect_int(raw_entry.get('conflict_id')) if isinstance(raw_entry, dict) else None
        row_key = f'conflict-{conflict_id}' if conflict_id is not None else f'entry-{index}'

        if not isinstance(raw_entry, dict):
            row_errors[row_key] = {'row': [_MUST_BE_OBJECT_MESSAGE]}
            continue

        field_errors: dict[str, list[str]] = {}

        if conflict_id is None:
            field_errors.setdefault('conflict_id', []).append(_MUST_BE_INTEGER_MESSAGE)

        status = _expect_string(raw_entry.get('status'))
        if status is None:
            field_errors.setdefault('status', []).append(_MUST_BE_STRING_MESSAGE)
        elif status not in valid_statuses:
            field_errors.setdefault('status', []).append(_UNKNOWN_STATUS_MESSAGE)

        note = _expect_string(raw_entry.get('note', ''))
        if note is None:
            field_errors.setdefault('note', []).append(_MUST_BE_STRING_MESSAGE)
        elif len(note) > _NOTE_MAX_LENGTH:
            field_errors.setdefault('note', []).append(_NOTE_TOO_LONG_MESSAGE)

        if field_errors:
            row_errors[row_key] = field_errors
            continue

        entries.append(AdjudicationEntry(conflict_id=conflict_id, status=status, note=note))

    if row_errors or non_field_errors:
        raise AdjudicationBufferValidationError(row_errors=row_errors, non_field_errors=non_field_errors, raw_body=raw_body)

    return AdjudicationBuffer(
        rehearsal_id=rehearsal_id,
        semester_id=semester_id,
        semester_updated_at=semester_updated_at,
        entries=entries,
    )


class SongRoleRequirementBufferValidationError(ValidationError):
    """Raised by `build_song_role_requirement_buffer_from_request()` for a JSON body that can't become a `SongRoleRequirementBuffer` (issue #339).

    Mirrors `AdjudicationBufferValidationError`'s shape: `row_errors`
    (`{<row_key>: {<field>: [messages]}}`, keyed by `role-<role_id>` when
    the row's `role_id` parsed cleanly, else `entry-<index>` — this
    Buffer's `entries` have no client-generated `row_key` of their own,
    unlike a Setlist/Roster row, since a Requirement's own identity
    already is its Role). Also carries `raw_body` — the request's own
    parsed JSON body, untouched — so the Preview view can still echo every
    submitted value on a validation failure (issue #339 user story 16)
    even though normalization never finished long enough to build a
    `SongRoleRequirementBuffer`.
    """

    def __init__(self, *, row_errors, non_field_errors, raw_body):
        """Store the structured failure shape and a human-readable summary message."""
        super().__init__('The submitted Role Requirements edit could not be validated.')
        self.row_errors = row_errors
        self.non_field_errors = non_field_errors
        self.raw_body = raw_body


def build_song_role_requirement_buffer_from_request(request, *, song_id, viewing_semester) -> SongRoleRequirementBuffer:
    """Parse `request`'s JSON body into a `SongRoleRequirementBuffer` for `song_id` (issue #339).

    The ONE place a submitted Requirements-editor JSON body becomes a
    `SongRoleRequirementBuffer` — its Preview and Save endpoints both call
    it, never fork it, mirroring `build_adjudication_buffer_from_request()`'s
    ADR-0008 "preview and save cannot disagree" guarantee. `song_id` always
    comes from the URL, never the body, the same way `rehearsal_id` does
    for the adjudication Buffer — there is no per-row Song to disagree
    about, since this Buffer always describes one Song's whole Requirements
    set.

    Wire shape::

        {
            "semester_id": 1,
            "semester_updated_at": "2026-01-01T00:00:00.000000+00:00",
            "entries": [{"role_id": 3, "count": 2}, ...]
        }

    `entries` names every Requirement the Song should have afterward — the
    client sends the target state, not a diff, matching
    `SongRoleRequirementBuffer.entries`' own documented semantics. A
    `count` below 1 and a `role_id` naming no Role are per-row Validation
    Errors; a `role_id` repeated across two entries is rejected here too
    (the `unique_role_requirement_per_song` constraint's backstop, an
    error a hand-crafted POST could otherwise turn into an unhandled
    `IntegrityError` deep inside `apply_song_role_requirements()`). Does
    not check `semester_id` against `viewing_semester`, nor a `role_id`
    against anything Roster-related: both stay
    `WrongViewingSemesterError`/Fallout territory, decided by
    `apply_song_role_requirements()`/`preview_song_role_requirements()`
    themselves.
    """
    from config.views import ApiView

    body = ApiView().parse_json_body(request)

    non_field_errors = []
    raw_body = body if isinstance(body, dict) else {}

    if not isinstance(body, dict):
        non_field_errors.append('Expected a JSON object.')
        raise SongRoleRequirementBufferValidationError(
            row_errors={}, non_field_errors=non_field_errors, raw_body=raw_body,
        )

    semester_id = _expect_int(body.get('semester_id'))
    if semester_id is None:
        non_field_errors.append('semester_id is required and must be an integer.')

    semester_updated_at = None
    raw_stamp = body.get('semester_updated_at')
    if not isinstance(raw_stamp, str) or not raw_stamp:
        non_field_errors.append('semester_updated_at is required and must be an ISO datetime string.')
    else:
        try:
            semester_updated_at = parse_datetime(raw_stamp)
        except ValueError:
            semester_updated_at = None
        if semester_updated_at is None:
            non_field_errors.append('semester_updated_at could not be parsed as an ISO datetime.')

    entries_raw = body.get('entries')
    if not isinstance(entries_raw, list):
        non_field_errors.append('entries must be a list.')
        entries_raw = []

    candidate_role_ids = set()
    for raw_entry in entries_raw:
        if isinstance(raw_entry, dict):
            candidate_role_id = _expect_int(raw_entry.get('role_id'))
            if candidate_role_id is not None:
                candidate_role_ids.add(candidate_role_id)
    existing_role_ids = set(
        Role.objects.filter(pk__in=candidate_role_ids).values_list('pk', flat=True)
    ) if candidate_role_ids else set()

    row_errors = {}
    seen_role_ids = set()
    entries = []
    for index, raw_entry in enumerate(entries_raw):
        role_id = _expect_int(raw_entry.get('role_id')) if isinstance(raw_entry, dict) else None
        row_key = f'role-{role_id}' if role_id is not None else f'entry-{index}'

        if not isinstance(raw_entry, dict):
            row_errors[row_key] = {'row': [_MUST_BE_OBJECT_MESSAGE]}
            continue

        field_errors: dict[str, list[str]] = {}

        if role_id is None:
            field_errors.setdefault('role_id', []).append(_MUST_BE_INTEGER_MESSAGE)
        elif role_id not in existing_role_ids:
            field_errors.setdefault('role_id', []).append(_UNKNOWN_ROLE_MESSAGE)
        elif role_id in seen_role_ids:
            field_errors.setdefault('role_id', []).append(_DUPLICATE_ROLE_MESSAGE)

        count = _expect_int(raw_entry.get('count'))
        if count is None:
            field_errors.setdefault('count', []).append(_MUST_BE_INTEGER_MESSAGE)
        elif count < 1:
            field_errors.setdefault('count', []).append(_COUNT_TOO_LOW_MESSAGE)

        if field_errors:
            row_errors[row_key] = field_errors
            continue

        seen_role_ids.add(role_id)
        entries.append(SongRoleRequirementEntry(role_id=role_id, count=count))

    if row_errors or non_field_errors:
        raise SongRoleRequirementBufferValidationError(
            row_errors=row_errors, non_field_errors=non_field_errors, raw_body=raw_body,
        )

    return SongRoleRequirementBuffer(
        song_id=song_id,
        semester_id=semester_id,
        semester_updated_at=semester_updated_at,
        entries=entries,
    )


class SongCastBufferValidationError(ValidationError):
    """Raised by `build_song_cast_buffer_from_request()` for a JSON body that can't become a `SongCastEditBuffer` (issue #499).

    Mirrors `AssignmentBufferValidationError`'s shape rather than the
    row-keyed Setlist/Requirements one: every field on this Buffer is an
    id or a flat tuple of ids, never a per-row edit a client renders back
    beside one input, so a malformed submission is reported as
    `non_field_errors` alone.
    """

    def __init__(self, *, non_field_errors):
        """Store the submission-wide failure messages."""
        super().__init__('The submitted cast edit could not be validated.')
        self.non_field_errors = non_field_errors


def build_song_cast_buffer_from_request(request, *, song_id) -> SongCastEditBuffer:
    """Parse `request`'s JSON body into a `SongCastEditBuffer` for `song_id` (issue #499, ADR-0019).

    The ONE place a submitted Song-level cast JSON body becomes a
    `SongCastEditBuffer` — `/api/songs/<pk>/cast/preview/` and
    `/api/songs/<pk>/cast/save/` both call it, never fork it, so ADR-0008's
    "preview and save cannot disagree" guarantee holds on the wire too.
    `song_id` always comes from the URL, never the body, the same way
    `build_song_role_requirement_buffer_from_request()` takes it.

    Wire shape::

        {
            "song_updated_at": "2026-01-01T00:00:00.000000+00:00",
            "removed_assignment_ids": [1, 2],
            "added_entries": [{"role_id": 2, "person_id": 3}]
        }

    There is no `semester_id` here, unlike every other Buffer on the wire:
    this surface's Semester check is "does `song_id` name a Song in the
    viewing Semester", answered by `apply_song_cast_edits()` (and 404'd by
    the view before that), so a body-supplied Semester id would be a
    second, redundant source of the same answer. `song_updated_at` is
    required — without it neither the staleness check nor its `is_stale`
    report can run at all — and is the only thing that raises here; every
    id list is shape-checked only, since whether an id names a live row is
    `apply_song_cast_edits()`'s job.
    """
    from config.views import ApiView

    body = ApiView().parse_json_body(request)
    if not isinstance(body, dict):
        raise SongCastBufferValidationError(non_field_errors=['Expected a JSON object.'])

    non_field_errors = []
    song_updated_at = None
    raw_stamp = body.get('song_updated_at')
    if not isinstance(raw_stamp, str) or not raw_stamp:
        non_field_errors.append('song_updated_at is required and must be an ISO datetime string.')
    else:
        try:
            song_updated_at = parse_datetime(raw_stamp)
        except ValueError:
            song_updated_at = None
        if song_updated_at is None:
            non_field_errors.append('song_updated_at could not be parsed as an ISO datetime.')

    if non_field_errors:
        raise SongCastBufferValidationError(non_field_errors=non_field_errors)

    return SongCastEditBuffer(
        song_id=song_id,
        song_updated_at=song_updated_at,
        removed_assignment_ids=_parse_assignment_id_set(body.get('removed_assignment_ids', [])),
        added_entries=_parse_added_cast_entries(body.get('added_entries', [])),
    )
