"""The Overview semester switcher and the non-live Semester banner (issue #169)."""

from datetime import time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import SemesterFactory, SongFactory
from scheduling.models import Rehearsal
from scheduling.services import (
    SEMESTER_STATUS_DRAFT,
    SEMESTER_STATUS_LIVE,
    SEMESTER_STATUS_PREVIOUSLY_PUBLISHED,
    VIEWING_SEMESTER_SESSION_KEY,
    semester_options_for,
)

PASSWORD = 'a-strong-test-password-123'

BANNER_MARKER = 'data-testid="semester-banner"'
PANEL_MARKER = 'data-testid="semester-panel"'


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
    """POST the switcher to select `semester` (or clear the selection when None) and return the response."""
    return test_case.client.post(
        reverse('scheduling:manage-semester-select'),
        {'semester': '' if semester is None else semester.pk},
    )


@override_settings(SECURE_SSL_REDIRECT=False)
class SemesterOptionsTests(TestCase):
    def test_options_are_newest_created_first_and_labelled(self):
        """Every Semester is listed newest-created first, labelled Live, Draft or Previously published."""
        older = SemesterFactory()
        live = SemesterFactory()
        draft = SemesterFactory(draft=True)
        request = self._admin_request()

        options = semester_options_for(request)

        self.assertEqual([option.semester for option in options], [draft, live, older])
        self.assertEqual(
            [option.status for option in options],
            [SEMESTER_STATUS_DRAFT, SEMESTER_STATUS_LIVE, SEMESTER_STATUS_PREVIOUSLY_PUBLISHED],
        )

    def test_the_viewing_semester_is_flagged(self):
        """Exactly the resolved viewing Semester carries is_viewing, so the dropdown can preselect it."""
        SemesterFactory()
        draft = SemesterFactory(draft=True)
        request = self._admin_request()
        request.session[VIEWING_SEMESTER_SESSION_KEY] = draft.pk

        options = semester_options_for(request)

        self.assertEqual([option.semester for option in options if option.is_viewing], [draft])

    def test_a_member_gets_no_options(self):
        """A non-admin has no Semester to choose from, so the read itself returns nothing."""
        SemesterFactory()
        request = self._member_request()

        self.assertEqual(semester_options_for(request), [])

    def _admin_request(self):
        """Return a real request carrying a logged-in admin and a session, via the Overview page."""
        admin_client(self)
        return self.client.get(reverse('scheduling:overview')).wsgi_request

    def _member_request(self):
        """Return a real request carrying a logged-in non-admin and a session."""
        member_client(self)
        return self.client.get(reverse('scheduling:overview')).wsgi_request


@override_settings(SECURE_SSL_REDIRECT=False)
class SwitcherPanelTests(TestCase):
    def test_the_overview_panel_lists_every_semester_for_an_admin(self):
        """An admin's Overview holds the panel, with an option per Semester and its label."""
        live = SemesterFactory()
        draft = SemesterFactory(draft=True)
        admin_client(self)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertContains(response, PANEL_MARKER)
        self.assertContains(response, live.name)
        self.assertContains(response, draft.name)
        self.assertContains(response, SEMESTER_STATUS_DRAFT)

    def test_the_panel_posts_to_the_switcher(self):
        """The panel is a plain POST form aimed at the switcher route, so it works without JavaScript."""
        SemesterFactory()
        admin_client(self)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertContains(response, f'action="{reverse("scheduling:manage-semester-select")}"')
        self.assertContains(response, 'method="post"')

    def test_a_member_never_sees_the_panel(self):
        """A non-admin's Overview holds no panel and no Semester options."""
        SemesterFactory()
        member_client(self)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertNotContains(response, PANEL_MARKER)


@override_settings(SECURE_SSL_REDIRECT=False)
class SwitcherPostTests(TestCase):
    def test_selecting_a_semester_persists_across_pages(self):
        """A selection made on Overview still scopes a later request to a different page."""
        SemesterFactory()
        draft = SemesterFactory(draft=True)
        draft_song = SongFactory(semester=draft)
        admin_client(self)

        select(self, draft)

        response = self.client.get(reverse('scheduling:setlist'))
        self.assertContains(response, draft_song.title)

    def test_selecting_redirects_back_to_the_requesting_page(self):
        """The switcher is POST-and-redirect, landing back on the page that submitted it."""
        semester = SemesterFactory()
        admin_client(self)

        response = self.client.post(
            reverse('scheduling:manage-semester-select'),
            {'semester': semester.pk, 'next': reverse('scheduling:setlist')},
        )

        self.assertRedirects(response, reverse('scheduling:setlist'))

    def test_an_off_site_next_falls_back_to_the_overview(self):
        """A `next` pointing off-site is ignored, so the switcher can't be used as an open redirect."""
        semester = SemesterFactory()
        admin_client(self)

        response = self.client.post(
            reverse('scheduling:manage-semester-select'),
            {'semester': semester.pk, 'next': 'https://evil.example.com/'},
        )

        self.assertRedirects(response, reverse('scheduling:overview'))

    def test_an_empty_selection_returns_to_the_live_semester(self):
        """Submitting an empty value clears the selection, putting the admin back on the Live Semester."""
        live = SemesterFactory()
        live_song = SongFactory(semester=live)
        draft = SemesterFactory(draft=True)
        admin_client(self)
        select(self, draft)

        select(self, None)

        self.assertNotIn(VIEWING_SEMESTER_SESSION_KEY, self.client.session)
        self.assertContains(self.client.get(reverse('scheduling:setlist')), live_song.title)

    def test_an_unknown_semester_clears_the_selection(self):
        """A pk matching no Semester leaves the admin on the Live Semester rather than erroring."""
        SemesterFactory()
        admin_client(self)

        response = self.client.post(reverse('scheduling:manage-semester-select'), {'semester': '999999'})

        self.assertEqual(response.status_code, 302)
        self.assertNotIn(VIEWING_SEMESTER_SESSION_KEY, self.client.session)

    def test_the_selection_dies_at_logout(self):
        """Logging out drops the session and with it the Semester selection."""
        SemesterFactory()
        draft = SemesterFactory(draft=True)
        admin_client(self)
        select(self, draft)

        self.client.post(reverse('identity:logout'))

        self.assertNotIn(VIEWING_SEMESTER_SESSION_KEY, self.client.session)

    def test_a_member_posting_the_switcher_is_forbidden(self):
        """A logged-in non-admin is rejected with 403 by the shared admin-required mixin."""
        semester = SemesterFactory()
        member_client(self)

        response = select(self, semester)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(VIEWING_SEMESTER_SESSION_KEY, self.client.session)

    def test_an_anonymous_switcher_post_redirects_to_login(self):
        """An anonymous POST redirects to login, via the same mixin's login gate."""
        semester = SemesterFactory()

        response = select(self, semester)

        url = reverse('scheduling:manage-semester-select')
        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}", fetch_redirect_response=False)

    def test_the_switcher_rejects_a_get(self):
        """The switcher is POST-only: a GET is a 405, not a page."""
        admin_client(self)

        response = self.client.get(reverse('scheduling:manage-semester-select'))

        self.assertEqual(response.status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
class SelectionGovernsWritesTests(TestCase):
    def test_a_manage_write_lands_on_the_selected_draft(self):
        """An admin viewing a draft who creates a Rehearsal writes it to the draft, leaving the Live Semester untouched."""
        live = SemesterFactory()
        draft = SemesterFactory(draft=True)
        admin_client(self)
        select(self, draft)

        self.client.post(
            reverse('scheduling:manage-schedule'),
            {'date': timezone.now().date() + timedelta(days=1), 'start_time': time(18, 0)},
        )

        self.assertTrue(Rehearsal.objects.filter(semester=draft).exists())
        self.assertFalse(Rehearsal.objects.filter(semester=live).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class BannerTests(TestCase):
    NAV_PAGES: tuple[str, ...] = (
        'scheduling:overview',
        'scheduling:schedule',
        'scheduling:setlist',
        'scheduling:members',
    )

    def test_the_banner_renders_on_every_page_while_a_draft_is_selected(self):
        """With a draft selected, every nav page carries the banner — it comes from the shared shell."""
        SemesterFactory()
        draft = SemesterFactory(draft=True)
        admin_client(self)
        select(self, draft)

        for view_name in self.NAV_PAGES:
            with self.subTest(view_name=view_name):
                response = self.client.get(reverse(view_name))

                self.assertContains(response, BANNER_MARKER)
                self.assertContains(response, draft.name)

    def test_the_banner_says_it_is_not_what_members_see_and_offers_a_way_back(self):
        """The banner names the viewed Semester, says members don't see it, and posts back to the Live Semester."""
        SemesterFactory()
        draft = SemesterFactory(draft=True)
        admin_client(self)
        select(self, draft)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertContains(response, 'not what members see')
        self.assertContains(response, f'action="{reverse("scheduling:manage-semester-select")}"')

    def test_no_banner_on_the_live_semester(self):
        """An admin with no selection is on the Live Semester, so no page shows the banner."""
        SemesterFactory()
        admin_client(self)

        for view_name in self.NAV_PAGES:
            with self.subTest(view_name=view_name):
                self.assertNotContains(self.client.get(reverse(view_name)), BANNER_MARKER)

    def test_selecting_the_live_semester_explicitly_shows_no_banner(self):
        """An explicit selection of the Live Semester is still the Live Semester: no banner."""
        live = SemesterFactory()
        admin_client(self)

        select(self, live)

        self.assertNotContains(self.client.get(reverse('scheduling:overview')), BANNER_MARKER)

    def test_a_member_never_sees_the_banner(self):
        """A non-admin only ever resolves the Live Semester, so no page shows the banner."""
        SemesterFactory()
        SemesterFactory(draft=True)
        member_client(self)

        self.assertNotContains(self.client.get(reverse('scheduling:overview')), BANNER_MARKER)

    def test_a_deleted_selection_silently_yields_the_live_semester(self):
        """A selection pointing at a since-deleted Semester renders the live view with no banner and no error."""
        SemesterFactory()
        draft = SemesterFactory(draft=True)
        admin_client(self)
        select(self, draft)
        draft.delete()

        response = self.client.get(reverse('scheduling:overview'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, BANNER_MARKER)

    def test_an_account_that_loses_admin_mid_session_sees_the_member_view(self):
        """A stale selection held by a demoted account yields the Live Semester, with no banner and no panel."""
        SemesterFactory()
        draft = SemesterFactory(draft=True)
        person = admin_client(self)
        select(self, draft)
        person.is_admin = False
        person.save()

        response = self.client.get(reverse('scheduling:overview'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, BANNER_MARKER)
        self.assertNotContains(response, PANEL_MARKER)

    def test_a_draft_only_portal_still_banners_the_admin(self):
        """With nothing published at all, the admin's fallback draft is still not what members see."""
        draft = SemesterFactory(draft=True)
        admin_client(self)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertContains(response, BANNER_MARKER)
        self.assertContains(response, draft.name)
