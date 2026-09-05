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
