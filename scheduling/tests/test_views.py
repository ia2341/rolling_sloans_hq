"""Member read routes (issue #56): /schedule/, /setlist/, /songs/<id>/."""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
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
