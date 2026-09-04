"""The Semesters management surface and the Publish action: /manage/semesters/ (issue #170)."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import SemesterFactory
from scheduling.services import get_live_semester, publish_semester

PASSWORD = 'a-strong-test-password-123'


class PublishSemesterTests(TestCase):
    def test_publish_sets_published_at_to_now(self):
        """Publishing a draft stamps published_at to (approximately) now."""
        semester = SemesterFactory(draft=True)
        before = timezone.now()

        publish_semester(semester)

        semester.refresh_from_db()
        self.assertIsNotNone(semester.published_at)
        self.assertGreaterEqual(semester.published_at, before)
        self.assertEqual(get_live_semester(), semester)

    def test_republishing_an_older_semester_makes_it_live_again(self):
        """Publishing a previously-published, now-stale Semester makes it live again (rollback)."""
        older = SemesterFactory(published_at=timezone.now() - timedelta(days=2))
        newer = SemesterFactory(published_at=timezone.now() - timedelta(days=1))
        self.assertEqual(get_live_semester(), newer)

        publish_semester(older)

        self.assertEqual(get_live_semester(), older)

    def test_publishing_the_already_live_semester_is_harmless(self):
        """Publishing the Semester that is already live leaves it live."""
        semester = SemesterFactory()
        self.assertEqual(get_live_semester(), semester)

        publish_semester(semester)

        self.assertEqual(get_live_semester(), semester)

    def test_publish_does_not_touch_other_fields(self):
        """Publishing changes only published_at, nothing else about the Semester."""
        semester = SemesterFactory(draft=True)
        name = semester.name

        publish_semester(semester)

        semester.refresh_from_db()
        self.assertEqual(semester.name, name)


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_manage_semesters_redirects_anonymous_users_to_login(self):
        """An anonymous request to /manage/semesters/ redirects to the login page."""
        url = reverse('scheduling:manage-semesters')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_publish_redirects_anonymous_users_to_login(self):
        """An anonymous POST to the publish action redirects to the login page and publishes nothing."""
        semester = SemesterFactory(draft=True)
        url = reverse('scheduling:manage-semesters-publish', args=[semester.pk])

        response = self.client.post(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")
        semester.refresh_from_db()
        self.assertIsNone(semester.published_at)


@override_settings(SECURE_SSL_REDIRECT=False)
class NonAdminAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic non-admin Person to log in as before each test."""
        cls.person = PersonFactory(password=PASSWORD, is_admin=False)

    def setUp(self):
        """Log in as the synthetic non-admin Person before each test."""
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_manage_semesters_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's GET to /manage/semesters/ returns 403."""
        response = self.client.get(reverse('scheduling:manage-semesters'))

        self.assertEqual(response.status_code, 403)

    def test_publish_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's POST to the publish action returns 403 and publishes nothing."""
        semester = SemesterFactory(draft=True)

        response = self.client.post(reverse('scheduling:manage-semesters-publish', args=[semester.pk]))

        self.assertEqual(response.status_code, 403)
        semester.refresh_from_db()
        self.assertIsNone(semester.published_at)


@override_settings(SECURE_SSL_REDIRECT=False)
class SemesterManageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person to log in as before each test."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_lists_every_semester_newest_created_first(self):
        """The list includes every Semester (draft and published alike), ordered newest-created first."""
        first = SemesterFactory()
        second = SemesterFactory()
        third = SemesterFactory(draft=True)

        response = self.client.get(reverse('scheduling:manage-semesters'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['semesters']), [third, second, first])

    def test_labels_the_live_semester(self):
        """The Live Semester is distinguishable in context from a draft or a previously-published one."""
        live = SemesterFactory()

        response = self.client.get(reverse('scheduling:manage-semesters'))

        self.assertEqual(response.context['live_semester'], live)
        self.assertContains(response, 'Live')

    def test_publish_action_publishes_and_redirects_with_message(self):
        """POSTing the publish action publishes the target Semester and redirects with a success message."""
        draft = SemesterFactory(draft=True)

        response = self.client.post(
            reverse('scheduling:manage-semesters-publish', args=[draft.pk]), follow=True,
        )

        self.assertRedirects(response, reverse('scheduling:manage-semesters'))
        draft.refresh_from_db()
        self.assertIsNotNone(draft.published_at)
        self.assertEqual(get_live_semester(), draft)
        messages = [str(m) for m in response.context['messages']]
        self.assertTrue(any('published' in m for m in messages))

    def test_publish_404s_for_a_nonexistent_semester(self):
        """POSTing the publish action for a nonexistent Semester id 404s."""
        response = self.client.post(reverse('scheduling:manage-semesters-publish', args=[999999]))

        self.assertEqual(response.status_code, 404)

    def test_no_unpublish_route_exists(self):
        """No URL name for unpublishing a Semester is registered anywhere in the project."""
        with self.assertRaises(NoReverseMatch):
            reverse('scheduling:manage-semesters-unpublish', args=[1])
