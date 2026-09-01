"""Member read routes (issue #56): /schedule/, /setlist/, /songs/<id>/, and the Overview (issue #94)."""

from datetime import date, datetime, time, timedelta
from unittest.mock import patch

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


@override_settings(SECURE_SSL_REDIRECT=False)
class OverviewViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_next_rehearsal_card_skips_a_rehearsal_the_person_is_not_needed_at(self):
        """The Next Rehearsal card picks the earliest Rehearsal the Person is actually needed at, not the band's literal next one."""
        semester = SemesterFactory()
        role = RoleFactory()
        today = timezone.localdate()
        soon_rehearsal = RehearsalFactory(semester=semester, date=today + timedelta(days=1))
        RehearsalSongFactory(rehearsal=soon_rehearsal, song=SongFactory(semester=semester), order=1)
        later_rehearsal = RehearsalFactory(semester=semester, date=today + timedelta(days=5))
        later_song = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=later_rehearsal, song=later_song, order=1)
        SongRoleAssignmentFactory(song=later_song, role=role, person=self.person)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['next_rehearsal'], later_rehearsal)
        self.assertContains(response, f'?rehearsal={later_rehearsal.pk}')

    def test_next_rehearsal_card_includes_a_rehearsal_needed_only_for_a_middle_song(self):
        """A Person assigned only to a middle RehearsalSong (needed at neither end) still counts as needing that Rehearsal."""
        semester = SemesterFactory()
        role = RoleFactory()
        today = timezone.localdate()
        rehearsal = RehearsalFactory(semester=semester, date=today + timedelta(days=1))
        first_song = SongFactory(semester=semester)
        middle_song = SongFactory(semester=semester)
        last_song = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=first_song, order=1)
        RehearsalSongFactory(rehearsal=rehearsal, song=middle_song, order=2)
        RehearsalSongFactory(rehearsal=rehearsal, song=last_song, order=3)
        SongRoleAssignmentFactory(song=middle_song, role=role, person=self.person)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['next_rehearsal'], rehearsal)
        self.assertIsNotNone(response.context['next_rehearsal_suggestion'])

    @patch('scheduling.services.timezone.localtime')
    @patch('scheduling.services.timezone.localdate')
    def test_next_rehearsal_excludes_a_same_day_rehearsal_that_already_ended(self, mock_localdate, mock_localtime):
        """A Rehearsal earlier today whose end_time has already passed isn't offered as the Person's next Rehearsal."""
        fixed_date = date(2026, 3, 10)
        mock_localdate.return_value = fixed_date
        mock_localtime.return_value = datetime.combine(fixed_date, time(12, 0))
        semester = SemesterFactory()
        role = RoleFactory()
        ended_rehearsal = RehearsalFactory(semester=semester, date=fixed_date, start_time=time(9, 0), end_time=time(10, 0))
        ended_song = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=ended_rehearsal, song=ended_song, order=1)
        SongRoleAssignmentFactory(song=ended_song, role=role, person=self.person)
        future_rehearsal = RehearsalFactory(semester=semester, date=fixed_date + timedelta(days=1))
        future_song = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=future_rehearsal, song=future_song, order=1)
        SongRoleAssignmentFactory(song=future_song, role=role, person=self.person)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['next_rehearsal'], future_rehearsal)

    def test_partial_attendance_suggestion_buffers_the_persons_own_assigned_slots(self):
        """Needed only from the start: arrival/departure buffer applies around the Person's own assigned slot, not the whole Rehearsal."""
        semester = SemesterFactory()
        role = RoleFactory()
        today = timezone.localdate()
        rehearsal = RehearsalFactory(semester=semester, date=today + timedelta(days=1))
        first_song = SongFactory(semester=semester)
        middle_song = SongFactory(semester=semester)
        last_song = SongFactory(semester=semester)
        first_slot = RehearsalSongFactory(rehearsal=rehearsal, song=first_song, order=1)
        RehearsalSongFactory(rehearsal=rehearsal, song=middle_song, order=2)
        RehearsalSongFactory(rehearsal=rehearsal, song=last_song, order=3)
        SongRoleAssignmentFactory(song=first_song, role=role, person=self.person)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertEqual(response.status_code, 200)
        suggestion = response.context['next_rehearsal_suggestion']
        expected_arrival = (
            datetime.combine(rehearsal.date, first_slot.start_time) - timedelta(minutes=rehearsal.arrival_buffer_minutes)
        ).time()
        expected_departure = (
            datetime.combine(rehearsal.date, first_slot.end_time) + timedelta(minutes=rehearsal.departure_buffer_minutes)
        ).time()
        self.assertEqual(suggestion.arrival_time, expected_arrival)
        self.assertEqual(suggestion.departure_time, expected_departure)

    def test_preview_shows_not_needed_note_for_a_rehearsal_with_zero_assignments(self):
        """The 3-rehearsal preview lists a Rehearsal with zero SongRoleAssignments as an explicit "not needed" row, never omitted."""
        semester = SemesterFactory()
        role = RoleFactory()
        today = timezone.localdate()
        needed_rehearsal = RehearsalFactory(semester=semester, date=today + timedelta(days=1))
        needed_song = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=needed_rehearsal, song=needed_song, order=1)
        SongRoleAssignmentFactory(song=needed_song, role=role, person=self.person)
        not_needed_rehearsal = RehearsalFactory(semester=semester, date=today + timedelta(days=2))
        RehearsalSongFactory(rehearsal=not_needed_rehearsal, song=SongFactory(semester=semester), order=1)
        RehearsalFactory(semester=semester, date=today + timedelta(days=3))

        response = self.client.get(reverse('scheduling:overview'))

        self.assertEqual(response.status_code, 200)
        preview = response.context['upcoming_rehearsals']
        self.assertEqual(len(preview), 3)
        suggestions_by_rehearsal = dict(preview)
        self.assertIsNotNone(suggestions_by_rehearsal[needed_rehearsal])
        self.assertIsNone(suggestions_by_rehearsal[not_needed_rehearsal])
        self.assertContains(response, 'not needed at this rehearsal')

    def test_dress_rehearsal_suggestion_uses_rehearsal_window_not_per_song_times(self):
        """A Dress Rehearsal suggestion falls back to the Rehearsal's own start/end, since no RehearsalSong rows exist (ADR-0003)."""
        semester = SemesterFactory()
        role = RoleFactory()
        today = timezone.localdate()
        dress_rehearsal = RehearsalFactory(semester=semester, date=today + timedelta(days=1), is_full_setlist=True)
        first_song = SongFactory(semester=semester, position=1)
        SongFactory(semester=semester, position=2)
        SongRoleAssignmentFactory(song=first_song, role=role, person=self.person)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['next_rehearsal'], dress_rehearsal)
        suggestion = response.context['next_rehearsal_suggestion']
        self.assertEqual(suggestion.arrival_time, dress_rehearsal.start_time)
        self.assertEqual(suggestion.departure_time, dress_rehearsal.end_time)
