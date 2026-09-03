"""Admin schedule & assignment management: /manage/schedule/, /manage/assignments/ (issue #60)."""

from datetime import time

from django.test import TestCase, override_settings
from django.urls import reverse
from faker import Faker

from identity.factories import PersonFactory
from scheduling.factories import (
    ConflictFactory,
    MembershipFactory,
    MembershipRoleFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Rehearsal, RehearsalSong, SongRoleAssignment

fake = Faker()
PASSWORD = 'a-strong-test-password-123'


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_manage_schedule_redirects_anonymous_users_to_login(self):
        """An anonymous request to /manage/schedule/ redirects to the login page."""
        url = reverse('scheduling:manage-schedule')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_manage_assignments_redirects_anonymous_users_to_login(self):
        """An anonymous request to /manage/assignments/ redirects to the login page."""
        url = reverse('scheduling:manage-assignments')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")


@override_settings(SECURE_SSL_REDIRECT=False)
class NonAdminAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic non-admin Person to log in as before each test."""
        cls.person = PersonFactory(password=PASSWORD, is_admin=False)

    def setUp(self):
        """Log in as the synthetic Person before each test."""
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_manage_schedule_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's GET to /manage/schedule/ returns 403."""
        response = self.client.get(reverse('scheduling:manage-schedule'))

        self.assertEqual(response.status_code, 403)

    def test_manage_assignments_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's GET to /manage/assignments/ returns 403."""
        response = self.client.get(reverse('scheduling:manage-assignments'))

        self.assertEqual(response.status_code, 403)

    def test_manage_schedule_edit_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's GET/POST to the Rehearsal edit endpoint returns 403 and changes nothing."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        url = reverse('scheduling:manage-schedule-edit', args=[rehearsal.pk])

        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'is_full_setlist': True}).status_code, 403)
        self.assertFalse(Rehearsal.objects.get(pk=rehearsal.pk).is_full_setlist)

    def test_manage_assignments_delete_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's POST to the assignment delete endpoint returns 403 and deletes nothing."""
        assignment = SongRoleAssignmentFactory()

        response = self.client.post(reverse('scheduling:manage-assignments-delete', args=[assignment.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(SongRoleAssignment.objects.filter(pk=assignment.pk).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class RehearsalManageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person, with a current Semester."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.semester = SemesterFactory()

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_lists_current_semester_rehearsals(self):
        """The schedule page lists the current Semester's Rehearsals."""
        rehearsal = RehearsalFactory(semester=self.semester)

        response = self.client.get(reverse('scheduling:manage-schedule'))

        self.assertEqual(response.status_code, 200)
        self.assertIn(rehearsal, response.context['rehearsals'])

    def test_valid_post_creates_rehearsal_and_redirects_with_message(self):
        """A valid POST creates a Rehearsal in the current Semester and redirects with a success message."""
        args = {'date': fake.date_between(start_date='+1d', end_date='+120d'), 'start_time': time(18, 0)}

        response = self.client.post(reverse('scheduling:manage-schedule'), args, follow=True)

        self.assertRedirects(response, reverse('scheduling:manage-schedule'))
        created = Rehearsal.objects.get(date=args['date'])
        self.assertEqual(created.semester, self.semester)
        messages = [str(m) for m in response.context['messages']]
        self.assertTrue(any('created' in m for m in messages))

    def test_invalid_post_rerenders_form_with_errors(self):
        """A POST missing required fields re-renders the form with errors, creating nothing."""
        response = self.client.post(reverse('scheduling:manage-schedule'), {})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(Rehearsal.objects.count(), 0)

    def test_edit_get_prefills_form(self):
        """The edit page's form is pre-filled with the target Rehearsal's current values."""
        rehearsal = RehearsalFactory(semester=self.semester)

        response = self.client.get(reverse('scheduling:manage-schedule-edit', args=[rehearsal.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].instance, rehearsal)

    def test_valid_edit_post_updates_rehearsal_and_redirects(self):
        """A valid edit POST updates the Rehearsal and redirects to the schedule list with a success message."""
        rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)

        response = self.client.post(
            reverse('scheduling:manage-schedule-edit', args=[rehearsal.pk]),
            {
                'date': rehearsal.date, 'start_time': rehearsal.start_time, 'end_time': rehearsal.end_time,
                'setup_grace_minutes': rehearsal.setup_grace_minutes,
                'teardown_grace_minutes': rehearsal.teardown_grace_minutes,
                'is_full_setlist': True,
            },
            follow=True,
        )

        self.assertRedirects(response, reverse('scheduling:manage-schedule'))
        self.assertTrue(Rehearsal.objects.get(pk=rehearsal.pk).is_full_setlist)

    def test_edit_post_flipping_is_full_setlist_on_is_blocked_when_conflicts_exist(self):
        """An edit making a Rehearsal with declared Conflicts the Dress Rehearsal re-renders with a counted error (issue #150)."""
        rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)
        ConflictFactory(rehearsal=rehearsal)
        ConflictFactory(rehearsal=rehearsal)

        response = self.client.post(
            reverse('scheduling:manage-schedule-edit', args=[rehearsal.pk]),
            {
                'date': rehearsal.date, 'start_time': rehearsal.start_time, 'end_time': rehearsal.end_time,
                'setup_grace_minutes': rehearsal.setup_grace_minutes,
                'teardown_grace_minutes': rehearsal.teardown_grace_minutes,
                'is_full_setlist': True,
            },
        )

        self.assertEqual(response.status_code, 200)
        errors = response.context['form'].errors['is_full_setlist']
        self.assertEqual(len(errors), 1)
        self.assertIn('2', errors[0])
        self.assertFalse(Rehearsal.objects.get(pk=rehearsal.pk).is_full_setlist)

    def test_edit_post_flipping_is_full_setlist_off_stays_allowed(self):
        """An edit turning the Dress Rehearsal back into an ordinary Rehearsal still succeeds (issue #150)."""
        rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=True)

        response = self.client.post(
            reverse('scheduling:manage-schedule-edit', args=[rehearsal.pk]),
            {
                'date': rehearsal.date, 'start_time': rehearsal.start_time, 'end_time': rehearsal.end_time,
                'setup_grace_minutes': rehearsal.setup_grace_minutes,
                'teardown_grace_minutes': rehearsal.teardown_grace_minutes,
            },
            follow=True,
        )

        self.assertRedirects(response, reverse('scheduling:manage-schedule'))
        self.assertFalse(Rehearsal.objects.get(pk=rehearsal.pk).is_full_setlist)

    def test_invalid_edit_post_rerenders_form_with_errors(self):
        """An invalid edit POST re-renders the edit form with errors, leaving the Rehearsal unchanged."""
        rehearsal = RehearsalFactory(semester=self.semester)

        response = self.client.post(reverse('scheduling:manage-schedule-edit', args=[rehearsal.pk]), {})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)

    def test_edit_404s_for_a_rehearsal_outside_the_current_semester(self):
        """A stale Semester's Rehearsal isn't editable through the current-Semester edit route."""
        stale_rehearsal = RehearsalFactory(semester=self.semester)
        SemesterFactory()  # supersedes self.semester as "current" (most-recently-created)

        response = self.client.get(reverse('scheduling:manage-schedule-edit', args=[stale_rehearsal.pk]))

        self.assertEqual(response.status_code, 404)

    def test_edit_post_moving_the_window_re_derives_scheduled_song_times(self):
        """Moving a Rehearsal's start_time leaves no RehearsalSong claiming the old hours (issue #215)."""
        rehearsal = RehearsalFactory(semester=self.semester, start_time=time(18, 0), is_full_setlist=False)
        first_song = SongFactory(semester=self.semester, position=1)
        second_song = SongFactory(semester=self.semester, position=2)
        first = RehearsalSongFactory(rehearsal=rehearsal, song=first_song, order=1, slot_count=1)
        second = RehearsalSongFactory(rehearsal=rehearsal, song=second_song, order=2, slot_count=1)
        stale_start, stale_end = first.start_time, first.end_time

        self.client.post(
            reverse('scheduling:manage-schedule-edit', args=[rehearsal.pk]),
            {
                'date': rehearsal.date, 'start_time': time(19, 0), 'end_time': rehearsal.end_time,
                'setup_grace_minutes': rehearsal.setup_grace_minutes,
                'teardown_grace_minutes': rehearsal.teardown_grace_minutes,
                'is_full_setlist': False,
            },
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.start_time, time(19, 0))
        self.assertNotEqual(first.start_time, stale_start)
        self.assertNotEqual(first.end_time, stale_end)
        self.assertEqual(first.order, 1)
        self.assertEqual(second.order, 2)

    def test_edit_post_moving_the_window_leaves_order_untouched(self):
        """Re-deriving RehearsalSong times on a window move never changes their order values (issue #215)."""
        rehearsal = RehearsalFactory(semester=self.semester, start_time=time(18, 0), is_full_setlist=False)
        songs = [
            RehearsalSongFactory(rehearsal=rehearsal, song=SongFactory(semester=self.semester, position=n), order=n)
            for n in range(1, 4)
        ]

        self.client.post(
            reverse('scheduling:manage-schedule-edit', args=[rehearsal.pk]),
            {
                'date': rehearsal.date, 'start_time': time(19, 0), 'end_time': rehearsal.end_time,
                'setup_grace_minutes': rehearsal.setup_grace_minutes,
                'teardown_grace_minutes': rehearsal.teardown_grace_minutes,
                'is_full_setlist': False,
            },
        )

        orders = list(
            RehearsalSong.objects.filter(rehearsal=rehearsal).order_by('order').values_list('order', flat=True)
        )
        self.assertEqual(orders, [song.order for song in songs])


@override_settings(SECURE_SSL_REDIRECT=False)
class SongRoleAssignmentManageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic admin Person, with a current Semester and Song."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.semester = SemesterFactory()
        cls.song = SongFactory(semester=cls.semester, position=1)
        cls.role = RoleFactory()

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_lists_current_semester_assignments(self):
        """The assignments page lists SongRoleAssignments for the current Semester's Songs."""
        assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)

        response = self.client.get(reverse('scheduling:manage-assignments'))

        self.assertEqual(response.status_code, 200)
        self.assertIn(assignment, response.context['assignments'])

    def test_valid_post_creates_assignment_and_redirects_with_message(self):
        """A valid POST creates a SongRoleAssignment and redirects with a success message."""
        person = PersonFactory()
        args = {'song': self.song.pk, 'role': self.role.pk, 'person': person.pk}

        response = self.client.post(reverse('scheduling:manage-assignments'), args, follow=True)

        self.assertRedirects(response, reverse('scheduling:manage-assignments'))
        self.assertTrue(SongRoleAssignment.objects.filter(song=self.song, role=self.role, person=person).exists())

    def test_role_mismatch_is_surfaced_in_response(self):
        """An assignment whose Role isn't on the Person's Membership is created and flagged in the response."""
        person = PersonFactory()
        args = {'song': self.song.pk, 'role': self.role.pk, 'person': person.pk}

        self.client.post(reverse('scheduling:manage-assignments'), args)
        response = self.client.get(reverse('scheduling:manage-assignments'))

        assignment = SongRoleAssignment.objects.get(song=self.song, role=self.role, person=person)
        self.assertTrue(assignment.is_role_mismatch)
        self.assertContains(response, 'role mismatch')

    def test_matching_role_is_not_flagged(self):
        """An assignment whose Role matches a declared MembershipRole is not flagged as a mismatch."""
        membership = MembershipFactory(semester=self.semester)
        MembershipRoleFactory(membership=membership, role=self.role)
        args = {'song': self.song.pk, 'role': self.role.pk, 'person': membership.person.pk}

        self.client.post(reverse('scheduling:manage-assignments'), args)

        assignment = SongRoleAssignment.objects.get(song=self.song, role=self.role, person=membership.person)
        self.assertFalse(assignment.is_role_mismatch)

    def test_invalid_post_rerenders_form_with_errors(self):
        """A POST missing required fields re-renders the form with errors, creating nothing."""
        response = self.client.post(reverse('scheduling:manage-assignments'), {})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(SongRoleAssignment.objects.count(), 0)

    def test_duplicate_post_rerenders_form_with_errors(self):
        """A POST duplicating an existing (song, role, person) triple re-renders the form with a uniqueness error."""
        assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)
        args = {'song': self.song.pk, 'role': self.role.pk, 'person': assignment.person.pk}

        response = self.client.post(reverse('scheduling:manage-assignments'), args)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(SongRoleAssignment.objects.filter(song=self.song, role=self.role).count(), 1)

    def test_delete_removes_assignment_and_redirects(self):
        """A POST to the delete endpoint removes the SongRoleAssignment and redirects with a success message."""
        assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)

        response = self.client.post(reverse('scheduling:manage-assignments-delete', args=[assignment.pk]), follow=True)

        self.assertRedirects(response, reverse('scheduling:manage-assignments'))
        self.assertFalse(SongRoleAssignment.objects.filter(pk=assignment.pk).exists())

    def test_delete_404s_for_an_assignment_outside_the_current_semester(self):
        """A stale Semester's SongRoleAssignment isn't removable through the current-Semester delete route."""
        stale_assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)
        SemesterFactory()  # supersedes self.semester as "current" (most-recently-created)

        response = self.client.post(reverse('scheduling:manage-assignments-delete', args=[stale_assignment.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(SongRoleAssignment.objects.filter(pk=stale_assignment.pk).exists())
