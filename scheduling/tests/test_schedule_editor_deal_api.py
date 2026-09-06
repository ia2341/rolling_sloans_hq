"""`/api/schedule/editor/deal/` and `/api/schedule/editor/rehearsal/<id>/shuffle/` over HTTP (issue #337, #223)."""

import json
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from scheduling.factories import (
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import RehearsalSong
from scheduling.tests.api_test_helpers import (
    admin_client,
    member_client,
    select,
)

TOMORROW = timezone.localdate() + timedelta(days=1)
NEXT_WEEK = timezone.localdate() + timedelta(days=7)


def _deal_url():
    """Return the deal `/api/` endpoint's URL."""
    return reverse('api-schedule-editor-deal')


def _shuffle_url(rehearsal_id):
    """Return the per-Rehearsal shuffle `/api/` endpoint's URL."""
    return reverse('api-schedule-editor-shuffle', args=[rehearsal_id])


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """Both routes gate identically to every other `AdminApiView`."""

    def setUp(self):
        """Build a Semester and a Rehearsal so a request has something to resolve against."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(semester=self.semester, date=TOMORROW)

    def test_anonymous_deal_is_401(self):
        """An anonymous POST to Deal answers the documented JSON 401, never a redirect."""
        response = self.client.post(_deal_url())

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_anonymous_shuffle_is_401(self):
        """An anonymous POST to Shuffle answers the documented JSON 401, never a redirect."""
        response = self.client.post(_shuffle_url(self.rehearsal.pk))

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_non_admin_deal_is_403(self):
        """A logged-in non-admin's POST to Deal is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_deal_url())

        self.assertEqual(response.status_code, 403)

    def test_non_admin_shuffle_is_403(self):
        """A logged-in non-admin's POST to Shuffle is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_shuffle_url(self.rehearsal.pk))

        self.assertEqual(response.status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class DealTests(TestCase):
    """`ScheduleEditorDealApiView` proposes a balanced deal, writing nothing."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with two Songs and two eligible Rehearsals."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.songs = [SongFactory(semester=self.semester, position=n) for n in range(1, 3)]
        self.rehearsal_a = RehearsalFactory(semester=self.semester, date=TOMORROW)
        self.rehearsal_b = RehearsalFactory(semester=self.semester, date=NEXT_WEEK)

    def test_a_valid_deal_fills_every_eligible_rehearsal_and_writes_nothing(self):
        """A valid deal returns one entry per eligible Rehearsal and creates no `RehearsalSong` row."""
        count_before = RehearsalSong.objects.count()

        response = self.client.post(_deal_url())
        envelope = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertIn('context', envelope)
        rehearsal_ids = {entry['rehearsal_id'] for entry in envelope['data']['rehearsals']}
        self.assertEqual(rehearsal_ids, {self.rehearsal_a.pk, self.rehearsal_b.pk})
        self.assertEqual(RehearsalSong.objects.count(), count_before)

    def test_a_pinned_rows_identity_order_and_slot_count_survive_a_deal(self):
        """A deal leaves every pinned row's id, order, and slot_count identical (issue #223)."""
        pinned = RehearsalSongFactory(rehearsal=self.rehearsal_a, song=self.songs[0], order=1, slot_count=2)

        response = self.client.post(_deal_url())
        envelope = json.loads(response.content)

        rehearsal_a_rows = next(
            entry['rows'] for entry in envelope['data']['rehearsals'] if entry['rehearsal_id'] == self.rehearsal_a.pk
        )
        pinned_echo = next(row for row in rehearsal_a_rows if row['rehearsal_song_id'] == pinned.pk)
        self.assertEqual(pinned_echo['song_id'], self.songs[0].pk)
        self.assertEqual(pinned_echo['slot_count'], 2)

    def test_empty_setlist_is_refused_naming_why(self):
        """A Semester with no Songs at all refuses the deal, naming why (never a silent no-op)."""
        empty_semester = SemesterFactory()
        select(self, empty_semester)
        RehearsalFactory(semester=empty_semester, date=TOMORROW)

        response = self.client.post(_deal_url())

        self.assertEqual(response.status_code, 400)
        self.assertIn('error', json.loads(response.content))

    def test_no_eligible_rehearsal_is_refused_naming_why(self):
        """A Semester with Songs but no eligible (non-Dress, non-past) Rehearsal refuses the deal, naming why."""
        semester = SemesterFactory()
        select(self, semester)
        SongFactory(semester=semester, position=1)

        response = self.client.post(_deal_url())

        self.assertEqual(response.status_code, 400)


@override_settings(SECURE_SSL_REDIRECT=False)
class ShuffleTests(TestCase):
    """`ScheduleEditorShuffleApiView` reorders one Rehearsal's own Running Order, writing nothing."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one Rehearsal."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.rehearsal = RehearsalFactory(semester=self.semester, date=TOMORROW)

    def test_a_rehearsal_with_no_rows_is_a_no_op_not_an_error(self):
        """A Rehearsal carrying no Running Order rows shuffles to an empty list, not an error (issue #223)."""
        response = self.client.post(_shuffle_url(self.rehearsal.pk))
        envelope = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(envelope['data']['rows'], [])

    def test_a_rehearsal_outside_the_viewing_semester_is_404(self):
        """A `rehearsal_id` naming a Rehearsal outside the viewing Semester 404s, not a Validation Error."""
        other_semester = SemesterFactory()
        other_rehearsal = RehearsalFactory(semester=other_semester, date=TOMORROW)

        response = self.client.post(_shuffle_url(other_rehearsal.pk))

        self.assertEqual(response.status_code, 404)

    def test_shuffle_reorders_without_writing(self):
        """A Rehearsal with several rows shuffles them (client-side proposal only) and writes nothing to the database."""
        songs = [SongFactory(semester=self.semester, position=n) for n in range(1, 4)]
        rows = [
            RehearsalSongFactory(rehearsal=self.rehearsal, song=song, order=index + 1)
            for index, song in enumerate(songs)
        ]
        orders_before = list(RehearsalSong.objects.filter(rehearsal=self.rehearsal).order_by('order').values_list('order', flat=True))

        response = self.client.post(_shuffle_url(self.rehearsal.pk))
        envelope = json.loads(response.content)

        self.assertEqual(len(envelope['data']['rows']), len(rows))
        orders_after = list(RehearsalSong.objects.filter(rehearsal=self.rehearsal).order_by('order').values_list('order', flat=True))
        self.assertEqual(orders_before, orders_after)
