"""Shared HTTP-test infrastructure for `/api/` test modules (extracted from `test_setlist_reorder_add_delete.py` by issue #341).

Not a `factories.py` (this is test-only infrastructure, not a
`factory_boy` model factory) and not itself a test module — `admin_client`/
`member_client`/`select` were originally defined in
`test_setlist_reorder_add_delete.py` for its own view tests, but a wide
swath of `/api/` test modules (built across issues #329-#340) came to
depend on importing them from there. Deleting that file's now-obsolete
Django-view tests (issue #341's cutover) would have taken these load-
bearing helpers down with it, so they live here instead, with every
importer repointed at this module. `build_post_data` (that same file's
formset-POST builder for the retired setlist edit grid's own wire format)
stayed behind and was deleted outright — nothing outside the view tests
it served ever called it.
"""

from identity.factories import PersonFactory
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY

PASSWORD = 'a-strong-test-password-123'


def admin_client(test_case):
    """Log a synthetic admin Person into `test_case`'s client and return that Person."""
    person = PersonFactory(password=PASSWORD, is_admin=True)
    test_case.client.login(username=person.email, password=PASSWORD)
    return person


def member_client(test_case):
    """Log a synthetic non-admin Person into `test_case`'s client and return that Person."""
    person = PersonFactory(password=PASSWORD)
    test_case.client.login(username=person.email, password=PASSWORD)
    return person


def select(test_case, semester):
    """Record `semester` as the client's session selection, mirroring `services.set_viewing_semester`."""
    session = test_case.client.session
    session[VIEWING_SEMESTER_SESSION_KEY] = semester.pk
    session.save()
