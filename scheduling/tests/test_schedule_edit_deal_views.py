"""`/schedule/edit/deal/` and `/schedule/edit/rehearsal/<id>/shuffle/`: the balanced dealer's endpoints (issue #223)."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import Rehearsal, RehearsalSong
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY
from scheduling.tests.preview_helpers import assert_preview_writes_nothing

PASSWORD = 'a-strong-test-password-123'
TOMORROW = timezone.localdate() + timedelta(days=1)


def admin_client(test_case):
    """Log a synthetic admin Person into `test_case`'s client and return that Person."""
    person = PersonFactory(password=PASSWORD, is_admin=True)
    test_case.client.login(username=person.email, password=PASSWORD)
    return person


def member_client(test_case):
    """Log a synthetic non-admin Person into `test_case`'s client and return that Person."""
    person = PersonFactory(password=PASSWORD)
    test_case.client.login(username=person.email, password=PASSWORD)
    return person


def select(test_case, semester):
    """Record `semester` as the client's session selection, mirroring `services.set_viewing_semester`."""
    session = test_case.client.session
    session[VIEWING_SEMESTER_SESSION_KEY] = semester.pk
    session.save()


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditDealViewTests(TestCase):
    def test_post_redirects_anonymous_users_to_login(self):
        """An anonymous POST redirects to the login page."""
        SemesterFactory()
        url = reverse('scheduling:schedule-edit-deal')

        response = self.client.post(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_post_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's POST returns 403."""
        SemesterFactory()
        member_client(self)

        response = self.client.post(reverse('scheduling:schedule-edit-deal'))

        self.assertEqual(response.status_code, 403)

    def test_refuses_an_empty_setlist_with_400(self):
        """An empty setlist is refused with a 400 naming the reason."""
        semester = SemesterFactory()
        RehearsalFactory(semester=semester, date=TOMORROW, is_full_setlist=False)
        admin_client(self)

        response = self.client.post(reverse('scheduling:schedule-edit-deal'))

        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_refuses_no_eligible_rehearsals_with_400(self):
        """No eligible Rehearsal is refused with a 400 naming the reason."""
        semester = SemesterFactory()
        SongFactory(semester=semester)
        admin_client(self)

        response = self.client.post(reverse('scheduling:schedule-edit-deal'))

        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_writes_nothing(self):
        """A deal POST leaves every RehearsalSong/Rehearsal row untouched."""
        semester = SemesterFactory()
        for _ in range(3):
            SongFactory(semester=semester)
        RehearsalFactory(semester=semester, date=TOMORROW, is_full_setlist=False)
        admin_client(self)

        response = assert_preview_writes_nothing(
            self, reverse('scheduling:schedule-edit-deal'), {},
            models_to_check=[Rehearsal, RehearsalSong],
            semester=semester,
        )

        self.assertIn('rehearsals', response.json())

    def test_returns_a_deal_for_every_eligible_rehearsal(self):
        """The JSON body carries one entry per eligible Rehearsal, each with the setlist's dealt rows."""
        semester = SemesterFactory(default_song_slot_count=3)
        for _ in range(3):
            SongFactory(semester=semester)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, is_full_setlist=False)
        admin_client(self)

        response = self.client.post(reverse('scheduling:schedule-edit-deal'))

        body = response.json()
        self.assertEqual(len(body['rehearsals']), 1)
        self.assertEqual(body['rehearsals'][0]['rehearsal_id'], rehearsal.pk)
        self.assertEqual(len(body['rehearsals'][0]['rows']), 3)
        for row in body['rehearsals'][0]['rows']:
            self.assertEqual(row['slot_count'], 1)
            self.assertIsNone(row['rehearsal_song_id'])


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleEditShuffleViewTests(TestCase):
    def test_post_redirects_anonymous_users_to_login(self):
        """An anonymous POST redirects to the login page."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, is_full_setlist=False)
        url = reverse('scheduling:schedule-edit-shuffle', args=[rehearsal.pk])

        response = self.client.post(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_post_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's POST returns 403."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, is_full_setlist=False)
        member_client(self)

        response = self.client.post(reverse('scheduling:schedule-edit-shuffle', args=[rehearsal.pk]))

        self.assertEqual(response.status_code, 403)

    def test_returns_404_for_a_rehearsal_outside_the_viewing_semester(self):
        """A Rehearsal belonging to a different Semester than the viewing one returns 404."""
        semester = SemesterFactory()
        other_semester = SemesterFactory()
        other_rehearsal = RehearsalFactory(semester=other_semester, date=TOMORROW, is_full_setlist=False)
        admin_client(self)
        select(self, semester)

        response = self.client.post(reverse('scheduling:schedule-edit-shuffle', args=[other_rehearsal.pk]))

        self.assertEqual(response.status_code, 404)

    def test_writes_nothing(self):
        """A shuffle POST leaves every RehearsalSong row untouched."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, is_full_setlist=False)
        for i in range(4):
            RehearsalSongFactory(rehearsal=rehearsal, song=SongFactory(semester=semester), order=i + 1)
        admin_client(self)
        select(self, semester)

        response = assert_preview_writes_nothing(
            self, reverse('scheduling:schedule-edit-shuffle', args=[rehearsal.pk]), {},
            models_to_check=[RehearsalSong],
            semester=semester,
        )

        self.assertEqual(len(response.json()['rows']), 4)

    def test_returns_empty_rows_for_a_rehearsal_with_no_running_order(self):
        """A Rehearsal with no RehearsalSong rows yet returns an empty rows list, not an error."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, is_full_setlist=False)
        admin_client(self)

        response = self.client.post(reverse('scheduling:schedule-edit-shuffle', args=[rehearsal.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['rows'], [])

    def test_pinned_row_stays_at_its_own_order_in_the_response(self):
        """A Recording-bearing row's identity appears at the same index in the response, every time."""
        semester = SemesterFactory()
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, is_full_setlist=False)
        rehearsal_songs = [
            RehearsalSongFactory(rehearsal=rehearsal, song=SongFactory(semester=semester), order=i + 1)
            for i in range(5)
        ]
        pinned = rehearsal_songs[2]
        RecordingFactory(rehearsal_song=pinned)
        admin_client(self)
        select(self, semester)
        url = reverse('scheduling:schedule-edit-shuffle', args=[rehearsal.pk])

        for _ in range(5):
            response = self.client.post(url)
            rows = response.json()['rows']
            self.assertEqual(rows[2]['rehearsal_song_id'], pinned.pk)
