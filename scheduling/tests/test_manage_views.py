"""/manage/assignments/ is gone (issue #213); /manage/schedule/ and its edit route are gone too (issue #224).

Since issue #325's catch-all, a GET to one of these retired paths reaches
the SPA shell (a 200) rather than a Django 404 — the client now owns
deciding a path is not found. A POST still gets no write surface: the
catch-all is GET-only, so it 405s instead.
"""

from django.test import TestCase, override_settings

from identity.factories import PersonFactory
from scheduling.factories import RehearsalFactory, SongRoleAssignmentFactory
from scheduling.models import Rehearsal, SongRoleAssignment

PASSWORD = 'a-strong-test-password-123'


@override_settings(SECURE_SSL_REDIRECT=False)
class ManageScheduleRemovedTests(TestCase):
    """`/manage/schedule/` and `/manage/schedule/<pk>/edit/` are gone outright, no redirect (issue #224).

    Rehearsal editing now lives solely on `/schedule/?view=all` in edit
    mode; both old routes reach the SPA's catch-all shell for anyone, admin
    included, rather than redirecting anywhere.
    """

    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person and one Rehearsal to target the edit route with."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.rehearsal = RehearsalFactory(is_full_setlist=False)

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_manage_schedule_reaches_the_spa_shell(self):
        """A GET to /manage/schedule/ returns the SPA shell, even for an admin."""
        response = self.client.get('/manage/schedule/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<div id="root">')

    def test_manage_schedule_edit_reaches_the_spa_shell_and_changes_nothing(self):
        """A GET to /manage/schedule/<pk>/edit/ returns the SPA shell; a POST 405s and changes nothing."""
        url = f'/manage/schedule/{self.rehearsal.pk}/edit/'

        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, '<div id="root">')

        self.assertEqual(self.client.post(url, {'is_full_setlist': True}).status_code, 405)
        self.assertFalse(Rehearsal.objects.get(pk=self.rehearsal.pk).is_full_setlist)


@override_settings(SECURE_SSL_REDIRECT=False)
class ManageAssignmentsRemovedTests(TestCase):
    """`/manage/assignments/` and its delete route are gone outright, no redirect (issue #213).

    The flat add-form had no Rehearsal, so it structurally couldn't raise
    the availability warning; the assignment grid on /schedule/ now covers
    every case it did (add, remove, reach any Role), so both routes reach
    the SPA's catch-all shell for anyone, admin included, rather than
    redirecting anywhere.
    """

    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person and one SongRoleAssignment to target the delete route with."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.assignment = SongRoleAssignmentFactory()

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_manage_assignments_reaches_the_spa_shell(self):
        """A GET to /manage/assignments/ returns the SPA shell, even for an admin."""
        response = self.client.get('/manage/assignments/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<div id="root">')

    def test_manage_assignments_delete_405s(self):
        """A POST to /manage/assignments/<pk>/delete/ 405s and deletes nothing, even for an admin."""
        response = self.client.post(f'/manage/assignments/{self.assignment.pk}/delete/')

        self.assertEqual(response.status_code, 405)
        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())
