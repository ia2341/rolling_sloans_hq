"""`/manage/semesters/<pk>/reapply-defaults/`: the admin-facing bulk defaults-push surface (issue #291)."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import RehearsalFactory, RehearsalSongFactory, SemesterFactory

PASSWORD = 'a-strong-test-password-123'
TOMORROW = timezone.localdate() + timedelta(days=1)
YESTERDAY = timezone.localdate() - timedelta(days=1)


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_get_redirects_anonymous_users_to_login(self):
        """An anonymous GET to the confirmation page redirects to the login page."""
        semester = SemesterFactory()
        url = reverse('scheduling:manage-semesters-reapply-defaults', args=[semester.pk])

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_post_redirects_anonymous_users_to_login_and_writes_nothing(self):
        """An anonymous POST redirects to login and leaves the Rehearsal untouched."""
        semester = SemesterFactory(default_setup_grace_minutes=20)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, setup_grace_minutes=1)
        url = reverse('scheduling:manage-semesters-reapply-defaults', args=[semester.pk])

        response = self.client.post(url, {'semester_updated_at': semester.updated_at.isoformat()})

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class NonAdminAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic non-admin Person to log in as before each test."""
        cls.person = PersonFactory(password=PASSWORD, is_admin=False)

    def setUp(self):
        """Log in as the synthetic non-admin Person before each test."""
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_get_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's GET returns 403."""
        semester = SemesterFactory()

        response = self.client.get(reverse('scheduling:manage-semesters-reapply-defaults', args=[semester.pk]))

        self.assertEqual(response.status_code, 403)

    def test_post_is_forbidden_for_non_admin_and_writes_nothing(self):
        """A logged-in non-admin's POST returns 403 and leaves the Rehearsal untouched."""
        semester = SemesterFactory(default_setup_grace_minutes=20)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, setup_grace_minutes=1)

        response = self.client.post(
            reverse('scheduling:manage-semesters-reapply-defaults', args=[semester.pk]),
            {'semester_updated_at': semester.updated_at.isoformat()},
        )

        self.assertEqual(response.status_code, 403)
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class SemesterDefaultsReapplyViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person to log in as before each test."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_get_404s_for_a_nonexistent_semester(self):
        """A GET for a nonexistent Semester id 404s."""
        response = self.client.get(reverse('scheduling:manage-semesters-reapply-defaults', args=[999999]))

        self.assertEqual(response.status_code, 404)

    def test_get_renders_the_upcoming_rehearsal_count(self):
        """The confirmation page's Fallout counts the Semester's upcoming Rehearsals."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=TOMORROW)
        RehearsalFactory(semester=semester, date=YESTERDAY)

        response = self.client.get(reverse('scheduling:manage-semesters-reapply-defaults', args=[semester.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['fallout'].is_blocked)
        self.assertEqual(response.context['fallout'].changed_rehearsal_count, 1)

    def test_get_leaves_the_semester_and_rehearsals_untouched(self):
        """Rendering the confirmation page (a rolled-back Preview) writes nothing."""
        semester = SemesterFactory(default_setup_grace_minutes=20)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, setup_grace_minutes=1)
        stamp_before = semester.updated_at

        self.client.get(reverse('scheduling:manage-semesters-reapply-defaults', args=[semester.pk]))

        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 1)
        semester.refresh_from_db()
        self.assertEqual(semester.updated_at, stamp_before)

    def test_post_reapplies_and_redirects_with_a_success_message(self):
        """POSTing the confirmation reapplies the Semester's defaults and redirects with a success message."""
        semester = SemesterFactory(default_setup_grace_minutes=20)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, setup_grace_minutes=1)

        response = self.client.post(
            reverse('scheduling:manage-semesters-reapply-defaults', args=[semester.pk]),
            {'semester_updated_at': semester.updated_at.isoformat()},
            follow=True,
        )

        self.assertRedirects(response, reverse('scheduling:manage-semesters'))
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 20)
        messages = [str(m) for m in response.context['messages']]
        self.assertTrue(any('Reapplied' in m for m in messages))

    def test_post_with_a_stale_stamp_writes_nothing_and_redirects_back_with_an_error(self):
        """A stale semester_updated_at is rejected, writes nothing, and redirects back to the confirmation."""
        semester = SemesterFactory(default_setup_grace_minutes=20)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, setup_grace_minutes=1)
        stale_stamp = semester.updated_at.isoformat()
        semester.updated_at = timezone.now()
        semester.save(update_fields=['updated_at'])

        response = self.client.post(
            reverse('scheduling:manage-semesters-reapply-defaults', args=[semester.pk]),
            {'semester_updated_at': stale_stamp},
            follow=True,
        )

        self.assertRedirects(response, reverse('scheduling:manage-semesters-reapply-defaults', args=[semester.pk]))
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 1)

    def test_post_blocked_by_a_slot_overrun_writes_nothing_and_redirects_back_with_an_error(self):
        """A shrunk default_song_slot_count that would overrun a RehearsalSong blocks the POST and writes nothing."""
        semester = SemesterFactory(default_song_slot_count=5, default_setup_grace_minutes=20)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, setup_grace_minutes=1)
        RehearsalSongFactory(rehearsal=rehearsal, order=1, slot_count=5)
        semester.default_song_slot_count = 1
        semester.save(update_fields=['default_song_slot_count'])

        response = self.client.post(
            reverse('scheduling:manage-semesters-reapply-defaults', args=[semester.pk]),
            {'semester_updated_at': semester.updated_at.isoformat()},
            follow=True,
        )

        self.assertRedirects(response, reverse('scheduling:manage-semesters-reapply-defaults', args=[semester.pk]))
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 1)
