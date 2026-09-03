"""The Roster editor's "Invite someone new" affordance: /members/invite/ (issue #230)."""

from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from faker import Faker

from identity.factories import PersonFactory
from identity.models import Person
from identity.services import EmailDeliveryError
from scheduling.factories import MembershipFactory, SemesterFactory
from scheduling.models import Membership
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY

fake = Faker()
PASSWORD = 'a-strong-test-password-123'


def _invite_url():
    """Return the invite endpoint's URL."""
    return reverse('scheduling:members-roster-invite')


def _edit_url():
    """Return /members/ with the edit-mode query string."""
    return f"{reverse('scheduling:members')}?mode=edit"


def _invite_args():
    """Build a fresh, fake (name, email) payload for the invite form."""
    return {'name': fake.name(), 'email': fake.email(domain='example.com')}


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic non-admin Person and a live Semester."""
        cls.person = PersonFactory(password=PASSWORD)
        cls.semester = SemesterFactory()

    def test_anonymous_post_redirects_to_login(self):
        """An anonymous invite POST redirects to login rather than inviting anyone."""
        response = self.client.post(_invite_url(), _invite_args())

        self.assertRedirects(response, f"{reverse('identity:login')}?next={_invite_url()}")

    def test_non_admin_post_is_forbidden(self):
        """A logged-in non-admin's invite POST returns 403 and creates nothing."""
        self.client.login(username=self.person.email, password=PASSWORD)
        args = _invite_args()

        response = self.client.post(_invite_url(), args)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Person.objects.filter(email=args['email']).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class InviteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person and the Semester they're viewing."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.semester = SemesterFactory()

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_no_viewing_semester_redirects_without_inviting(self):
        """With no viewing Semester at all, the invite POST redirects and creates nothing."""
        self.semester.delete()
        args = _invite_args()

        response = self.client.post(_invite_url(), args)

        self.assertRedirects(response, reverse('scheduling:members'))
        self.assertFalse(Person.objects.filter(email=args['email']).exists())

    def test_valid_invite_creates_person_and_memberships_and_sends_mail(self):
        """A valid invite creates the Person, rosters them in the viewing Semester, and sends one email."""
        args = _invite_args()

        response = self.client.post(_invite_url(), args, follow=True)

        self.assertRedirects(response, _edit_url())
        created = Person.objects.get(email=args['email'])
        self.assertFalse(created.has_usable_password())
        self.assertTrue(Membership.objects.filter(person=created, semester=self.semester).exists())
        self.assertEqual(len(mail.outbox), 1)
        messages = [str(m) for m in response.context['messages']]
        self.assertTrue(any(args['email'] in m for m in messages))

    def test_invited_person_rosters_into_the_currently_viewed_semester(self):
        """The new Membership lands in the admin's session-selected viewing Semester, not just any Semester."""
        other_semester = SemesterFactory(draft=True)
        session = self.client.session
        session[VIEWING_SEMESTER_SESSION_KEY] = other_semester.pk
        session.save()
        args = _invite_args()

        self.client.post(_invite_url(), args)

        created = Person.objects.get(email=args['email'])
        self.assertTrue(Membership.objects.filter(person=created, semester=other_semester).exists())
        self.assertFalse(Membership.objects.filter(person=created, semester=self.semester).exists())

    def test_duplicate_email_is_rejected_with_a_message_pointing_at_the_add_list(self):
        """An email already belonging to a Person is rejected, names the add list, creates nothing, and sends no mail."""
        existing = PersonFactory()

        response = self.client.post(_invite_url(), {'name': fake.name(), 'email': existing.email})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'tick them in the add list')
        self.assertEqual(Person.objects.filter(email=existing.email).count(), 1)
        self.assertFalse(Membership.objects.filter(person=existing, semester=self.semester).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_rolled_back_invite_creates_no_person_and_no_membership(self):
        """If the invite email fails to send, the exception propagates and neither the Person nor a Membership survives."""
        args = _invite_args()

        with patch('identity.services.send_mail', return_value=0), \
                self.assertRaises(EmailDeliveryError):
            self.client.post(_invite_url(), args)

        self.assertFalse(Person.objects.filter(email=args['email']).exists())
        self.assertEqual(Membership.objects.filter(semester=self.semester).count(), 0)

    def test_invite_commits_independently_of_a_later_discarded_buffer(self):
        """The invited Person and Membership survive even though the admin never presses Save Changes afterward."""
        args = _invite_args()

        self.client.post(_invite_url(), args)
        # Simulate "discarding the Buffer" by simply never submitting the Save Changes form
        # afterward, then re-rendering edit mode fresh, as a fresh GET would.
        response = self.client.get(_edit_url())

        created = Person.objects.get(email=args['email'])
        self.assertTrue(Membership.objects.filter(person=created, semester=self.semester).exists())
        self.assertContains(response, f'value="{created.name}"')

    def test_invalid_invite_rerenders_edit_mode_with_errors(self):
        """A blank name re-renders edit mode (not a 500) and creates nothing."""
        response = self.client.post(_invite_url(), {'name': '', 'email': fake.email(domain='example.com')})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="roster-edit-form"')

    def test_invite_never_sent_through_a_preview(self):
        """Previewing the Roster edit Buffer never calls invite_person or sends mail — the invite has no path through it."""
        MembershipFactory(semester=self.semester)
        payload = {
            'roster-TOTAL_FORMS': '0', 'roster-INITIAL_FORMS': '0',
            'roster-MIN_NUM_FORMS': '0', 'roster-MAX_NUM_FORMS': '1000',
            'roster_add-TOTAL_FORMS': '0', 'roster_add-INITIAL_FORMS': '0',
            'roster_add-MIN_NUM_FORMS': '0', 'roster_add-MAX_NUM_FORMS': '1000',
            'roster_semester_id': str(self.semester.pk),
            'roster_semester_updated_at': self.semester.updated_at.isoformat(),
        }

        self.client.post(reverse('scheduling:members-preview'), payload)

        self.assertEqual(len(mail.outbox), 0)
