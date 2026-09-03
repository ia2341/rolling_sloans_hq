"""Semester lifecycle resolution: the Live Semester and the per-request viewing Semester (issue #167)."""

from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    RehearsalFactory,
    SemesterFactory,
    SongFactory,
)
from scheduling.services import (
    VIEWING_SEMESTER_SESSION_KEY,
    get_live_semester,
    get_viewing_semester,
    set_viewing_semester,
)

PASSWORD = 'a-strong-test-password-123'


class GetLiveSemesterTests(TestCase):
    def test_no_semesters_at_all_is_none(self):
        """With no Semester rows, there is no Live Semester."""
        self.assertIsNone(get_live_semester())

    def test_a_draft_is_never_live(self):
        """A Semester with a null published_at is a draft and is excluded from the Live Semester."""
        SemesterFactory(draft=True)

        self.assertIsNone(get_live_semester())

    def test_live_is_the_greatest_published_at(self):
        """The Live Semester is the greatest published_at, not the greatest id or the newest created."""
        published_first = SemesterFactory(published_at=timezone.now())
        published_later = SemesterFactory(published_at=timezone.now() + timedelta(days=1))
        SemesterFactory(published_at=timezone.now() - timedelta(days=1))

        self.assertEqual(get_live_semester(), published_later)
        self.assertNotEqual(get_live_semester(), published_first)

    def test_republishing_an_older_semester_makes_it_live_again(self):
        """Bumping an older Semester's published_at past the incumbent's makes it the Live Semester."""
        older = SemesterFactory(published_at=timezone.now() - timedelta(days=30))
        newer = SemesterFactory(published_at=timezone.now())
        self.assertEqual(get_live_semester(), newer)

        older.published_at = timezone.now() + timedelta(seconds=1)
        older.save()

        self.assertEqual(get_live_semester(), older)


class GetViewingSemesterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build the RequestFactory the per-request resolution tests drive."""
        cls.factory = RequestFactory()

    def _request(self, user, selected_semester_id=None):
        """Return a GET request carrying `user` and, optionally, a session semester selection."""
        request = self.factory.get('/')
        request.user = user
        request.session = self.client.session
        if selected_semester_id is not None:
            request.session[VIEWING_SEMESTER_SESSION_KEY] = selected_semester_id
        return request

    def test_member_gets_the_live_semester(self):
        """A non-admin's request resolves to the Live Semester."""
        SemesterFactory(draft=True)
        live = SemesterFactory(published_at=timezone.now())

        self.assertEqual(get_viewing_semester(self._request(PersonFactory())), live)

    def test_member_gets_none_when_nothing_is_published(self):
        """With only drafts in the database, a non-admin resolves to None — the admin fallback is not theirs."""
        SemesterFactory(draft=True)

        self.assertIsNone(get_viewing_semester(self._request(PersonFactory())))

    def test_member_session_selection_is_ignored(self):
        """A session selection carried by a non-admin account is ignored, never honoured."""
        draft = SemesterFactory(draft=True)
        live = SemesterFactory(published_at=timezone.now())

        request = self._request(PersonFactory(), selected_semester_id=draft.pk)

        self.assertEqual(get_viewing_semester(request), live)

    def test_admin_with_a_selection_gets_that_semester(self):
        """An admin's session selection wins over the Live Semester, for reads and writes alike."""
        draft = SemesterFactory(draft=True)
        SemesterFactory(published_at=timezone.now())

        request = self._request(PersonFactory(is_admin=True), selected_semester_id=draft.pk)

        self.assertEqual(get_viewing_semester(request), draft)

    def test_admin_without_a_selection_gets_the_live_semester(self):
        """An admin who has selected nothing sees exactly what members see."""
        SemesterFactory(draft=True)
        live = SemesterFactory(published_at=timezone.now())

        self.assertEqual(get_viewing_semester(self._request(PersonFactory(is_admin=True))), live)

    def test_admin_falls_back_to_the_most_recently_created_semester_when_nothing_is_published(self):
        """A solo admin bootstrapping the first term sees their unpublished draft rather than empty states."""
        SemesterFactory(draft=True)
        newest_draft = SemesterFactory(draft=True)

        self.assertEqual(get_viewing_semester(self._request(PersonFactory(is_admin=True))), newest_draft)

    def test_no_semesters_at_all_is_none_for_an_admin(self):
        """An admin resolves to None when the database holds no Semester at all."""
        self.assertIsNone(get_viewing_semester(self._request(PersonFactory(is_admin=True))))

    def test_selection_pointing_at_a_deleted_semester_falls_back_to_live(self):
        """A stale selection resolves to the Live Semester rather than raising."""
        live = SemesterFactory(published_at=timezone.now())
        deleted = SemesterFactory(draft=True)
        deleted_pk = deleted.pk
        deleted.delete()

        request = self._request(PersonFactory(is_admin=True), selected_semester_id=deleted_pk)

        self.assertEqual(get_viewing_semester(request), live)

    def test_selection_held_by_an_account_that_lost_admin_falls_back_to_live(self):
        """An account demoted mid-session sees exactly what a member sees."""
        draft = SemesterFactory(draft=True)
        live = SemesterFactory(published_at=timezone.now())

        request = self._request(PersonFactory(is_admin=False), selected_semester_id=draft.pk)

        self.assertEqual(get_viewing_semester(request), live)

    def test_anonymous_request_gets_the_live_semester(self):
        """An anonymous request resolves to the Live Semester rather than raising on a missing is_admin."""
        live = SemesterFactory(published_at=timezone.now())

        self.assertEqual(get_viewing_semester(self._request(AnonymousUser())), live)


class SetViewingSemesterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build the RequestFactory the selection-recording tests drive."""
        cls.factory = RequestFactory()

    def _request(self):
        """Return a GET request carrying a real session."""
        request = self.factory.get('/')
        request.session = self.client.session
        return request

    def test_records_the_selection_in_the_session(self):
        """set_viewing_semester writes the selection into request.session, where it dies at logout."""
        semester = SemesterFactory(draft=True)
        request = self._request()

        set_viewing_semester(request, semester)

        self.assertEqual(request.session[VIEWING_SEMESTER_SESSION_KEY], semester.pk)

    def test_none_clears_the_selection(self):
        """Passing None clears any selection, returning the admin to the Live Semester."""
        request = self._request()
        set_viewing_semester(request, SemesterFactory(draft=True))

        set_viewing_semester(request, None)

        self.assertNotIn(VIEWING_SEMESTER_SESSION_KEY, request.session)

    def test_clearing_an_absent_selection_is_harmless(self):
        """Clearing when nothing is selected is a no-op rather than a KeyError."""
        request = self._request()

        set_viewing_semester(request, None)

        self.assertNotIn(VIEWING_SEMESTER_SESSION_KEY, request.session)


@override_settings(SECURE_SSL_REDIRECT=False)
class SelectionDiesAtLogoutTests(TestCase):
    def test_logging_out_discards_the_selection(self):
        """The selection lives in the session, so logging out drops it."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)
        draft = SemesterFactory(draft=True)
        session = self.client.session
        session[VIEWING_SEMESTER_SESSION_KEY] = draft.pk
        session.save()

        self.client.post(reverse('identity:logout'))

        self.assertNotIn(VIEWING_SEMESTER_SESSION_KEY, self.client.session)


@override_settings(SECURE_SSL_REDIRECT=False)
class MemberRouteScopingTests(TestCase):
    """Every band-wide route renders the Live Semester's data for a member, and no draft's."""

    @classmethod
    def setUpTestData(cls):
        """Build a synthetic non-admin Person, with one live Semester and one newer draft."""
        cls.person = PersonFactory(password=PASSWORD)
        cls.live = SemesterFactory(published_at=timezone.now())
        cls.draft = SemesterFactory(draft=True)

    def setUp(self):
        """Log in as the synthetic Person before each test."""
        self.client.login(username=self.person.email, password=PASSWORD)

    def _band_wide_urls(self):
        """Return every band-wide route a member reads the viewing Semester through."""
        return [
            reverse('scheduling:overview'),
            reverse('scheduling:schedule'),
            reverse('scheduling:setlist'),
            reverse('scheduling:members'),
            reverse('scheduling:member-detail', args=[self.person.pk]),
        ]

    def test_every_band_wide_route_names_the_live_semester_and_not_the_draft(self):
        """A member's pages carry the Live Semester in context, never the newer draft."""
        for url in self._band_wide_urls():
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['semester'], self.live)

    def test_a_drafts_songs_are_invisible_on_the_setlist(self):
        """A Song belonging to a draft never appears on a member's Songs page."""
        SongFactory(semester=self.draft, position=1)
        live_song = SongFactory(semester=self.live, position=1)

        response = self.client.get(reverse('scheduling:setlist'))

        self.assertEqual([song.pk for song in response.context['songs']], [live_song.pk])

    def test_a_drafts_roster_is_invisible_on_band_members(self):
        """A Membership belonging to a draft never appears on a member's Band Members page."""
        MembershipFactory(semester=self.draft)
        live_membership = MembershipFactory(semester=self.live)

        response = self.client.get(reverse('scheduling:members'))

        self.assertEqual([row.pk for row in response.context['members']], [live_membership.pk])

    def test_a_drafts_song_detail_page_404s_for_a_member(self):
        """A draft's Song is out of a member's reach entirely, not merely absent from the list."""
        draft_song = SongFactory(semester=self.draft, position=1)

        response = self.client.get(reverse('scheduling:song-detail', args=[draft_song.pk]))

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class UnpublishedSiteTests(TestCase):
    """With nothing published, a member's routes render empty rather than erroring."""

    @classmethod
    def setUpTestData(cls):
        """Build a synthetic non-admin Person against a database holding only a populated draft."""
        cls.person = PersonFactory(password=PASSWORD)
        cls.draft = SemesterFactory(draft=True)
        RehearsalFactory(semester=cls.draft)
        SongFactory(semester=cls.draft, position=1)
        MembershipFactory(semester=cls.draft, person=cls.person)

    def setUp(self):
        """Log in as the synthetic Person before each test."""
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_every_band_wide_route_renders_empty_for_a_member(self):
        """Each band-wide route returns 200 with no Semester in context when nothing is published."""
        urls = [
            reverse('scheduling:overview'),
            reverse('scheduling:schedule'),
            reverse('scheduling:setlist'),
            reverse('scheduling:members'),
            reverse('scheduling:member-detail', args=[self.person.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.context['semester'])

    def test_the_recordings_route_renders_an_empty_picker(self):
        """/me/recordings/ renders its empty state rather than offering the draft's slots."""
        response = self.client.get(reverse('scheduling:recordings'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['has_rehearsal_song_options'])

    def test_the_setlist_and_roster_are_empty(self):
        """The draft's Songs and Memberships render as zero rows rather than leaking through."""
        setlist = self.client.get(reverse('scheduling:setlist'))
        members = self.client.get(reverse('scheduling:members'))

        self.assertEqual(list(setlist.context['songs']), [])
        self.assertEqual(list(members.context['members']), [])


@override_settings(SECURE_SSL_REDIRECT=False)
class PublishVisibilityTests(TestCase):
    """Publishing changes what a member's next request renders, with no re-login."""

    @classmethod
    def setUpTestData(cls):
        """Build a synthetic non-admin Person, before anything is published."""
        cls.person = PersonFactory(password=PASSWORD)
        cls.draft = SemesterFactory(draft=True)

    def setUp(self):
        """Log in as the synthetic Person before each test."""
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_a_session_predating_the_publish_sees_the_new_live_semester(self):
        """A member logged in before the publish sees the newly-live Semester on their next request."""
        self.assertIsNone(self.client.get(reverse('scheduling:overview')).context['semester'])

        self.draft.published_at = timezone.now()
        self.draft.save()

        self.assertEqual(self.client.get(reverse('scheduling:overview')).context['semester'], self.draft)
