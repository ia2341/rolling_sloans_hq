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
                "notes": "..."
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
from django.utils.dateparse import parse_date, parse_datetime, parse_time

from scheduling.fields import parse_song_length
from scheduling.models import Song
from scheduling.services import (
    RehearsalEditBuffer,
    RehearsalEditRow,
    RehearsalPatternInput,
    RehearsalTimeInput,
    RunningOrderRow,
    SetlistEditBuffer,
    SetlistEditRow,
    SkipDateInput,
)

#: Field-level messages shared by every row/field validation failure below.
_REQUIRED_MESSAGE = 'This field is required.'
_MUST_BE_INTEGER_MESSAGE = 'Enter a whole number.'
_MUST_BE_STRING_MESSAGE = 'Enter a string.'
_MUST_BE_LIST_MESSAGE = 'Expected a list.'
_MUST_BE_OBJECT_MESSAGE = 'Expected an object.'
_SONG_NOT_FOUND_MESSAGE = 'This song no longer exists in the current semester.'


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

        if field_errors:
            row_errors[row_key] = field_errors
            continue

        rows.append(SetlistEditRow(
            song_id=song_id,
            title=title.strip(),
            artist=artist.strip(),
            length=length,
            notes=notes,
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
