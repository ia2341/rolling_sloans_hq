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
from django.core.validators import validate_email
from django.utils.dateparse import parse_datetime

from identity.models import Person
from scheduling.fields import parse_song_length
from scheduling.models import Role, Song
from scheduling.services import (
    RosterEditBuffer,
    RosterEditEntry,
    RosterInvite,
    SetlistEditBuffer,
    SetlistEditRow,
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

    Wire shape::

        {
            "semester_id": 1,
            "semester_updated_at": "2026-01-01T00:00:00.000000+00:00",
            "entries": [
                {"row_key": "row-1", "person_id": 5, "name": "...", "role_ids": [1, 2]}
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
    candidate_role_ids = set()
    for raw_entry in entries_raw:
        if not isinstance(raw_entry, dict):
            continue
        candidate_person_id = _expect_int(raw_entry.get('person_id'))
        if candidate_person_id is not None:
            candidate_person_ids.add(candidate_person_id)
        role_ids_raw = raw_entry.get('role_ids')
        if isinstance(role_ids_raw, list):
            for value in role_ids_raw:
                candidate_role_id = _expect_int(value)
                if candidate_role_id is not None:
                    candidate_role_ids.add(candidate_role_id)

    people_by_id = Person.objects.in_bulk(candidate_person_ids)
    existing_role_ids = set(
        Role.objects.filter(pk__in=candidate_role_ids).values_list('pk', flat=True)
    ) if candidate_role_ids else set()

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

        role_ids_raw = raw_entry.get('role_ids', [])
        role_ids = set()
        if not isinstance(role_ids_raw, list):
            field_errors.setdefault('role_ids', []).append(_MUST_BE_LIST_MESSAGE)
        else:
            for value in role_ids_raw:
                role_id = _expect_int(value)
                if role_id is None or role_id not in existing_role_ids:
                    field_errors.setdefault('role_ids', []).append(_UNKNOWN_ROLE_MESSAGE)
                else:
                    role_ids.add(role_id)

        if field_errors:
            row_errors[row_key] = field_errors
            continue

        entries.append(RosterEditEntry(
            person=people_by_id[person_id], name=name.strip(), role_ids=frozenset(role_ids),
        ))

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
