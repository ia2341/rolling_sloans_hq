"""The self-serve current-password-gated password change flow (issue #90)."""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from identity.models import Person

OLD_PASSWORD = 'a-strong-old-password-123'
NEW_PASSWORD = 'a-strong-new-password-456'


@override_settings(SECURE_SSL_REDIRECT=False)
class PasswordChangeViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person before each test."""
        self.person = PersonFactory(password=OLD_PASSWORD)
        self.client.login(username=self.person.email, password=OLD_PASSWORD)

    def test_anonymous_request_redirects_to_login(self):
        """An anonymous request to the password-change page redirects to login."""
        self.client.logout()
        url = reverse('identity:password-change')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_incorrect_current_password_is_rejected(self):
        """Submitting the wrong current password re-renders the form with an error and leaves the password unchanged."""
        response = self.client.post(reverse('identity:password-change'), {
            'old_password': 'not-the-right-password',
            'new_password1': NEW_PASSWORD,
            'new_password2': NEW_PASSWORD,
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())
        reloaded = Person.objects.get(pk=self.person.pk)
        self.assertTrue(reloaded.check_password(OLD_PASSWORD))

    def test_correct_current_password_changes_it_and_keeps_the_session_valid(self):
        """A correct current password updates the stored password and the session stays authenticated afterward."""
        response = self.client.post(reverse('identity:password-change'), {
            'old_password': OLD_PASSWORD,
            'new_password1': NEW_PASSWORD,
            'new_password2': NEW_PASSWORD,
        })

        self.assertRedirects(response, reverse('identity:password-change-done'))
        reloaded = Person.objects.get(pk=self.person.pk)
        self.assertTrue(reloaded.check_password(NEW_PASSWORD))
        self.assertFalse(reloaded.check_password(OLD_PASSWORD))
        whoami = self.client.get(reverse('scheduling:profile'))
        self.assertTrue(whoami.wsgi_request.user.is_authenticated)
