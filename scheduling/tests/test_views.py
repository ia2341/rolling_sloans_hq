"""Member read routes (issue #56): /schedule/, /setlist/, /songs/<id>/, and the Overview (issue #94)."""

from datetime import datetime, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
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

    def test_renders_current_semesters_rehearsals(self):
        """Renders successfully, listing only the current Semester's Rehearsals."""
        old_semester = SemesterFactory()
        current_semester = SemesterFactory()
        RehearsalFactory(semester=old_semester)
        current_rehearsal = RehearsalFactory(semester=current_semester)

        response = self.client.get(reverse('scheduling:schedule'))

        self.assertEqual(response.status_code, 200)
        rehearsals = list(response.context['rehearsals'])
        self.assertEqual(rehearsals, [current_rehearsal])


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
