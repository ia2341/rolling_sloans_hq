"""`scheduling/serializers.py`'s `serialize_context()`: exact key sets and the privacy verdicts (issue #326)."""

from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase, override_settings

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    RehearsalFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.serializers import serialize_context
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY

CONTEXT_KEYS = {
    'viewer',
    'viewing_semester',
    'live_semester',
    'semester_warning',
    'semester_options',
    'pending_conflict_count',
}
SEMESTER_OPTION_KEYS = {
    'id', 'name', 'status', 'is_viewing', 'member_count', 'song_count', 'rehearsal_count',
}
VIEWING_SEMESTER_KEYS = {'id', 'name', 'status', 'published_at', 'updated_at'}


def _request_for(person):
    """Return a real, session-carrying request for `person`, via the Django test client."""
    factory_request = RequestFactory()
    request = factory_request.get('/')
    request.user = person
    # A plain RequestFactory request has no session; give it one, since
    # get_viewing_semester()/semester_options_for() read request.session.
    request.session = SessionStore()
    return request


@override_settings(SECURE_SSL_REDIRECT=False)
class SerializeContextTests(TestCase):
    """`serialize_context()`'s six-key envelope, for a member and for an admin."""

    def test_exact_key_set(self):
        """The context block has exactly the six documented keys."""
        person = PersonFactory()

        context = serialize_context(_request_for(person))

        self.assertEqual(set(context), CONTEXT_KEYS)

    def test_member_gets_empty_semester_options_and_null_pending_count(self):
        """A member's semester_options is empty and pending_conflict_count is null (ADR 0005)."""
        SemesterFactory()
        person = PersonFactory()

        context = serialize_context(_request_for(person))

        self.assertEqual(context['semester_options'], [])
        self.assertIsNone(context['pending_conflict_count'])

    def test_member_viewing_semester_is_the_live_semester_and_status_live(self):
        """A member's viewing_semester is the Live Semester, with wire status 'live'."""
        live = SemesterFactory()
        person = PersonFactory()

        context = serialize_context(_request_for(person))

        self.assertEqual(context['viewing_semester']['id'], live.pk)
        self.assertEqual(context['viewing_semester']['status'], 'live')
        self.assertEqual(set(context['viewing_semester']), VIEWING_SEMESTER_KEYS)
        self.assertFalse(context['semester_warning'])

    def test_admin_gets_semester_options_with_exactly_one_is_viewing_and_counts(self):
        """An admin's semester_options carries every Semester, exactly one is_viewing, with the three counts."""
        live = SemesterFactory()
        draft = SemesterFactory(draft=True)
        MembershipFactory(semester=live)
        SongFactory(semester=live)
        RehearsalFactory(semester=live)
        person = PersonFactory(is_admin=True)

        context = serialize_context(_request_for(person))

        options = context['semester_options']
        self.assertEqual({option['id'] for option in options}, {live.pk, draft.pk})
        viewing_options = [option for option in options if option['is_viewing']]
        self.assertEqual(len(viewing_options), 1)
        self.assertEqual(viewing_options[0]['id'], live.pk)
        for option in options:
            self.assertEqual(set(option), SEMESTER_OPTION_KEYS)
        live_option = next(option for option in options if option['id'] == live.pk)
        self.assertEqual(live_option['member_count'], 1)
        self.assertEqual(live_option['song_count'], 1)
        self.assertEqual(live_option['rehearsal_count'], 1)

    def test_admin_viewing_a_draft_gets_a_pending_conflict_count_and_a_warning(self):
        """An admin viewing a draft Semester gets an integer pending_conflict_count and semester_warning True."""
        SemesterFactory()  # the Live Semester, so the draft below isn't it
        draft = SemesterFactory(draft=True)
        person = PersonFactory(is_admin=True)
        request = _request_for(person)
        request.session[VIEWING_SEMESTER_SESSION_KEY] = draft.pk

        context = serialize_context(request)

        self.assertEqual(context['viewing_semester']['id'], draft.pk)
        self.assertEqual(context['viewing_semester']['status'], 'draft')
        self.assertTrue(context['semester_warning'])
        self.assertIsInstance(context['pending_conflict_count'], int)

    def test_no_semesters_at_all_gives_null_viewing_and_live_semester(self):
        """With nothing in the database, viewing_semester and live_semester are both null for a member."""
        person = PersonFactory()

        context = serialize_context(_request_for(person))

        self.assertIsNone(context['viewing_semester'])
        self.assertIsNone(context['live_semester'])
        self.assertIsNone(context['pending_conflict_count'])

    def test_viewer_is_the_requesting_person_own_email_only(self):
        """context.viewer carries the requesting Person's own email — never a stand-in for anyone else."""
        person = PersonFactory()

        context = serialize_context(_request_for(person))

        self.assertEqual(context['viewer']['email'], person.email)
        self.assertEqual(context['viewer']['id'], person.pk)
