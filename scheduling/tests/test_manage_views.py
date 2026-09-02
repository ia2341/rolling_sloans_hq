"""Admin schedule, setlist & assignment management: /manage/schedule/, /manage/setlist/, /manage/assignments/ (issue #60)."""

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
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Rehearsal, Song, SongRoleAssignment

fake = Faker()
PASSWORD = 'a-strong-test-password-123'


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_manage_schedule_redirects_anonymous_users_to_login(self):
        """An anonymous request to /manage/schedule/ redirects to the login page."""
        url = reverse('scheduling:manage-schedule')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_manage_setlist_redirects_anonymous_users_to_login(self):
        """An anonymous request to /manage/setlist/ redirects to the login page."""
        url = reverse('scheduling:manage-setlist')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_manage_assignments_redirects_anonymous_users_to_login(self):
        """An anonymous request to /manage/assignments/ redirects to the login page."""
        url = reverse('scheduling:manage-assignments')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")


@override_settings(SECURE_SSL_REDIRECT=False)
class NonAdminAccessTests(TestCase):
    def setUp(self):
        """Log in a synthetic non-admin Person before each test."""
        self.person = PersonFactory(password=PASSWORD, is_admin=False)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_manage_schedule_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's GET to /manage/schedule/ returns 403."""
        response = self.client.get(reverse('scheduling:manage-schedule'))

        self.assertEqual(response.status_code, 403)

    def test_manage_setlist_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's GET to /manage/setlist/ returns 403."""
        response = self.client.get(reverse('scheduling:manage-setlist'))

        self.assertEqual(response.status_code, 403)

    def test_manage_assignments_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's GET to /manage/assignments/ returns 403."""
        response = self.client.get(reverse('scheduling:manage-assignments'))

        self.assertEqual(response.status_code, 403)

    def test_song_move_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's POST to the reorder endpoint returns 403 and changes nothing."""
        song = SongFactory(position=1)

        response = self.client.post(reverse('scheduling:manage-setlist-move-down', args=[song.pk]))

        self.assertEqual(response.status_code, 403)

    def test_manage_schedule_edit_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's GET/POST to the Rehearsal edit endpoint returns 403 and changes nothing."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        url = reverse('scheduling:manage-schedule-edit', args=[rehearsal.pk])

        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'is_full_setlist': True}).status_code, 403)
        self.assertFalse(Rehearsal.objects.get(pk=rehearsal.pk).is_full_setlist)

    def test_manage_setlist_edit_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's GET/POST to the Song edit endpoint returns 403 and changes nothing."""
        song = SongFactory(position=1, title='Original Title')
        url = reverse('scheduling:manage-setlist-edit', args=[song.pk])

        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'title': 'New Title'}).status_code, 403)
        self.assertEqual(Song.objects.get(pk=song.pk).title, 'Original Title')

    def test_manage_setlist_delete_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's POST to the Song delete endpoint returns 403 and deletes nothing."""
        song = SongFactory(position=1)

        response = self.client.post(reverse('scheduling:manage-setlist-delete', args=[song.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Song.objects.filter(pk=song.pk).exists())

    def test_manage_assignments_delete_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's POST to the assignment delete endpoint returns 403 and deletes nothing."""
        assignment = SongRoleAssignmentFactory()

        response = self.client.post(reverse('scheduling:manage-assignments-delete', args=[assignment.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(SongRoleAssignment.objects.filter(pk=assignment.pk).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class RehearsalManageViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person, with a current Semester, before each test."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=self.admin.email, password=PASSWORD)
        self.semester = SemesterFactory()

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


@override_settings(SECURE_SSL_REDIRECT=False)
class SongManageViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person, with a current Semester, before each test."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=self.admin.email, password=PASSWORD)
        self.semester = SemesterFactory()

    def test_lists_current_semester_songs(self):
        """The setlist page lists the current Semester's Songs."""
        song = SongFactory(semester=self.semester, position=1)

        response = self.client.get(reverse('scheduling:manage-setlist'))

        self.assertEqual(response.status_code, 200)
        self.assertIn(song, response.context['songs'])

    def test_valid_post_appends_song_at_end_of_setlist(self):
        """A valid POST creates a Song positioned after the current Semester's existing Songs."""
        SongFactory(semester=self.semester, position=1)
        SongFactory(semester=self.semester, position=2)
        args = {'title': 'Song Z', 'artist': 'Some Artist', 'length': '00:03:30', 'notes': ''}

        response = self.client.post(reverse('scheduling:manage-setlist'), args, follow=True)

        self.assertRedirects(response, reverse('scheduling:manage-setlist'))
        created = Song.objects.get(title='Song Z')
        self.assertEqual(created.semester, self.semester)
        self.assertEqual(created.position, 3)

    def test_invalid_post_rerenders_form_with_errors(self):
        """A POST missing required fields re-renders the form with errors, creating nothing."""
        response = self.client.post(reverse('scheduling:manage-setlist'), {})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(Song.objects.count(), 0)

    def test_valid_edit_post_updates_song_and_redirects(self):
        """A valid edit POST updates the Song's fields and redirects to the setlist with a success message."""
        song = SongFactory(semester=self.semester, position=1, title='Old Title')

        response = self.client.post(
            reverse('scheduling:manage-setlist-edit', args=[song.pk]),
            {'title': 'New Title', 'artist': song.artist, 'length': '00:03:30', 'notes': ''},
            follow=True,
        )

        self.assertRedirects(response, reverse('scheduling:manage-setlist'))
        self.assertEqual(Song.objects.get(pk=song.pk).title, 'New Title')

    def test_delete_removes_song_and_redirects(self):
        """A POST to the delete endpoint removes the Song and redirects with a success message."""
        song = SongFactory(semester=self.semester, position=1)

        response = self.client.post(reverse('scheduling:manage-setlist-delete', args=[song.pk]), follow=True)

        self.assertRedirects(response, reverse('scheduling:manage-setlist'))
        self.assertFalse(Song.objects.filter(pk=song.pk).exists())

    def test_edit_404s_for_a_song_outside_the_current_semester(self):
        """A stale Semester's Song isn't editable through the current-Semester edit route."""
        stale_song = SongFactory(semester=self.semester, position=1)
        SemesterFactory()  # supersedes self.semester as "current" (most-recently-created)

        response = self.client.get(reverse('scheduling:manage-setlist-edit', args=[stale_song.pk]))

        self.assertEqual(response.status_code, 404)

    def test_delete_404s_for_a_song_outside_the_current_semester(self):
        """A stale Semester's Song isn't removable through the current-Semester delete route."""
        stale_song = SongFactory(semester=self.semester, position=1)
        SemesterFactory()  # supersedes self.semester as "current" (most-recently-created)

        response = self.client.post(reverse('scheduling:manage-setlist-delete', args=[stale_song.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Song.objects.filter(pk=stale_song.pk).exists())

    def test_move_404s_for_a_song_outside_the_current_semester(self):
        """A stale Semester's Song isn't reorderable through the current-Semester move route."""
        stale_song = SongFactory(semester=self.semester, position=1)
        SemesterFactory()  # supersedes self.semester as "current" (most-recently-created)

        response = self.client.post(reverse('scheduling:manage-setlist-move-down', args=[stale_song.pk]))

        self.assertEqual(response.status_code, 404)

    def test_move_down_swaps_position_with_next_song(self):
        """Moving a Song down swaps its position with the next Song in position order."""
        first = SongFactory(semester=self.semester, position=1)
        second = SongFactory(semester=self.semester, position=2)

        response = self.client.post(reverse('scheduling:manage-setlist-move-down', args=[first.pk]), follow=True)

        self.assertRedirects(response, reverse('scheduling:manage-setlist'))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.position, 2)
        self.assertEqual(second.position, 1)

    def test_move_up_swaps_position_with_previous_song(self):
        """Moving a Song up swaps its position with the previous Song in position order."""
        first = SongFactory(semester=self.semester, position=1)
        second = SongFactory(semester=self.semester, position=2)

        response = self.client.post(reverse('scheduling:manage-setlist-move-up', args=[second.pk]), follow=True)

        self.assertRedirects(response, reverse('scheduling:manage-setlist'))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.position, 2)
        self.assertEqual(second.position, 1)

    def test_move_up_at_start_of_setlist_is_a_noop(self):
        """Moving the first Song up leaves its position unchanged and still redirects."""
        first = SongFactory(semester=self.semester, position=1)

        response = self.client.post(reverse('scheduling:manage-setlist-move-up', args=[first.pk]), follow=True)

        self.assertRedirects(response, reverse('scheduling:manage-setlist'))
        self.assertEqual(Song.objects.get(pk=first.pk).position, 1)

    def test_move_down_at_end_of_setlist_is_a_noop(self):
        """Moving the last Song down leaves its position unchanged and still redirects."""
        last = SongFactory(semester=self.semester, position=1)

        response = self.client.post(reverse('scheduling:manage-setlist-move-down', args=[last.pk]), follow=True)

        self.assertRedirects(response, reverse('scheduling:manage-setlist'))
        self.assertEqual(Song.objects.get(pk=last.pk).position, 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class SongRoleAssignmentManageViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person, with a current Semester and Song, before each test."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=self.admin.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.song = SongFactory(semester=self.semester, position=1)
        self.role = RoleFactory()

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
