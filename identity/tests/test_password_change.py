"""Change password (issue #90), relocated into the SPA by #333 and out of `identity/urls.py` by #327.

The route- and form-level tests move with the surface into #333's SPA
change-password endpoint. What survives here is the one contract #327 asks
this module to keep proving: `update_session_auth_hash()` on a changed
Person does not invalidate the session that made the change, which is what
lets a routine password change happen without ejecting the member from the
page they were on.
"""

from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.http import HttpRequest
from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory

OLD_PASSWORD = 'a-strong-old-password-123'
NEW_PASSWORD = 'a-strong-new-password-456'


@override_settings(SECURE_SSL_REDIRECT=False)
class PasswordChangeSessionContinuityTests(TestCase):
    def test_update_session_auth_hash_keeps_the_session_authenticated(self):
        """Setting a new password and calling update_session_auth_hash must not invalidate the requesting session."""
        person = PersonFactory(password=OLD_PASSWORD)
        self.client.login(username=person.email, password=OLD_PASSWORD)
        session = self.client.session
        request = HttpRequest()
        request.session = session
        request.user = person

        person.set_password(NEW_PASSWORD)
        person.save()
        update_session_auth_hash(request, person)
        session.save()
        # update_session_auth_hash() cycles the session key (so a fixated
        # session identifier can't survive it either); the test client's
        # cookie jar has to follow that new key to keep talking to the same
        # (still-authenticated) session.
        self.client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        response = self.client.get(reverse('scheduling:member-detail', args=[person.pk]))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_without_update_session_auth_hash_the_session_is_invalidated(self):
        """Contrast case: skipping update_session_auth_hash after a password change does log the session out.

        Pins the reason `update_session_auth_hash` is required in the first
        place, rather than only asserting the happy path.
        """
        person = PersonFactory(password=OLD_PASSWORD)
        self.client.login(username=person.email, password=OLD_PASSWORD)

        person.set_password(NEW_PASSWORD)
        person.save()

        response = self.client.get(reverse('scheduling:member-detail', args=[person.pk]))
        self.assertFalse(response.wsgi_request.user.is_authenticated)
