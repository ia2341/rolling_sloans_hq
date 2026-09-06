"""`/api/semesters/...`: the SPA's semester-control surface — management rows, publish/delete popups, select, create, and Reapply defaults (issue #329).

Ports the behavioural cases from the pre-SPA prior art
(`test_semester_manage_views.py`, `test_semester_switcher.py`,
`test_create_semester.py`, `test_semester_deletion.py`,
`test_semester_defaults_reapply_view.py`/`test_semester_defaults_reapply.py`)
onto the new envelope-shaped endpoints, without touching any of those
files or the server-rendered views they cover.
"""

import json
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.models import Rehearsal, Semester
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY
from scheduling.tests.preview_helpers import assert_preview_writes_nothing

PASSWORD = 'a-strong-test-password-123'
TOMORROW = timezone.localdate() + timedelta(days=1)
YESTERDAY = timezone.localdate() - timedelta(days=1)

TIMING_DEFAULTS = {
    'default_rehearsal_duration_minutes': 240,
    'default_setup_grace_minutes': 10,
    'default_teardown_grace_minutes': 10,
    'default_song_slot_count': 6,
    'default_arrival_buffer_minutes': 5,
    'default_departure_buffer_minutes': 5,
}


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


def post_json(test_case, url, body):
    """POST `body` (a dict) as a JSON request body and return `(response, envelope)`."""
    response = test_case.client.post(url, data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


def get_json(test_case, url):
    """GET `url` and return `(response, envelope)`."""
    response = test_case.client.get(url)
    return response, json.loads(response.content)


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """Every new `/api/semesters/...` route is admin-gated: 401 anonymously, 403 for a non-admin, never a 302."""

    def setUp(self):
        """Build one Semester so parameterised routes have a pk to resolve."""
        self.semester = SemesterFactory(draft=True)

    def _routes(self):
        """Return every new route as `(url, method)`, zero-argument and parameterised alike."""
        return [
            (reverse('api-semesters-management-rows'), 'get'),
            (reverse('api-semesters-publish-impact', args=[self.semester.pk]), 'get'),
            (reverse('api-semesters-deletion-summary', args=[self.semester.pk]), 'get'),
            (reverse('api-semesters-select'), 'post'),
            (reverse('api-semesters-create'), 'post'),
            (reverse('api-semesters-publish', args=[self.semester.pk]), 'post'),
            (reverse('api-semesters-delete', args=[self.semester.pk]), 'post'),
            (reverse('api-semesters-reapply-defaults-preview'), 'post'),
            (reverse('api-semesters-reapply-defaults-save'), 'post'),
        ]

    def test_every_route_401s_anonymously_and_never_302s(self):
        """An anonymous request to every new route answers the documented JSON 401, never a redirect."""
        for url, method in self._routes():
            with self.subTest(url=url, method=method):
                response = getattr(self.client, method)(url, data='{}', content_type='application/json') \
                    if method == 'post' else self.client.get(url)
                self.assertEqual(response.status_code, 401)
                self.assertNotIn('Location', response)

    def test_every_route_is_403_for_a_non_admin(self):
        """A logged-in non-admin's request to every new route is rejected with the documented JSON 403."""
        member_client(self)
        for url, method in self._routes():
            with self.subTest(url=url, method=method):
                response = getattr(self.client, method)(url, data='{}', content_type='application/json') \
                    if method == 'post' else self.client.get(url)
                self.assertEqual(response.status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class ManagementRowsApiTests(TestCase):
    """`GET /api/semesters/management-rows/`: one row per Semester with its label and four counts."""

    def test_lists_every_semester_newest_created_first_with_counts_and_viewing_flag(self):
        """Each row carries its status, is_viewing flag, and member/song/rehearsal/recording counts."""
        older = SemesterFactory()
        live = SemesterFactory()
        draft = SemesterFactory(draft=True)
        MembershipFactory(semester=draft)
        song = SongFactory(semester=draft)
        rehearsal = RehearsalFactory(semester=draft)
        RecordingFactory(rehearsal_song__rehearsal=rehearsal, rehearsal_song__song=song)
        admin_client(self)
        select(self, draft)

        response, envelope = get_json(self, reverse('api-semesters-management-rows'))

        self.assertEqual(response.status_code, 200)
        rows = envelope['data']
        self.assertEqual([row['id'] for row in rows], [draft.pk, live.pk, older.pk])
        draft_row = rows[0]
        self.assertTrue(draft_row['is_viewing'])
        self.assertEqual(draft_row['status'], 'draft')
        self.assertEqual(draft_row['member_count'], 1)
        self.assertEqual(draft_row['song_count'], 1)
        self.assertEqual(draft_row['rehearsal_count'], 1)
        self.assertEqual(draft_row['recording_count'], 1)
        self.assertEqual(rows[1]['status'], 'live')


@override_settings(SECURE_SSL_REDIRECT=False)
class PublishImpactApiTests(TestCase):
    """`GET /api/semesters/<pk>/publish-impact/`: the incumbent Live Semester's name/counts plus the empty-setlist flags."""

    def test_names_the_incumbent_and_its_counts(self):
        """A draft's publish-impact names the current Live Semester and its rehearsal/song counts."""
        live = SemesterFactory()
        RehearsalFactory(semester=live)
        SongFactory(semester=live)
        draft = SemesterFactory(draft=True)
        admin_client(self)

        response, envelope = get_json(self, reverse('api-semesters-publish-impact', args=[draft.pk]))

        self.assertEqual(response.status_code, 200)
        data = envelope['data']
        self.assertFalse(data['is_already_live'])
        self.assertEqual(data['incumbent']['id'], live.pk)
        self.assertEqual(data['incumbent_rehearsal_count'], 1)
        self.assertEqual(data['incumbent_song_count'], 1)
        self.assertTrue(data['has_no_setlist'])
        self.assertTrue(data['has_no_rehearsals'])

    def test_already_live_reports_no_incumbent(self):
        """Publishing the already-Live Semester reports is_already_live with no incumbent."""
        live = SemesterFactory()
        admin_client(self)

        response, envelope = get_json(self, reverse('api-semesters-publish-impact', args=[live.pk]))

        self.assertEqual(response.status_code, 200)
        data = envelope['data']
        self.assertTrue(data['is_already_live'])
        self.assertIsNone(data['incumbent'])
        self.assertEqual(data['incumbent_rehearsal_count'], 0)
        self.assertEqual(data['incumbent_song_count'], 0)

    def test_404s_for_a_nonexistent_semester(self):
        """A pk naming no Semester 404s."""
        admin_client(self)

        response = self.client.get(reverse('api-semesters-publish-impact', args=[999999]))

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class DeletionSummaryApiTests(TestCase):
    """`GET /api/semesters/<pk>/deletion-summary/`: wraps `semester_deletion_summary()`, recomputing nothing."""

    def test_wraps_the_four_existing_counts(self):
        """The endpoint's data carries exactly `semester_deletion_summary()`'s four counts."""
        draft = SemesterFactory(draft=True)
        MembershipFactory(semester=draft)
        SongFactory(semester=draft)
        rehearsal = RehearsalFactory(semester=draft)
        RecordingFactory(rehearsal_song__rehearsal=rehearsal)
        admin_client(self)

        response, envelope = get_json(self, reverse('api-semesters-deletion-summary', args=[draft.pk]))

        self.assertEqual(response.status_code, 200)
        data = envelope['data']
        self.assertEqual(data['member_count'], 1)
        self.assertEqual(data['song_count'], 1)
        self.assertEqual(data['rehearsal_count'], 1)
        self.assertEqual(data['recording_count'], 1)

    def test_404s_for_a_nonexistent_semester(self):
        """A pk naming no Semester 404s."""
        admin_client(self)

        response = self.client.get(reverse('api-semesters-deletion-summary', args=[999999]))

        self.assertEqual(response.status_code, 404)

    def test_carries_no_conflict_identifying_data(self):
        """Per ADR 0005, the payload's keys are counts only — no reason/note/person-identity key exists at all."""
        draft = SemesterFactory(draft=True)
        admin_client(self)

        _, envelope = get_json(self, reverse('api-semesters-deletion-summary', args=[draft.pk]))

        self.assertEqual(
            set(envelope['data'].keys()), {'member_count', 'song_count', 'rehearsal_count', 'recording_count'},
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class SelectApiTests(TestCase):
    """`POST /api/semesters/select/`: records or clears this session's Viewing Semester selection."""

    def test_selecting_a_semester_updates_the_context(self):
        """Selecting a draft makes it the context's viewing_semester on the very same response."""
        SemesterFactory()
        draft = SemesterFactory(draft=True)
        admin_client(self)

        response, envelope = post_json(self, reverse('api-semesters-select'), {'semester_id': draft.pk})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertEqual(envelope['context']['viewing_semester']['id'], draft.pk)

    def test_selecting_null_clears_and_falls_back_to_live(self):
        """A null semester_id clears the selection, falling back to the Live Semester."""
        live = SemesterFactory()
        draft = SemesterFactory(draft=True)
        admin_client(self)
        select(self, draft)

        response, envelope = post_json(self, reverse('api-semesters-select'), {'semester_id': None})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(VIEWING_SEMESTER_SESSION_KEY, self.client.session)
        self.assertEqual(envelope['context']['viewing_semester']['id'], live.pk)

    def test_an_unknown_semester_id_clears_the_selection_silently(self):
        """A semester_id matching no Semester clears the selection rather than erroring."""
        SemesterFactory()
        admin_client(self)

        response, envelope = post_json(self, reverse('api-semesters-select'), {'semester_id': 999999})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertNotIn(VIEWING_SEMESTER_SESSION_KEY, self.client.session)

    def test_a_deleted_selection_falls_back_silently_on_the_next_read(self):
        """A selection pointing at a since-deleted Semester yields the Live Semester on a later context read, no error."""
        live = SemesterFactory()
        draft = SemesterFactory(draft=True)
        admin_client(self)
        select(self, draft)
        draft.delete()

        response, envelope = get_json(self, reverse('api-semesters-management-rows'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(envelope['context']['viewing_semester']['id'], live.pk)

    def test_exactly_one_option_carries_is_viewing(self):
        """The context's semester_options carries is_viewing on exactly the resolved viewing Semester."""
        SemesterFactory()
        draft = SemesterFactory(draft=True)
        admin_client(self)
        select(self, draft)

        _, envelope = get_json(self, reverse('api-semesters-management-rows'))

        viewing_options = [option for option in envelope['context']['semester_options'] if option['is_viewing']]
        self.assertEqual([option['id'] for option in viewing_options], [draft.pk])

    def test_malformed_semester_id_is_a_400(self):
        """A non-integer semester_id is genuinely malformed, not a per-field Validation Error."""
        admin_client(self)

        response, _ = post_json(self, reverse('api-semesters-select'), {'semester_id': 'not-an-int'})

        self.assertEqual(response.status_code, 400)


@override_settings(SECURE_SSL_REDIRECT=False)
class CreateApiTests(TestCase):
    """`POST /api/semesters/create/`: creates a draft and selects it, or reports a name error at HTTP 200."""

    def test_creates_a_draft_with_timing_defaults_and_selects_it(self):
        """A successful create leaves the caller's viewing Semester set to the new draft."""
        admin_client(self)
        body = {'name': 'Fall 2026', **TIMING_DEFAULTS}

        response, envelope = post_json(self, reverse('api-semesters-create'), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        semester = Semester.objects.get(name='Fall 2026')
        self.assertIsNone(semester.published_at)
        for field, value in TIMING_DEFAULTS.items():
            self.assertEqual(getattr(semester, field), value)
        self.assertEqual(envelope['context']['viewing_semester']['id'], semester.pk)

    def test_blank_name_is_ok_false_at_http_200(self):
        """A blank name is a per-field error at HTTP 200, not a 4xx."""
        admin_client(self)
        body = {'name': '   ', **TIMING_DEFAULTS}

        response, envelope = post_json(self, reverse('api-semesters-create'), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertIn('name', envelope['errors'])
        self.assertFalse(Semester.objects.exists())

    def test_duplicate_name_case_insensitive_is_ok_false_at_http_200(self):
        """A name matching an existing Semester (any case) is a per-field error at HTTP 200, not a 4xx."""
        SemesterFactory(name='Fall 2026')
        admin_client(self)
        body = {'name': 'fall 2026', **TIMING_DEFAULTS}

        response, envelope = post_json(self, reverse('api-semesters-create'), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertIn('name', envelope['errors'])
        self.assertEqual(Semester.objects.count(), 1)

    def test_missing_name_is_a_400(self):
        """A missing/non-string name is genuinely malformed, not a per-field Validation Error."""
        admin_client(self)
        body = {**TIMING_DEFAULTS}

        response, _ = post_json(self, reverse('api-semesters-create'), body)

        self.assertEqual(response.status_code, 400)

    def test_a_non_integer_timing_default_is_a_400(self):
        """A malformed timing-default field is genuinely malformed, not a per-field Validation Error."""
        admin_client(self)
        body = {'name': 'Fall 2026', **TIMING_DEFAULTS, 'default_song_slot_count': 'six'}

        response, _ = post_json(self, reverse('api-semesters-create'), body)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Semester.objects.exists())

    def test_a_negative_timing_default_is_a_400(self):
        """A negative timing-default field is genuinely malformed, not a per-field Validation Error."""
        admin_client(self)
        body = {'name': 'Fall 2026', **TIMING_DEFAULTS, 'default_song_slot_count': -1}

        response, _ = post_json(self, reverse('api-semesters-create'), body)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Semester.objects.exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class PublishApiTests(TestCase):
    """`POST /api/semesters/<pk>/publish/`: publishes the target Semester through the same endpoint rollback uses."""

    def test_publish_makes_a_draft_live(self):
        """Publishing a draft stamps published_at and makes it the Live Semester."""
        draft = SemesterFactory(draft=True)
        admin_client(self)

        response, envelope = post_json(self, reverse('api-semesters-publish', args=[draft.pk]), {})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        draft.refresh_from_db()
        self.assertIsNotNone(draft.published_at)

    def test_republishing_the_already_live_semester_is_harmless(self):
        """Publishing the already-live Semester through this endpoint leaves it live (rollback path)."""
        live = SemesterFactory()
        admin_client(self)

        response, envelope = post_json(self, reverse('api-semesters-publish', args=[live.pk]), {})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])

    def test_404s_for_a_nonexistent_semester(self):
        """A pk naming no Semester 404s."""
        admin_client(self)

        response = self.client.post(reverse('api-semesters-publish', args=[999999]))

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class DeleteApiTests(TestCase):
    """`POST /api/semesters/<pk>/delete/`: calls delete_semester() and reports its Live-Semester refusal."""

    def test_deletes_a_draft(self):
        """Deleting a draft removes it."""
        draft = SemesterFactory(draft=True)
        admin_client(self)

        with self.captureOnCommitCallbacks(execute=True):
            response, envelope = post_json(self, reverse('api-semesters-delete', args=[draft.pk]), {})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertFalse(Semester.objects.filter(pk=draft.pk).exists())

    def test_refuses_to_delete_the_live_semester(self):
        """Deleting the Live Semester is refused as ok:false with a non_field_errors message, not a 4xx."""
        live = SemesterFactory()
        admin_client(self)

        response, envelope = post_json(self, reverse('api-semesters-delete', args=[live.pk]), {})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.assertTrue(Semester.objects.filter(pk=live.pk).exists())

    def test_404s_for_a_nonexistent_semester(self):
        """A pk naming no Semester 404s."""
        admin_client(self)

        response = self.client.post(reverse('api-semesters-delete', args=[999999]))

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class ReapplyDefaultsPreviewApiTests(TestCase):
    """`POST /api/semesters/reapply-defaults/preview/`: run for real, rolled back (ADR 0008)."""

    def test_preview_writes_nothing_and_reports_the_changed_count(self):
        """A valid Buffer previews ok:true, reports changed_rehearsal_count, and writes nothing."""
        semester = SemesterFactory(default_setup_grace_minutes=20)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, setup_grace_minutes=1)
        admin_client(self)
        body = {'semester_id': semester.pk, 'semester_updated_at': semester.updated_at.isoformat()}

        response = assert_preview_writes_nothing(
            self, reverse('api-semesters-reapply-defaults-preview'),
            models_to_check=[Rehearsal], semester=semester, json_body=body,
        )
        envelope = json.loads(response.content)

        self.assertTrue(envelope['ok'])
        self.assertFalse(envelope['fallout']['is_blocked'])
        self.assertEqual(envelope['fallout']['changed_rehearsal_count'], 1)
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 1)

    def test_preview_reports_blocked_for_a_nonexistent_semester(self):
        """A semester_id naming no Semester reports is_blocked, not a 404/500."""
        admin_client(self)
        body = {'semester_id': 999999, 'semester_updated_at': timezone.now().isoformat()}

        response, envelope = post_json(self, reverse('api-semesters-reapply-defaults-preview'), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertTrue(envelope['fallout']['is_blocked'])

    def test_malformed_body_is_ok_false_with_non_field_errors(self):
        """A missing semester_id is a validation failure reported as ok:false, not a 4xx."""
        admin_client(self)

        response, envelope = post_json(
            self, reverse('api-semesters-reapply-defaults-preview'), {'semester_updated_at': 'not-a-datetime'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])


@override_settings(SECURE_SSL_REDIRECT=False)
class ReapplyDefaultsSaveApiTests(TestCase):
    """`POST /api/semesters/reapply-defaults/save/`: the real, committing write."""

    def test_save_reapplies_the_defaults(self):
        """A valid Buffer applies the Semester's current defaults onto its upcoming Rehearsals."""
        semester = SemesterFactory(default_setup_grace_minutes=20)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, setup_grace_minutes=1)
        admin_client(self)
        body = {'semester_id': semester.pk, 'semester_updated_at': semester.updated_at.isoformat()}

        response, envelope = post_json(self, reverse('api-semesters-reapply-defaults-save'), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 20)

    def test_a_stale_stamp_is_reported_as_ok_false_and_writes_nothing(self):
        """A stale semester_updated_at is reported, not refused with a 4xx, and applies nothing."""
        semester = SemesterFactory(default_setup_grace_minutes=20)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, setup_grace_minutes=1)
        stale_stamp = semester.updated_at.isoformat()
        semester.updated_at = timezone.now()
        semester.save(update_fields=['updated_at'])
        admin_client(self)
        body = {'semester_id': semester.pk, 'semester_updated_at': stale_stamp}

        response, envelope = post_json(self, reverse('api-semesters-reapply-defaults-save'), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 1)

    def test_a_blocked_reapply_is_reported_as_ok_false_and_writes_nothing(self):
        """A shrunk default_song_slot_count that would overrun a RehearsalSong is reported blocked, not a 4xx."""
        semester = SemesterFactory(default_song_slot_count=5, default_setup_grace_minutes=20)
        rehearsal = RehearsalFactory(semester=semester, date=TOMORROW, setup_grace_minutes=1)
        RehearsalSongFactory(rehearsal=rehearsal, order=1, slot_count=5)
        semester.default_song_slot_count = 1
        semester.save(update_fields=['default_song_slot_count'])
        admin_client(self)
        body = {'semester_id': semester.pk, 'semester_updated_at': semester.updated_at.isoformat()}

        response, envelope = post_json(self, reverse('api-semesters-reapply-defaults-save'), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        rehearsal.refresh_from_db()
        self.assertEqual(rehearsal.setup_grace_minutes, 1)
