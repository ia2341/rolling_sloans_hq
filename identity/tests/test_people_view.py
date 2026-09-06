"""Admin people management: /manage/people/ (issue #59)."""

from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from faker import Faker

from identity.factories import PersonFactory
from identity.models import Person
from identity.services import EmailDeliveryError

fake = Faker()
PASSWORD = 'a-strong-test-password-123'


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_people_redirects_anonymous_users_to_login(self):
        """An anonymous request to /manage/people/ redirects to the login page."""
        url = reverse('identity:people')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_toggle_admin_redirects_anonymous_users_to_login(self):
        """An anonymous POST to the toggle-admin endpoint redirects to the login page."""
        target = PersonFactory()
        url = reverse('identity:people-toggle-admin', args=[target.pk])

        response = self.client.post(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_resend_invite_redirects_anonymous_users_to_login(self):
        """An anonymous POST to the resend-invite endpoint redirects to the login page."""
        target = PersonFactory()
        url = reverse('identity:people-resend-invite', args=[target.pk])

        response = self.client.post(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")


@override_settings(SECURE_SSL_REDIRECT=False)
class NonAdminAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic non-admin Person to log in as before each test."""
        cls.person = PersonFactory(password=PASSWORD, is_admin=False)

    def setUp(self):
        """Log in as the synthetic non-admin Person before each test."""
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_people_get_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's GET to /manage/people/ returns 403."""
        response = self.client.get(reverse('identity:people'))

        self.assertEqual(response.status_code, 403)

    def test_people_post_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's POST to /manage/people/ returns 403 and creates nothing."""
        response = self.client.post(reverse('identity:people'), {
            'name': fake.name(), 'email': fake.email(domain='example.com'),
        })

        self.assertEqual(response.status_code, 403)

    def test_toggle_admin_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's POST to the toggle-admin endpoint returns 403 and changes nothing."""
        target = PersonFactory(is_admin=False)

        response = self.client.post(reverse('identity:people-toggle-admin', args=[target.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Person.objects.get(pk=target.pk).is_admin)

    def test_resend_invite_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's POST to the resend-invite endpoint returns 403 and sends nothing."""
        target = PersonFactory()

        response = self.client.post(reverse('identity:people-resend-invite', args=[target.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(SECURE_SSL_REDIRECT=False)
class PeopleViewGetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person to log in as before each test."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_lists_existing_people(self):
        """The roster includes existing Persons."""
        other = PersonFactory()

        response = self.client.get(reverse('identity:people'))

        self.assertEqual(response.status_code, 200)
        self.assertIn(other, response.context['people'])
        self.assertIn(self.admin, response.context['people'])

    def test_marks_pending_people_as_pending(self):
        """A never-set-password Person is flagged is_pending_invite; a settled one is not (#327)."""
        pending = PersonFactory()
        settled = PersonFactory(password=PASSWORD)

        response = self.client.get(reverse('identity:people'))

        by_pk = {person.pk: person for person in response.context['people']}
        self.assertTrue(by_pk[pending.pk].is_pending_invite)
        self.assertFalse(by_pk[settled.pk].is_pending_invite)

    def test_invite_again_button_present_only_for_pending_people(self):
        """The 'Invite again' control renders for a pending person and not for a settled one."""
        pending = PersonFactory()
        settled = PersonFactory(password=PASSWORD)

        response = self.client.get(reverse('identity:people'))

        self.assertContains(
            response, reverse('identity:people-resend-invite', args=[pending.pk]),
        )
        self.assertNotContains(
            response, reverse('identity:people-resend-invite', args=[settled.pk]),
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class PeopleViewPostTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person to log in as before each test."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_valid_post_invites_person_and_redirects_with_message(self):
        """A valid POST creates a Person via invite_person(), sends the invite email, and redirects with a success message."""
        args = {'name': fake.name(), 'email': fake.email(domain='example.com')}

        response = self.client.post(reverse('identity:people'), args, follow=True)

        self.assertRedirects(response, reverse('identity:people'))
        created = Person.objects.get(email=args['email'])
        self.assertFalse(created.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        messages = [str(m) for m in response.context['messages']]
        self.assertTrue(any(args['email'] in m for m in messages))

    def test_invalid_post_rerenders_form_with_errors(self):
        """A POST with a duplicate email re-renders the form with a field error, not a 500, and creates nothing."""
        existing = PersonFactory()

        response = self.client.post(reverse('identity:people'), {
            'name': fake.name(), 'email': existing.email,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(Person.objects.filter(email=existing.email).count(), 1)

    def test_rolled_back_invite_does_not_create_person(self):
        """If the invite email fails to send, the exception propagates and no Person row is left committed."""
        args = {'name': fake.name(), 'email': fake.email(domain='example.com')}

        with patch('identity.services.send_mail', return_value=0), \
                self.assertRaises(EmailDeliveryError):
            self.client.post(reverse('identity:people'), args)

        self.assertFalse(Person.objects.filter(email=args['email']).exists())

    def test_toggle_admin_flips_flag_and_redirects_with_message(self):
        """A valid POST toggles is_admin on an existing Person and redirects with a success message."""
        target = PersonFactory(is_admin=False)

        response = self.client.post(
            reverse('identity:people-toggle-admin', args=[target.pk]), follow=True,
        )

        self.assertRedirects(response, reverse('identity:people'))
        self.assertTrue(Person.objects.get(pk=target.pk).is_admin)
        messages = [str(m) for m in response.context['messages']]
        self.assertTrue(any(target.email in m for m in messages))

    def test_toggle_admin_twice_reverts_to_original(self):
        """Toggling twice flips is_admin back to its original value."""
        target = PersonFactory(is_admin=True)
        url = reverse('identity:people-toggle-admin', args=[target.pk])

        self.client.post(url)
        self.client.post(url)

        self.assertTrue(Person.objects.get(pk=target.pk).is_admin)

    def test_toggle_admin_404s_for_unknown_person(self):
        """A toggle-admin POST for a nonexistent Person id returns 404."""
        response = self.client.post(reverse('identity:people-toggle-admin', args=[999999]))

        self.assertEqual(response.status_code, 404)

    def test_resend_invite_re_sends_and_redirects_with_message(self):
        """A valid resend-invite POST re-sends to a pending Person and redirects with a success message."""
        target = PersonFactory()

        response = self.client.post(
            reverse('identity:people-resend-invite', args=[target.pk]), follow=True,
        )

        self.assertRedirects(response, reverse('identity:people'))
        self.assertEqual(len(mail.outbox), 1)
        messages = [str(m) for m in response.context['messages']]
        self.assertTrue(any(target.email in m for m in messages))

    def test_resend_invite_is_refused_for_a_settled_person(self):
        """Resend-invite on a Person who already has a usable password is refused with a clear reason."""
        target = PersonFactory(password=PASSWORD)

        response = self.client.post(
            reverse('identity:people-resend-invite', args=[target.pk]), follow=True,
        )

        self.assertRedirects(response, reverse('identity:people'))
        self.assertEqual(len(mail.outbox), 0)
        messages = [str(m) for m in response.context['messages']]
        self.assertTrue(any('already set a password' in m for m in messages))

    def test_resend_invite_does_not_duplicate_the_person(self):
        """Clicking resend-invite repeatedly never creates a second Person row."""
        target = PersonFactory()
        url = reverse('identity:people-resend-invite', args=[target.pk])

        self.client.post(url)
        self.client.post(url)

        self.assertEqual(Person.objects.filter(email=target.email).count(), 1)
        self.assertEqual(len(mail.outbox), 2)

    def test_resend_invite_404s_for_unknown_person(self):
        """A resend-invite POST for a nonexistent Person id returns 404."""
        response = self.client.post(reverse('identity:people-resend-invite', args=[999999]))

        self.assertEqual(response.status_code, 404)
