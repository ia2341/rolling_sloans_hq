"""The merged member page: /schedule/ absorbs the Conflicts page (issue #190).

Availability folds inline into the rehearsal it concerns, so these cover
the `?view=next` detail's "Your availability" block, the `?view=all`
rows, the declare/edit/delete endpoints now living under `/schedule/`,
the owner-only adjudication read, the landing-anchor fallback, and the
outright removal of `/me/conflicts/`.
"""

from datetime import time, timedelta

from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    ConflictFactory,
    ConflictWindowFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Conflict, ConflictWindow
from scheduling.services import conflict_history_for

PASSWORD = 'a-strong-test-password-123'

SCHEDULE_URL_NAME = 'scheduling:schedule'


def declare_url(rehearsal):
    """Reverse the declare/edit endpoint for `rehearsal`."""
    return reverse('scheduling:conflict-declare', args=[rehearsal.pk])


def delete_url(rehearsal):
    """Reverse the delete endpoint for `rehearsal`."""
    return reverse('scheduling:conflict-delete', args=[rehearsal.pk])


def declaration_data(rehearsal, **fields):
    """Build POST data for `rehearsal`'s availability form, prefixed the way the view expects."""
    prefix = f'conflict-{rehearsal.pk}'
    return {f'{prefix}-{name}': value for name, value in fields.items()}


def future_rehearsal(semester, days=1, **kwargs):
    """Build a Rehearsal `days` days from today in `semester`, starting at a fixed 18:00."""
    return RehearsalFactory(
        semester=semester, date=timezone.localdate() + timedelta(days=days), start_time=time(18, 0), **kwargs
    )


def past_rehearsal(semester, days=1, **kwargs):
    """Build a Rehearsal `days` days before today in `semester`, starting at a fixed 18:00."""
    return RehearsalFactory(
        semester=semester, date=timezone.localdate() - timedelta(days=days), start_time=time(18, 0), **kwargs
    )


def assign_to(person, rehearsal, position=1, order=1):
    """Assign `person` to a Song scheduled at `rehearsal`, so they are needed there."""
    song = SongFactory(semester=rehearsal.semester, position=position)
    RehearsalSongFactory(rehearsal=rehearsal, song=song, order=order)
    SongRoleAssignmentFactory(song=song, person=person)
    return song


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_declare_redirects_anonymous_users_to_login(self):
        """An anonymous POST to /schedule/<id>/conflict/ redirects to the login page."""
        url = declare_url(RehearsalFactory())

        response = self.client.post(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_delete_redirects_anonymous_users_to_login(self):
        """An anonymous POST to /schedule/<id>/conflict/delete/ redirects to the login page."""
        url = delete_url(RehearsalFactory())

        response = self.client.post(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")


@override_settings(SECURE_SSL_REDIRECT=False)
class OldConflictsPageRemovalTests(TestCase):
    """The old page goes outright, with no redirect — the treatment #172 gave /manage/setlist/*."""

    def setUp(self):
        """Log in a synthetic Person before each test."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_the_conflicts_page_is_gone(self):
        """/me/conflicts/ 404s rather than redirecting anywhere."""
        response = self.client.get('/me/conflicts/')

        self.assertEqual(response.status_code, 404)

    def test_the_conflict_edit_route_is_gone(self):
        """/me/conflicts/<id>/edit/ 404s rather than redirecting anywhere."""
        rehearsal = RehearsalFactory()

        response = self.client.post(f'/me/conflicts/{rehearsal.pk}/edit/')

        self.assertEqual(response.status_code, 404)

    def test_the_conflict_delete_route_is_gone(self):
        """/me/conflicts/<id>/delete/ 404s rather than redirecting anywhere."""
        rehearsal = RehearsalFactory()

        response = self.client.post(f'/me/conflicts/{rehearsal.pk}/delete/')

        self.assertEqual(response.status_code, 404)

    def test_no_conflicts_route_is_registered_under_any_name(self):
        """The `conflicts` and `conflict-edit` route names no longer resolve."""
        for name in ('scheduling:conflicts', 'scheduling:conflict-edit'):
            with self.subTest(name=name), self.assertRaises(NoReverseMatch):
                reverse(name)

    def test_the_conflicts_template_and_script_are_deleted(self):
        """conflicts.html and conflicts.js are gone from the app, not merely unreferenced."""
        from django.template import TemplateDoesNotExist
        from django.template.loader import get_template

        with self.assertRaises(TemplateDoesNotExist):
            get_template('scheduling/conflicts.html')

        from django.contrib.staticfiles import finders

        self.assertIsNone(finders.find('scheduling/js/conflicts.js'))

    def test_the_nav_drops_conflicts_and_keeps_my_schedule(self):
        """The nav's Conflicts item is removed; My Schedule survives."""
        SemesterFactory()

        response = self.client.get(reverse(SCHEDULE_URL_NAME))

        self.assertContains(response, 'My Schedule')
        self.assertNotContains(response, '>Conflicts<')


@override_settings(SECURE_SSL_REDIRECT=False)
class RehearsalDetailAvailabilityTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person against a published Semester holding one future Rehearsal."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.rehearsal = future_rehearsal(self.semester)

    def _detail(self, rehearsal=None):
        """GET the `?view=next` detail for `rehearsal` (defaulting to this test's own)."""
        return self.client.get(reverse(SCHEDULE_URL_NAME), {'rehearsal': (rehearsal or self.rehearsal).pk})

    def test_the_detail_carries_a_your_availability_block_for_that_rehearsal(self):
        """The block sits with the attendance suggestion and breaks already anchored on the Rehearsal."""
        response = self._detail()

        self.assertContains(response, 'Your availability')
        self.assertEqual(response.context['my_availability']['rehearsal'], self.rehearsal)

    def test_the_block_offers_a_declare_affordance_when_nothing_is_declared(self):
        """An undeclared future Rehearsal renders the declare form and says no conflict is declared."""
        response = self._detail()

        self.assertContains(response, 'No conflict declared.')
        self.assertContains(response, f'action="{declare_url(self.rehearsal)}"')

    def test_the_block_shows_an_existing_declaration_and_offers_edit_and_delete(self):
        """A declared future Rehearsal shows the declaration, its reason, and both write affordances."""
        ConflictFactory(
            person=self.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT, reason='Away that evening.',
        )

        response = self._detail()

        self.assertContains(response, 'Full absence')
        self.assertContains(response, 'Away that evening.')
        self.assertContains(response, f'action="{declare_url(self.rehearsal)}"')
        self.assertContains(response, f'action="{delete_url(self.rehearsal)}"')

    def test_a_partial_declaration_renders_its_declared_time(self):
        """A late arrival renders the derived type label and the time itself, not a raw window."""
        conflict = ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.PARTIAL)
        ConflictWindowFactory(
            conflict=conflict, unavailable_start=self.rehearsal.start_time, unavailable_end=time(18, 30),
        )

        response = self._detail()

        self.assertContains(response, 'Late arrival')
        self.assertContains(response, '6:30 p.m.')

    def test_a_past_rehearsal_detail_offers_no_declare_or_delete_control(self):
        """A past Rehearsal keeps its declaration visible but carries neither write affordance."""
        rehearsal = past_rehearsal(self.semester)
        ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)

        response = self._detail(rehearsal)

        self.assertContains(response, 'Full absence')
        self.assertNotContains(response, f'action="{declare_url(rehearsal)}"')
        self.assertNotContains(response, f'action="{delete_url(rehearsal)}"')

    def test_the_dress_rehearsal_renders_the_mandatory_line_and_no_declare_control(self):
        """Attendance is mandatory there (ADR 0006), so the member reads the rule instead of hitting an error."""
        dress = future_rehearsal(self.semester, days=2, is_full_setlist=True)

        response = self._detail(dress)

        self.assertContains(response, 'Attendance at the Dress Rehearsal is mandatory.')
        self.assertNotContains(response, f'action="{declare_url(dress)}"')

    def test_the_page_renders_no_history_section(self):
        """History disappears as a section, not as a record."""
        ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)

        response = self._detail()

        self.assertNotContains(response, 'History')


@override_settings(SECURE_SSL_REDIRECT=False)
class ViewAllAvailabilityTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person against a published Semester holding one past and one future Rehearsal."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.past = past_rehearsal(self.semester)
        self.future = future_rehearsal(self.semester)

    def _all(self):
        """GET the `?view=all` list."""
        return self.client.get(reverse(SCHEDULE_URL_NAME), {'view': 'all'})

    def test_each_row_shows_the_members_own_conflict_state_without_opening_it(self):
        """The state is on the row itself, so a member reads it without drilling into the rehearsal."""
        ConflictFactory(
            person=self.person, rehearsal=self.future, type=Conflict.FULL_CONFLICT, reason='A prior commitment.',
        )

        response = self._all()

        self.assertContains(response, 'Full absence')
        self.assertContains(response, 'A prior commitment.')

    def test_a_future_row_offers_edit_and_delete_of_an_existing_declaration(self):
        """A plan that fell through must not leave a false absence standing."""
        ConflictFactory(person=self.person, rehearsal=self.future, type=Conflict.FULL_CONFLICT)

        response = self._all()

        self.assertContains(response, f'action="{declare_url(self.future)}"')
        self.assertContains(response, f'action="{delete_url(self.future)}"')

    def test_a_past_row_offers_neither_edit_nor_delete(self):
        """A past declaration is a record, not something to withdraw."""
        ConflictFactory(person=self.person, rehearsal=self.past, type=Conflict.FULL_CONFLICT)

        response = self._all()

        self.assertNotContains(response, f'action="{declare_url(self.past)}"')
        self.assertNotContains(response, f'action="{delete_url(self.past)}"')

    def test_a_past_declaration_stays_visible_in_the_collapsed_past_section(self):
        """The record survives on its own row inside the past-rehearsals <details>."""
        ConflictFactory(
            person=self.person, rehearsal=self.past, type=Conflict.FULL_CONFLICT, reason='Was unwell.',
        )

        response = self._all()

        self.assertContains(response, 'Was unwell.')
        past_rows = response.context['schedule']['past']
        self.assertEqual([row['rehearsal'] for row in past_rows], [self.past])
        self.assertIsNotNone(past_rows[0]['availability']['conflict'])

    def test_no_rehearsal_is_rendered_more_than_once(self):
        """Each Rehearsal appears in exactly one section — there is no second list of the same rows."""
        response = self._all()

        rendered = [
            row['rehearsal'].pk
            for section in ('past', 'future')
            for row in response.context['schedule'][section]
        ]

        self.assertEqual(sorted(rendered), sorted({self.past.pk, self.future.pk}))
        self.assertContains(response, f'data-rehearsal-id="{self.future.pk}"', count=1)
        self.assertContains(response, f'data-rehearsal-id="{self.past.pk}"', count=1)

    def test_the_dress_rehearsal_row_renders_the_mandatory_line_and_no_declare_control(self):
        """The row learns the rule too, per ADR 0006."""
        dress = future_rehearsal(self.semester, days=2, is_full_setlist=True)

        response = self._all()

        self.assertContains(response, 'Attendance at the Dress Rehearsal is mandatory.')
        self.assertNotContains(response, f'action="{declare_url(dress)}"')


@override_settings(SECURE_SSL_REDIRECT=False)
class DeclareViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person against a published Semester holding one future Rehearsal."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.rehearsal = future_rehearsal(self.semester)

    def test_full_absence_creates_a_full_conflict_and_redirects_to_the_rehearsal(self):
        """A first declaration writes a FULL_CONFLICT with no window and lands back on the rehearsal it concerns."""
        data = declaration_data(self.rehearsal, declaration_type='full_absence', reason='Out of town.')

        response = self.client.post(declare_url(self.rehearsal), data, follow=True)

        self.assertRedirects(
            response, f"{reverse(SCHEDULE_URL_NAME)}?rehearsal={self.rehearsal.pk}",
        )
        conflict = Conflict.objects.get(person=self.person, rehearsal=self.rehearsal)
        self.assertEqual(conflict.type, Conflict.FULL_CONFLICT)
        self.assertEqual(conflict.reason, 'Out of town.')
        self.assertFalse(ConflictWindow.objects.filter(conflict=conflict).exists())

    def test_late_arrival_creates_a_partial_conflict_windowed_from_the_start(self):
        """A late arrival windows from the Rehearsal's start to the declared time."""
        data = declaration_data(self.rehearsal, declaration_type='late_arrival', arrival_time='18:30')

        self.client.post(declare_url(self.rehearsal), data)

        conflict = Conflict.objects.get(person=self.person, rehearsal=self.rehearsal)
        self.assertEqual(conflict.type, Conflict.PARTIAL)
        window = ConflictWindow.objects.get(conflict=conflict)
        self.assertEqual(window.unavailable_start, self.rehearsal.start_time)
        self.assertEqual(window.unavailable_end, time(18, 30))

    def test_a_second_submission_edits_in_place_rather_than_adding_a_row(self):
        """The same endpoint declares and edits, so a correction is never a second declaration."""
        ConflictFactory(person=self.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)
        data = declaration_data(self.rehearsal, declaration_type='late_arrival', arrival_time='18:30')

        self.client.post(declare_url(self.rehearsal), data)

        self.assertEqual(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).count(), 1)
        self.assertEqual(
            Conflict.objects.get(person=self.person, rehearsal=self.rehearsal).type, Conflict.PARTIAL,
        )

    def test_a_submission_from_view_all_redirects_back_to_view_all(self):
        """Declaring from the list returns to the list, not to a rehearsal detail."""
        data = declaration_data(self.rehearsal, declaration_type='full_absence')
        data['view'] = 'all'

        response = self.client.post(declare_url(self.rehearsal), data)

        self.assertRedirects(response, f'{reverse(SCHEDULE_URL_NAME)}?view=all')

    def test_a_crafted_view_value_cannot_redirect_off_the_page(self):
        """The hidden `view` field resolves through the page's own two views only."""
        data = declaration_data(self.rehearsal, declaration_type='full_absence')
        data['view'] = 'https://example.invalid/'

        response = self.client.post(declare_url(self.rehearsal), data)

        self.assertRedirects(
            response, f"{reverse(SCHEDULE_URL_NAME)}?rehearsal={self.rehearsal.pk}",
        )

    def test_an_invalid_submission_rerenders_the_page_with_the_error_in_place(self):
        """A time outside the Rehearsal's span re-renders /schedule/ with a field error, not a 500."""
        data = declaration_data(self.rehearsal, declaration_type='late_arrival', arrival_time='05:00')

        response = self.client.post(declare_url(self.rehearsal), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Must fall within the Rehearsal")
        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).exists())

    def test_an_invalid_submission_from_view_all_rerenders_the_list(self):
        """The failed submission comes back on the view it was made from."""
        data = declaration_data(self.rehearsal, declaration_type='late_arrival', arrival_time='05:00')
        data['view'] = 'all'

        response = self.client.post(declare_url(self.rehearsal), data)

        self.assertEqual(response.context['view_mode'], 'all')
        self.assertContains(response, "Must fall within the Rehearsal")

    def test_a_declaration_against_a_past_rehearsal_is_rejected(self):
        """Future-only enforcement is server-side, not a hidden control."""
        rehearsal = past_rehearsal(self.semester)

        response = self.client.post(
            declare_url(rehearsal), declaration_data(rehearsal, declaration_type='full_absence'),
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=rehearsal).exists())

    def test_a_declaration_against_the_dress_rehearsal_is_rejected(self):
        """A crafted POST naming the Dress Rehearsal 404s rather than reaching declare_conflict's ValueError."""
        dress = future_rehearsal(self.semester, days=2, is_full_setlist=True)

        response = self.client.post(
            declare_url(dress), declaration_data(dress, declaration_type='full_absence'),
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Conflict.objects.filter(person=self.person, rehearsal=dress).exists())

    def test_a_declaration_outside_the_viewing_semester_is_rejected(self):
        """The write is scoped to the Semester the request is viewing, exactly as the read is."""
        other = future_rehearsal(SemesterFactory(draft=True))

        response = self.client.post(
            declare_url(other), declaration_data(other, declaration_type='full_absence'),
        )

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class DeleteViewTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person holding one declared future Conflict."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.rehearsal = future_rehearsal(self.semester)
        self.conflict = ConflictFactory(
            person=self.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT,
        )

    def test_delete_removes_the_declaration_and_redirects(self):
        """Withdrawing a declaration removes the Conflict and lands back on the rehearsal."""
        response = self.client.post(delete_url(self.rehearsal), follow=True)

        self.assertRedirects(
            response, f"{reverse(SCHEDULE_URL_NAME)}?rehearsal={self.rehearsal.pk}",
        )
        self.assertFalse(Conflict.objects.filter(pk=self.conflict.pk).exists())

    def test_delete_cascades_to_the_conflicts_windows(self):
        """A partial declaration's windows go with it."""
        self.conflict.type = Conflict.PARTIAL
        self.conflict.save()
        ConflictWindowFactory(
            conflict=self.conflict, unavailable_start=self.rehearsal.start_time, unavailable_end=time(18, 30),
        )

        self.client.post(delete_url(self.rehearsal))

        self.assertFalse(ConflictWindow.objects.filter(conflict_id=self.conflict.pk).exists())

    def test_delete_against_a_past_rehearsal_is_rejected(self):
        """A crafted delete against a past Rehearsal 404s and leaves the record standing."""
        rehearsal = past_rehearsal(self.semester)
        conflict = ConflictFactory(person=self.person, rehearsal=rehearsal, type=Conflict.FULL_CONFLICT)

        response = self.client.post(delete_url(rehearsal))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Conflict.objects.filter(pk=conflict.pk).exists())

    def test_delete_against_an_undeclared_rehearsal_is_rejected(self):
        """There is nothing to withdraw where nothing was declared."""
        response = self.client.post(delete_url(future_rehearsal(self.semester, days=3)))

        self.assertEqual(response.status_code, 404)

    def test_delete_cannot_touch_another_members_declaration(self):
        """Ownership is re-checked server-side."""
        other = PersonFactory()
        theirs = ConflictFactory(person=other, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT)

        self.client.post(delete_url(self.rehearsal))

        self.assertTrue(Conflict.objects.filter(pk=theirs.pk).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class OwnAdjudicationReadTests(TestCase):
    """The owner reads their own verdict here, and nobody else does (ADR 0005 bounds the surface, not the viewer)."""

    def setUp(self):
        """Log in a synthetic Person holding one declared future Conflict."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.rehearsal = future_rehearsal(self.semester)

    def _declare(self, **kwargs):
        """Build this person's Conflict for the test Rehearsal with the given verdict fields."""
        return ConflictFactory(
            person=self.person, rehearsal=self.rehearsal, type=Conflict.FULL_CONFLICT, **kwargs,
        )

    def _detail(self):
        """GET the `?view=next` detail for the test Rehearsal."""
        return self.client.get(reverse(SCHEDULE_URL_NAME), {'rehearsal': self.rehearsal.pk})

    def test_a_pending_declaration_reads_as_nobody_having_looked(self):
        """`pending` must never read as "they looked and said no"."""
        self._declare(status=Conflict.PENDING)

        response = self._detail()

        self.assertContains(response, 'Awaiting a decision.')
        self.assertNotContains(response, 'Rejected.')
        self.assertContains(response, f'data-status="{Conflict.PENDING}"')

    def test_a_rejected_declaration_is_visibly_distinct_from_a_pending_one(self):
        """The two outcomes render different text and a different machine-readable status."""
        self._declare(status=Conflict.REJECTED)

        response = self._detail()

        self.assertContains(response, 'Rejected.')
        self.assertNotContains(response, 'Awaiting a decision.')
        self.assertContains(response, f'data-status="{Conflict.REJECTED}"')

    def test_an_approval_shows_the_admins_note_beside_the_outcome(self):
        """The note is readable on an approval as readily as on a rejection."""
        self._declare(status=Conflict.APPROVED, adjudication_note='Covered by a backup.')

        response = self._detail()

        self.assertContains(response, 'Approved.')
        self.assertContains(response, 'Covered by a backup.')

    def test_a_rejection_shows_the_admins_note_beside_the_outcome(self):
        """Same note, same place, on the other verdict."""
        self._declare(status=Conflict.REJECTED, adjudication_note='Too close to the concert.')

        response = self._detail()

        self.assertContains(response, 'Rejected.')
        self.assertContains(response, 'Too close to the concert.')

    def test_a_rejected_declaration_is_preserved_and_still_editable(self):
        """Being re-decided must not mean re-declaring."""
        conflict = self._declare(status=Conflict.REJECTED)

        response = self._detail()

        self.assertContains(response, f'action="{declare_url(self.rehearsal)}"')
        self.assertTrue(Conflict.objects.filter(pk=conflict.pk).exists())

    def test_editing_a_rejected_declaration_keeps_one_row_and_resets_the_verdict(self):
        """The edit lands on the same row, and its stale verdict does not survive it (issue #189)."""
        conflict = self._declare(status=Conflict.REJECTED, adjudication_note='Too close to the concert.')

        self.client.post(
            declare_url(self.rehearsal),
            declaration_data(self.rehearsal, declaration_type='late_arrival', arrival_time='18:30'),
        )

        conflict.refresh_from_db()
        self.assertEqual(Conflict.objects.filter(person=self.person, rehearsal=self.rehearsal).count(), 1)
        self.assertEqual(conflict.status, Conflict.PENDING)
        self.assertEqual(conflict.adjudication_note, '')

    def test_another_member_sees_no_part_of_the_owners_declaration(self):
        """Nobody else's availability reaches this page — it is owner-scoped throughout."""
        self._declare(
            status=Conflict.REJECTED, adjudication_note='Too close to the concert.', reason='A wedding.',
        )
        teammate = PersonFactory(password=PASSWORD)
        self.client.force_login(teammate)

        response = self.client.get(reverse(SCHEDULE_URL_NAME), {'rehearsal': self.rehearsal.pk})

        self.assertNotContains(response, 'A wedding.')
        self.assertNotContains(response, 'Too close to the concert.')
        self.assertNotContains(response, 'Rejected.')

    def test_an_admin_viewing_this_page_sees_no_part_of_it_either(self):
        """ADR 0005 draws its boundary around the surface, not the viewer."""
        self._declare(
            status=Conflict.REJECTED, adjudication_note='Too close to the concert.', reason='A wedding.',
        )
        admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.force_login(admin)

        response = self.client.get(reverse(SCHEDULE_URL_NAME), {'rehearsal': self.rehearsal.pk})

        self.assertNotContains(response, 'A wedding.')
        self.assertNotContains(response, 'Too close to the concert.')
        self.assertNotContains(response, 'Rejected.')


@override_settings(SECURE_SSL_REDIRECT=False)
class LandingAnchorTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person against a published Semester with two upcoming Rehearsals."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.first = future_rehearsal(self.semester, days=1)
        self.second = future_rehearsal(self.semester, days=8)

    def test_a_member_with_no_assignments_lands_on_the_bands_literal_next_rehearsal(self):
        """The dead-end "No upcoming rehearsal to show" would have hidden the declare path."""
        response = self.client.get(reverse(SCHEDULE_URL_NAME))

        self.assertEqual(response.context['rehearsal'], self.first)

    def test_a_member_with_no_assignments_can_declare_from_that_anchor(self):
        """The fallback exists precisely so the declare affordance is reachable."""
        response = self.client.get(reverse(SCHEDULE_URL_NAME))

        self.assertContains(response, f'action="{declare_url(self.first)}"')

    def test_a_member_with_assignments_still_lands_on_their_own_next_attended_rehearsal(self):
        """The fallback must not move the anchor for a member who has one."""
        assign_to(self.person, self.second)

        response = self.client.get(reverse(SCHEDULE_URL_NAME))

        self.assertEqual(response.context['rehearsal'], self.second)

    def test_a_semester_with_no_upcoming_rehearsals_still_has_no_anchor(self):
        """The fallback invents nothing where the band has nothing scheduled."""
        past_rehearsal(SemesterFactory())

        response = self.client.get(reverse(SCHEDULE_URL_NAME))

        self.assertIsNone(response.context['rehearsal'])
        self.assertContains(response, 'No upcoming rehearsal to show.')


@override_settings(SECURE_SSL_REDIRECT=False)
class SemesterScopingTests(TestCase):
    def setUp(self):
        """Log in a synthetic Person against a published Semester and an older one."""
        self.person = PersonFactory(password=PASSWORD)
        self.client.login(username=self.person.email, password=PASSWORD)
        self.older = SemesterFactory()
        self.live = SemesterFactory()

    def test_the_page_renders_against_the_semester_the_request_is_viewing(self):
        """Only the viewing Semester's Rehearsals — and only its declarations — reach the page."""
        older_rehearsal = future_rehearsal(self.older)
        live_rehearsal = future_rehearsal(self.live)
        ConflictFactory(
            person=self.person, rehearsal=older_rehearsal, type=Conflict.FULL_CONFLICT, reason='Last term.',
        )

        response = self.client.get(reverse(SCHEDULE_URL_NAME), {'view': 'all'})

        rendered = [
            row['rehearsal'] for section in ('past', 'future') for row in response.context['schedule'][section]
        ]
        self.assertEqual(rendered, [live_rehearsal])
        self.assertNotContains(response, 'Last term.')

    def test_the_page_renders_without_a_semester_when_nothing_is_published(self):
        """A member with nothing published gets the empty state, not an error."""
        person = PersonFactory(password=PASSWORD)
        self.client.force_login(person)
        for semester in (self.older, self.live):
            semester.published_at = None
            semester.save(update_fields=['published_at'])

        response = self.client.get(reverse(SCHEDULE_URL_NAME))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['semester'])
        self.assertIsNone(response.context['my_availability'])


class ConflictHistoryForTests(TestCase):
    """`conflict_history_for()` survives as a per-row lookup, with its docstring saying its surface is gone."""

    def test_the_docstring_says_the_history_surface_is_gone(self):
        """A reader who greps for "history" must learn there is no History section to find."""
        docstring = conflict_history_for.__doc__

        self.assertIn('no History surface', docstring)
        self.assertIn('#190', docstring)

    def test_it_still_returns_past_and_future_declarations_in_date_order(self):
        """The record it feeds spans both, which is what keeps a past declaration on its row."""
        person = PersonFactory()
        semester = SemesterFactory()
        past = past_rehearsal(semester)
        future = future_rehearsal(semester)
        ConflictFactory(person=person, rehearsal=future, type=Conflict.FULL_CONFLICT)
        ConflictFactory(person=person, rehearsal=past, type=Conflict.FULL_CONFLICT)

        rows = conflict_history_for(semester, person)

        self.assertEqual([row.rehearsal for row in rows], [past, future])
        self.assertEqual([row.is_future for row in rows], [False, True])
