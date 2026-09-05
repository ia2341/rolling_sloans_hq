"""Hand-written `/api/` wire serializers for `identity` (issue #326), mirroring `identity/services.py`.

Each function names every field it emits — no `dataclasses.asdict()`,
`model_to_dict()`, or other emit-everything helper, on ADR 0005 grounds: a
convenience that serializes a whole object is a rule that says "emit every
field", and the day a new field lands on `Person` it would ship to a
member-facing payload with no line of code deciding that was safe.
`scheduling/tests/test_prohibited_serializer_helpers.py` enforces this
mechanically for both serializer modules.
"""


def serialize_viewer(person):
    """Return `person` as the `context.viewer` block: `id`, `name`, `email`, `is_admin`.

    `email` is always the *requesting* person's own address — this
    function is only ever called with `request.user` — so it never
    violates `docs/person-page-visibility.md`'s "self only" verdict on a
    teammate's email; there is no path here that serializes anyone else's
    `Person` row.
    """
    return {
        'id': person.pk,
        'name': person.name,
        'email': person.email,
        'is_admin': person.is_admin,
    }
