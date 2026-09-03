"""The admin adjudication index at /manage/conflicts/ and its detail-route stub (issue #191)."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import ConflictFactory, RehearsalFactory, SemesterFactory
from scheduling.models import Conflict
from scheduling.services import (
    VIEWING_SEMESTER_SESSION_KEY,
    conflict_adjudication_index_for,
)

PASSWORD = 'a-strong-test-password-123'


def select(test_case, semester):
    """Record `semester` as the client's session selection, mirroring `services.set_viewing_semester`."""
    session = test_case.client.session
    session[VIEWING_SEMESTER_SESSION_KEY] = semester.pk
    session.save()


class ConflictAdjudicationIndexForTests(TestCase):
    """`conflict_adjudication_index_for()`: the service function backing the index (issue #191)."""

    def setUp(self):
        """Build a Semester with a well-defined 'today' to place rehearsals relative to."""
        self.semester = SemesterFactory()
        self.today = timezone.localdate()

    def test_excludes_the_dress_rehearsal(self):
        """A future Dress Rehearsal never appears, regardless of its Conflict count."""
        RehearsalFactory(semester=self.semester, date=self.today + timedelta(days=7), is_full_setlist=True)

        rows = conflict_adjudication_index_for(self.semester)

        self.assertEqual(rows, [])

    def test_excludes_past_rehearsals(self):
        """A past, non-Dress Rehearsal never appears, even with pending Conflicts on it."""
        past = RehearsalFactory(semester=self.semester, date=self.today - timedelta(days=1), is_full_setlist=False)
        ConflictFactory(rehearsal=past, status=Conflict.PENDING)

        rows = conflict_adjudication_index_for(self.semester)

        self.assertEqual(rows, [])

    def test_a_future_rehearsal_with_zero_conflicts_still_appears(self):
        """A Rehearsal with no Conflicts at all still gets a row, with a pending count of zero."""
        rehearsal = RehearsalFactory(semester=self.semester, date=self.today + timedelta(days=7), is_full_setlist=False)

        rows = conflict_adjudication_index_for(self.semester)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].rehearsal, rehearsal)
        self.assertEqual(rows[0].pending_count, 0)

    def test_pending_count_counts_only_pending_conflicts(self):
        """Approved and rejected Conflicts don't inflate the pending count."""
        rehearsal = RehearsalFactory(semester=self.semester, date=self.today + timedelta(days=7), is_full_setlist=False)
        ConflictFactory(rehearsal=rehearsal, status=Conflict.PENDING)
        ConflictFactory(rehearsal=rehearsal, status=Conflict.PENDING)
        ConflictFactory(rehearsal=rehearsal, status=Conflict.APPROVED)
        ConflictFactory(rehearsal=rehearsal, status=Conflict.REJECTED)

        rows = conflict_adjudication_index_for(self.semester)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].pending_count, 2)

    def test_rows_are_ordered_by_date(self):
        """Rows come back in date order, mirroring future_rehearsals_for()."""
        later = RehearsalFactory(semester=self.semester, date=self.today + timedelta(days=14), is_full_setlist=False)
        earlier = RehearsalFactory(semester=self.semester, date=self.today + timedelta(days=1), is_full_setlist=False)

        rows = conflict_adjudication_index_for(self.semester)

        self.assertEqual([row.rehearsal for row in rows], [earlier, later])

    def test_scoped_to_the_given_semester(self):
        """A Rehearsal in a different Semester never appears in this Semester's rows."""
        other_semester = SemesterFactory()
        RehearsalFactory(semester=other_semester, date=self.today + timedelta(days=7), is_full_setlist=False)

        rows = conflict_adjudication_index_for(self.semester)

        self.assertEqual(rows, [])


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_manage_conflicts_redirects_anonymous_users_to_login(self):
        """An anonymous request to /manage/conflicts/ redirects to the login page."""
        url = reverse('scheduling:manage-conflicts')

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_manage_conflicts_detail_redirects_anonymous_users_to_login(self):
        """An anonymous request to /manage/conflicts/<id>/ redirects to the login page."""
        rehearsal = RehearsalFactory(is_full_setlist=False)
        url = reverse('scheduling:manage-conflicts-detail', args=[rehearsal.pk])

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")


@override_settings(SECURE_SSL_REDIRECT=False)
class NonAdminAccessTests(TestCase):
    def setUp(self):
        """Log in a synthetic non-admin Person before each test."""
        self.person = PersonFactory(password=PASSWORD, is_admin=False)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_manage_conflicts_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's GET to /manage/conflicts/ returns 403 via AdminRequiredMixin."""
        response = self.client.get(reverse('scheduling:manage-conflicts'))

        self.assertEqual(response.status_code, 403)

    def test_manage_conflicts_detail_is_forbidden_for_non_admin(self):
        """A logged-in non-admin's GET to /manage/conflicts/<id>/ returns 403 via AdminRequiredMixin."""
        rehearsal = RehearsalFactory(is_full_setlist=False)

        response = self.client.get(reverse('scheduling:manage-conflicts-detail', args=[rehearsal.pk]))

        self.assertEqual(response.status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class ConflictAdjudicationIndexViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person and build a live Semester."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=self.admin.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.today = timezone.localdate()

    def test_lists_future_non_dress_rehearsals_with_pending_counts(self):
        """The index renders each future, non-Dress Rehearsal with its pending Conflict count."""
        rehearsal = RehearsalFactory(semester=self.semester, date=self.today + timedelta(days=7), is_full_setlist=False)
        ConflictFactory(rehearsal=rehearsal, status=Conflict.PENDING)

        response = self.client.get(reverse('scheduling:manage-conflicts'))

        self.assertEqual(response.status_code, 200)
        rows = response.context['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].rehearsal, rehearsal)
        self.assertEqual(rows[0].pending_count, 1)
        self.assertContains(response, reverse('scheduling:manage-conflicts-detail', args=[rehearsal.pk]))

    def test_dress_rehearsal_never_appears(self):
        """A future Dress Rehearsal is absent from the index."""
        RehearsalFactory(semester=self.semester, date=self.today + timedelta(days=7), is_full_setlist=True)

        response = self.client.get(reverse('scheduling:manage-conflicts'))

        self.assertEqual(response.context['rows'], [])

    def test_past_rehearsal_never_appears(self):
        """A past Rehearsal is absent from the index."""
        RehearsalFactory(semester=self.semester, date=self.today - timedelta(days=1), is_full_setlist=False)

        response = self.client.get(reverse('scheduling:manage-conflicts'))

        self.assertEqual(response.context['rows'], [])

    def test_a_rehearsal_with_zero_conflicts_is_still_listed_and_reachable(self):
        """A conflict-free Rehearsal still gets a row and a working link to its adjudication table."""
        rehearsal = RehearsalFactory(semester=self.semester, date=self.today + timedelta(days=7), is_full_setlist=False)

        response = self.client.get(reverse('scheduling:manage-conflicts'))

        self.assertEqual(len(response.context['rows']), 1)
        detail_response = self.client.get(reverse('scheduling:manage-conflicts-detail', args=[rehearsal.pk]))
        self.assertEqual(detail_response.status_code, 200)

    def test_scoped_to_the_viewing_semester_and_renders_the_non_live_banner(self):
        """Selecting a draft Semester scopes the index to it and renders the non-live banner."""
        draft = SemesterFactory(draft=True)
        select(self, draft)
        rehearsal = RehearsalFactory(semester=draft, date=self.today + timedelta(days=7), is_full_setlist=False)
        RehearsalFactory(semester=self.semester, date=self.today + timedelta(days=7), is_full_setlist=False)

        response = self.client.get(reverse('scheduling:manage-conflicts'))

        self.assertEqual([row.rehearsal for row in response.context['rows']], [rehearsal])
        self.assertContains(response, 'data-testid="semester-banner"')


@override_settings(SECURE_SSL_REDIRECT=False)
class ConflictAdjudicationDetailViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person and build a live Semester."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=self.admin.email, password=PASSWORD)
        self.semester = SemesterFactory()

    def test_renders_for_a_rehearsal_in_the_viewing_semester(self):
        """A GET for a Rehearsal in the viewing Semester renders successfully."""
        rehearsal = RehearsalFactory(semester=self.semester, is_full_setlist=False)

        response = self.client.get(reverse('scheduling:manage-conflicts-detail', args=[rehearsal.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['rehearsal'], rehearsal)

    def test_404s_for_a_rehearsal_outside_the_viewing_semester(self):
        """A Rehearsal belonging to a different Semester 404s rather than leaking across scope."""
        other_semester = SemesterFactory(draft=True)
        rehearsal = RehearsalFactory(semester=other_semester, is_full_setlist=False)

        response = self.client.get(reverse('scheduling:manage-conflicts-detail', args=[rehearsal.pk]))

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class ScheduleAdminLinkTests(TestCase):
    """The unconditional, countless admin-only link out to a Rehearsal's adjudication table (ADR 0005)."""

    def setUp(self):
        """Build a live Semester with one future, conflict-free Rehearsal."""
        self.semester = SemesterFactory()
        self.rehearsal = RehearsalFactory(
            semester=self.semester, date=timezone.localdate() + timedelta(days=7), is_full_setlist=False,
        )

    def test_admin_sees_the_link_on_the_single_rehearsal_view_with_no_conflicts(self):
        """An admin sees the link on a Rehearsal with zero Conflicts — it isn't conditioned on any existing."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)

        response = self.client.get(reverse('scheduling:schedule'), {'rehearsal': self.rehearsal.pk})

        self.assertContains(response, reverse('scheduling:manage-conflicts-detail', args=[self.rehearsal.pk]))
        self.assertContains(response, 'Manage conflicts for this rehearsal')

    def test_admin_sees_the_link_on_the_all_rehearsals_list(self):
        """An admin sees the link on the All-Rehearsals list row too."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)

        response = self.client.get(reverse('scheduling:schedule'), {'view': 'all'})

        self.assertContains(response, reverse('scheduling:manage-conflicts-detail', args=[self.rehearsal.pk]))

    def test_member_sees_no_trace_of_the_link(self):
        """A non-admin member sees no adjudication link anywhere on the schedule page."""
        member = PersonFactory(password=PASSWORD, is_admin=False)
        self.client.login(username=member.email, password=PASSWORD)

        response = self.client.get(reverse('scheduling:schedule'), {'rehearsal': self.rehearsal.pk})

        self.assertNotContains(response, reverse('scheduling:manage-conflicts-detail', args=[self.rehearsal.pk]))
        self.assertNotContains(response, 'Manage conflicts')


@override_settings(SECURE_SSL_REDIRECT=False)
class OverviewAdminLinkTests(TestCase):
    """Admin Home (Overview) links to the adjudication index (issue #191)."""

    def test_admin_sees_the_manage_conflicts_link(self):
        """An admin's Overview page links to /manage/conflicts/."""
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=admin.email, password=PASSWORD)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertContains(response, reverse('scheduling:manage-conflicts'))

    def test_member_sees_no_manage_conflicts_link(self):
        """A non-admin member's Overview page carries no link to /manage/conflicts/."""
        member = PersonFactory(password=PASSWORD, is_admin=False)
        self.client.login(username=member.email, password=PASSWORD)

        response = self.client.get(reverse('scheduling:overview'))

        self.assertNotContains(response, reverse('scheduling:manage-conflicts'))
