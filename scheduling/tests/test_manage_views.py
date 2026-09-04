"""/manage/assignments/ is gone (issue #213); /manage/schedule/ and its edit route are gone too (issue #224)."""

from django.test import TestCase, override_settings

from identity.factories import PersonFactory
from scheduling.factories import RehearsalFactory, SongRoleAssignmentFactory
from scheduling.models import Rehearsal, SongRoleAssignment

PASSWORD = 'a-strong-test-password-123'


@override_settings(SECURE_SSL_REDIRECT=False)
class ManageScheduleRemovedTests(TestCase):
    """`/manage/schedule/` and `/manage/schedule/<pk>/edit/` are gone outright, no redirect (issue #224).

    Rehearsal editing now lives solely on `/schedule/?view=all` in edit
    mode; both old routes 404 for anyone, admin included, rather than
    redirecting anywhere.
    """

    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person and one Rehearsal to target the edit route with."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.rehearsal = RehearsalFactory(is_full_setlist=False)

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_manage_schedule_404s(self):
        """A GET to /manage/schedule/ returns 404, even for an admin."""
        response = self.client.get('/manage/schedule/')

        self.assertEqual(response.status_code, 404)

    def test_manage_schedule_edit_404s(self):
        """A GET/POST to /manage/schedule/<pk>/edit/ returns 404 and changes nothing, even for an admin."""
        url = f'/manage/schedule/{self.rehearsal.pk}/edit/'

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'is_full_setlist': True}).status_code, 404)
        self.assertFalse(Rehearsal.objects.get(pk=self.rehearsal.pk).is_full_setlist)


@override_settings(SECURE_SSL_REDIRECT=False)
class ManageAssignmentsRemovedTests(TestCase):
    """`/manage/assignments/` and its delete route are gone outright, no redirect (issue #213).

    The flat add-form had no Rehearsal, so it structurally couldn't raise
    the availability warning; the assignment grid on /schedule/ now covers
    every case it did (add, remove, reach any Role), so both routes 404
    for anyone, admin included, rather than redirecting anywhere.
    """

    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person and one SongRoleAssignment to target the delete route with."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.assignment = SongRoleAssignmentFactory()

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_manage_assignments_404s(self):
        """A GET to /manage/assignments/ returns 404, even for an admin."""
        response = self.client.get('/manage/assignments/')

        self.assertEqual(response.status_code, 404)

    def test_manage_assignments_delete_404s(self):
        """A POST to /manage/assignments/<pk>/delete/ returns 404 and deletes nothing, even for an admin."""
        response = self.client.post(f'/manage/assignments/{self.assignment.pk}/delete/')

        self.assertEqual(response.status_code, 404)
        self.assertTrue(SongRoleAssignment.objects.filter(pk=self.assignment.pk).exists())
