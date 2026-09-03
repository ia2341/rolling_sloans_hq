"""Surface-agnostic Preview test infrastructure: the mandatory writes-nothing assertion (issue #228, ADR 0008).

Not a `factories.py` — this is test-only infrastructure, not a
`factory_boy` model factory, so it lives here instead.
"""

from django.core import mail


def assert_preview_writes_nothing(test_case, preview_url, post_data, *, models_to_check, semester=None):
    """Snapshot row counts for `models_to_check` plus `Semester.updated_at`, POST `post_data` to `preview_url`, and assert nothing moved.

    `models_to_check` is an iterable of `(Model, filter_kwargs)` pairs (or
    bare `Model` classes, treated as `(Model, {})`) — each is
    `.objects.filter(**filter_kwargs).count()`-ed before and after the
    POST, and the response's status is asserted to be a 2xx. `semester`,
    when given, has its `updated_at` snapshotted and re-checked too — the
    real `apply_*()` bumps it on every successful save, so an unchanged
    stamp is itself evidence the write was rolled back. Also snapshots
    `django.core.mail.outbox`'s length to verify no mail was sent, per ADR
    0008's `on_commit` rule — the base class cannot catch a side effect
    that escapes the database, so this is what actually verifies it.
    Callers pass a Buffer containing creations, mutations *and* deletions
    together, per issue #228's acceptance criteria: a helper exercised
    only against additions proves nothing about the rollback of a delete.

    Returns the `HttpResponse` from the POST, so a caller can additionally
    assert on rendered content without a second request.
    """
    checks = [entry if isinstance(entry, tuple) else (entry, {}) for entry in models_to_check]
    counts_before = [model.objects.filter(**filter_kwargs).count() for model, filter_kwargs in checks]
    mail_count_before = len(mail.outbox)
    stamp_before = semester.updated_at if semester is not None else None

    response = test_case.client.post(preview_url, post_data)

    test_case.assertLess(response.status_code, 300, 'Preview request did not succeed.')
    for (model, filter_kwargs), count_before in zip(checks, counts_before, strict=True):
        test_case.assertEqual(
            model.objects.filter(**filter_kwargs).count(), count_before,
            f'{model.__name__} row count changed after a Preview.',
        )
    test_case.assertEqual(len(mail.outbox), mail_count_before, 'A Preview sent mail.')
    if semester is not None:
        semester.refresh_from_db()
        test_case.assertEqual(semester.updated_at, stamp_before, "A Preview bumped the Semester's updated_at.")
    return response
