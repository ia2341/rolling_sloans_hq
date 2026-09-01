"""Member read routes (issue #56): /schedule/, /setlist/, /songs/<id>/."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    MembershipRoleFactory,
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)

PASSWORD = 'a-strong-test-password-123'


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_schedule_redirects_anonymous_users_to_login(self):
        """An anonymous request to /schedule/ redirects to the login page."""
        response = self.client.get(reverse('scheduling:schedule'))

        self.assertRedirects(
            response, f"{reverse('identity:login')}?next={reverse('scheduling:schedule')}",
        )

    def test_setlist_redirects_anonymous_users_to_login(self):
        """An anonymous request to /setlist/ redirects to the login page."""
        response = self.client.get(reverse('scheduling:setlist'))

        self.assertRedirects(
            response, f"{reverse('identity:login')}?next={reverse('scheduling:setlist')}",
        )

    def test_song_detail_redirects_anonymous_users_to_login(self):
        """An anonymous request to /songs/<id>/ redirects to the login page."""
        song = SongFactory()
        url = reverse('scheduling:song-detail', args=[song.pk])

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def _needed_rehearsal(self, semester, date):
        """Build a Rehearsal in `semester` dated `date` with one Song self.person is assigned to."""
        rehearsal = RehearsalFactory(semester=semester, date=date)
        song = SongFactory(semester=semester)
        RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)
        SongRoleAssignmentFactory(song=song, person=self.person)
        return rehearsal

    def test_no_active_semester_renders_placeholder(self):
        """With no Semester at all, renders successfully with no rehearsal/matrix in context."""
        response = self.client.get(reverse('scheduling:schedule'))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['semester'])
        self.assertIsNone(response.context['rehearsal'])

    def test_defaults_to_members_next_rehearsal_when_no_query_param(self):
        """With no ?rehearsal= param, drills into the member's own next Rehearsal."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=1))  # not needed at
        needed = self._needed_rehearsal(semester, timezone.localdate() + timedelta(days=2))

        response = self.client.get(reverse('scheduling:schedule'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['rehearsal'], needed)

    def test_rehearsal_query_param_drills_into_that_rehearsal_regardless_of_entry_point(self):
        """?rehearsal=<id> renders that Rehearsal's detail, not the member's default next Rehearsal."""
        semester = SemesterFactory()
        self._needed_rehearsal(semester, timezone.localdate() + timedelta(days=1))
        target = RehearsalFactory(semester=semester, date=timezone.localdate() + timedelta(days=10))

        response = self.client.get(reverse('scheduling:schedule'), {'rehearsal': target.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['rehearsal'], target)

    def test_default_landing_and_explicit_query_param_render_the_same_rehearsal_identically(self):
        """Landing on the member's next Rehearsal by default renders the same body as drilling in via ?rehearsal=<id>."""
        semester = SemesterFactory()
        needed = self._needed_rehearsal(semester, timezone.localdate() + timedelta(days=1))

        default_response = self.client.get(reverse('scheduling:schedule'))
        query_param_response = self.client.get(reverse('scheduling:schedule'), {'rehearsal': needed.pk})

        self.assertEqual(default_response.context['rehearsal'], needed)
        self.assertEqual(query_param_response.context['rehearsal'], needed)
        self.assertEqual(default_response.context['matrix'].rows, query_param_response.context['matrix'].rows)

    def test_404_for_rehearsal_outside_current_semester(self):
        """?rehearsal=<id> for a Rehearsal in an older Semester 404s."""
        old_semester = SemesterFactory()
        SemesterFactory()  # becomes current
        old_rehearsal = RehearsalFactory(semester=old_semester)

        response = self.client.get(reverse('scheduling:schedule'), {'rehearsal': old_rehearsal.pk})

        self.assertEqual(response.status_code, 404)

    def test_404_for_non_numeric_rehearsal_param(self):
        """A non-numeric ?rehearsal= value 404s instead of raising an unhandled error."""
        SemesterFactory()

        response = self.client.get(reverse('scheduling:schedule'), {'rehearsal': 'not-a-number'})

        self.assertEqual(response.status_code, 404)

    def test_is_role_mismatch_flag_renders_on_mismatched_assignment_cells(self):
        """A mismatched SongRoleAssignment's Person renders with the role-mismatch marker; a matched one doesn't."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester)
        song = SongFactory(semester=semester, position=1)
        RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)
        role = RoleFactory()
        SongRoleRequirementFactory(song=song, role=role, count=1)
        membership = MembershipFactory(person=self.person, semester=semester)
        MembershipRoleFactory(membership=membership, role=role)
        SongRoleAssignmentFactory(song=song, role=role, person=self.person)
        mismatched_person = PersonFactory()
        MembershipFactory(person=mismatched_person, semester=semester)
        SongRoleAssignmentFactory(song=song, role=role, person=mismatched_person)

        response = self.client.get(reverse('scheduling:schedule'), {'rehearsal': rehearsal.pk})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="role-mismatch"', count=1)

    def test_add_a_conflict_link_points_at_conflicts_route_with_rehearsal_param(self):
        """Renders an "Add a conflict" link pointing at the Conflicts route with ?rehearsal=<id>."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester)

        response = self.client.get(reverse('scheduling:schedule'), {'rehearsal': rehearsal.pk})

        expected_href = f"{reverse('scheduling:conflicts')}?rehearsal={rehearsal.pk}"
        self.assertContains(response, f'href="{expected_href}"')


@override_settings(SECURE_SSL_REDIRECT=False)
class SetlistViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_renders_current_semesters_songs_in_position_order(self):
        """Renders successfully, listing only the current Semester's Songs in position order."""
        old_semester = SemesterFactory()
        current_semester = SemesterFactory()
        SongFactory(semester=old_semester)
        second_song = SongFactory(semester=current_semester, position=2)
        first_song = SongFactory(semester=current_semester, position=1)

        response = self.client.get(reverse('scheduling:setlist'))

        self.assertEqual(response.status_code, 200)
        songs = list(response.context['songs'])
        self.assertEqual(songs, [first_song, second_song])

    def test_includes_rehearsal_count_progress_per_song(self):
        """Each Song in context carries its rehearsal-count actual/target progress indicators."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        rehearsal = RehearsalFactory(semester=semester, is_full_setlist=False)
        RehearsalSongFactory(song=song, rehearsal=rehearsal, order=1)

        response = self.client.get(reverse('scheduling:setlist'))

        self.assertEqual(response.status_code, 200)
        [rendered_song] = response.context['songs']
        self.assertEqual(rendered_song.rehearsal_count_actual, 1)
        self.assertEqual(rendered_song.rehearsal_count_target, 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class SongDetailViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_renders_assignments_and_recordings(self):
        """Lists the Song's SongRoleAssignments and Recordings."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        assignment = SongRoleAssignmentFactory(song=song)
        rehearsal = RehearsalFactory(semester=semester)
        rehearsal_song = RehearsalSongFactory(song=song, rehearsal=rehearsal)
        recording = RecordingFactory(rehearsal_song=rehearsal_song)

        response = self.client.get(reverse('scheduling:song-detail', args=[song.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn(assignment, response.context['assignments'])
        self.assertIn(recording, response.context['recordings'])

    def test_computes_rehearsal_count_target_vs_actual(self):
        """actual counts this Song's RehearsalSong rows; target counts the Semester's non-Dress Rehearsals."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        rehearsal_one = RehearsalFactory(semester=semester, is_full_setlist=False)
        rehearsal_two = RehearsalFactory(semester=semester, is_full_setlist=False)
        RehearsalFactory(semester=semester, is_full_setlist=True)
        RehearsalSongFactory(song=song, rehearsal=rehearsal_one, order=1)
        RehearsalSongFactory(song=song, rehearsal=rehearsal_two, order=1)

        response = self.client.get(reverse('scheduling:song-detail', args=[song.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['rehearsal_count_actual'], 2)
        self.assertEqual(response.context['rehearsal_count_target'], 2)

    def test_404_for_unknown_song(self):
        """A request for a nonexistent Song id returns 404."""
        response = self.client.get(reverse('scheduling:song-detail', args=[999999]))

        self.assertEqual(response.status_code, 404)

    def test_404_for_song_from_an_older_semester(self):
        """A Song belonging to a non-current Semester is not reachable by id."""
        old_semester = SemesterFactory()
        old_song = SongFactory(semester=old_semester)
        SemesterFactory()  # becomes the current Semester

        response = self.client.get(reverse('scheduling:song-detail', args=[old_song.pk]))

        self.assertEqual(response.status_code, 404)
