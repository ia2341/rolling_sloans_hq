"""The Song page's admin-only "Edit requirements" mode: the toggle, the buffer, and the atomic save (issue #209)."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import SongRoleRequirement
from scheduling.services import (
    VIEWING_SEMESTER_SESSION_KEY,
    apply_song_role_requirements,
)

PASSWORD = 'a-strong-test-password-123'


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


def post_data(song, requirements, edits=None, add_rows=(), semester_id=None, stamp=None):
    """Build POST data for `SongRequirementsEditView`'s two formsets plus its hidden staleness fields.

    `edits` maps a Requirement pk to overrides (`count`/`remove`) on its
    existing row; `add_rows` is a list of `{'role': pk, 'count': n}` dicts
    for "+ Add requirement" rows. `stamp`/`semester_id` default to the
    Song's own Semester unless overridden, to exercise the two staleness
    checks.
    """
    edits = edits or {}
    data = {
        'req-TOTAL_FORMS': str(len(requirements)),
        'req-INITIAL_FORMS': str(len(requirements)),
        'req-MIN_NUM_FORMS': '0',
        'req-MAX_NUM_FORMS': '1000',
        'add-TOTAL_FORMS': str(len(add_rows)),
        'add-INITIAL_FORMS': '0',
        'add-MIN_NUM_FORMS': '0',
        'add-MAX_NUM_FORMS': '1000',
    }
    for index, requirement in enumerate(requirements):
        row_edits = edits.get(requirement.pk, {})
        data[f'req-{index}-role_id'] = str(requirement.role_id)
        data[f'req-{index}-count'] = str(row_edits.get('count', requirement.count))
        if row_edits.get('remove'):
            data[f'req-{index}-remove'] = 'on'
    for index, row in enumerate(add_rows):
        data[f'add-{index}-role'] = str(row['role'])
        data[f'add-{index}-count'] = str(row['count'])
    data['requirements_semester_id'] = str(semester_id if semester_id is not None else song.semester_id)
    data['requirements_semester_updated_at'] = (
        stamp if stamp is not None else song.semester.updated_at.isoformat()
    )
    return data


@override_settings(SECURE_SSL_REDIRECT=False)
class SongRequirementsEditButtonTests(TestCase):
    def test_edit_button_renders_for_an_admin(self):
        """The Song detail page renders the 'Edit requirements' button for a logged-in admin."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        admin_client(self)

        response = self.client.get(reverse('scheduling:song-detail', args=[song.pk]))

        self.assertContains(response, 'id="edit-requirements-button"')

    def test_edit_button_is_absent_for_a_member(self):
        """A member sees no edit affordance anywhere on the Song page."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        member_client(self)

        response = self.client.get(reverse('scheduling:song-detail', args=[song.pk]))

        self.assertNotContains(response, 'id="edit-requirements-button"')
        self.assertNotContains(response, 'song-requirements-edit-form')


@override_settings(SECURE_SSL_REDIRECT=False)
class SongRequirementsEditAccessTests(TestCase):
    def test_get_redirects_anonymous_users_to_login(self):
        """An anonymous GET to the edit URL redirects to the login page."""
        song = SongFactory()
        url = reverse('scheduling:song-requirements-edit', args=[song.pk])

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")

    def test_post_redirects_anonymous_users_to_login_and_changes_nothing(self):
        """An anonymous POST to the edit URL redirects to login and writes nothing."""
        song = SongFactory()
        requirement = SongRoleRequirementFactory(song=song, count=1)
        url = reverse('scheduling:song-requirements-edit', args=[song.pk])

        response = self.client.post(url, post_data(song, [requirement], edits={requirement.pk: {'count': 5}}))

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")
        requirement.refresh_from_db()
        self.assertEqual(requirement.count, 1)

    def test_get_is_forbidden_for_a_non_admin(self):
        """A logged-in non-admin's GET to the edit URL returns 403."""
        song = SongFactory()
        member_client(self)

        response = self.client.get(reverse('scheduling:song-requirements-edit', args=[song.pk]))

        self.assertEqual(response.status_code, 403)

    def test_post_is_forbidden_for_a_non_admin_and_changes_nothing(self):
        """A logged-in non-admin's POST to the edit URL returns 403 and writes nothing."""
        song = SongFactory()
        requirement = SongRoleRequirementFactory(song=song, count=1)
        member_client(self)

        response = self.client.post(
            reverse('scheduling:song-requirements-edit', args=[song.pk]),
            post_data(song, [requirement], edits={requirement.pk: {'count': 5}}),
        )

        self.assertEqual(response.status_code, 403)
        requirement.refresh_from_db()
        self.assertEqual(requirement.count, 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class SongRequirementsEditGetTests(TestCase):
    def test_full_page_get_renders_the_table(self):
        """A direct (non-htmx) GET renders the full page with the edit table."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        SongRoleRequirementFactory(song=song, count=2)
        admin_client(self)

        response = self.client.get(reverse('scheduling:song-requirements-edit', args=[song.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="song-requirements-edit-form"')

    def test_htmx_get_returns_a_bare_fragment(self):
        """An `HX-Request` GET returns just the table fragment, not the full page shell."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        admin_client(self)

        response = self.client.get(
            reverse('scheduling:song-requirements-edit', args=[song.pk]), HTTP_HX_REQUEST='true',
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<html')
        self.assertContains(response, 'id="song-requirements-edit-form"')

    def test_a_requirement_on_a_retired_role_is_shown_with_a_quiet_flag(self):
        """A Requirement naming a retired Role still renders, flagged, in the edit table."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        retired_role = RoleFactory(is_active=False)
        SongRoleRequirementFactory(song=song, role=retired_role, count=1)
        admin_client(self)

        response = self.client.get(reverse('scheduling:song-requirements-edit', args=[song.pk]))

        self.assertContains(response, 'retired role')

    def test_a_song_outside_the_viewing_semester_404s(self):
        """A Song belonging to a different Semester than the one selected returns 404."""
        other_semester = SemesterFactory()
        song = SongFactory(semester=other_semester)
        selected = SemesterFactory()
        admin_client(self)
        select(self, selected)

        response = self.client.get(reverse('scheduling:song-requirements-edit', args=[song.pk]))

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class SongRequirementsEditSaveTests(TestCase):
    def test_changing_an_existing_count_saves_and_redirects_to_the_song(self):
        """Raising an existing Requirement's count from 2 to 3 saves and redirects to the Song page."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        requirement = SongRoleRequirementFactory(song=song, count=2)
        admin_client(self)

        response = self.client.post(
            reverse('scheduling:song-requirements-edit', args=[song.pk]),
            post_data(song, [requirement], edits={requirement.pk: {'count': 3}}),
        )

        self.assertRedirects(response, reverse('scheduling:song-detail', args=[song.pk]))
        requirement.refresh_from_db()
        self.assertEqual(requirement.count, 3)

    def test_deleting_a_requirement_leaves_assignments_role_and_other_songs_requirements_untouched(self):
        """Deleting a Requirement row leaves the Song's Assignments, the Role, and other Songs' Requirements untouched."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        other_song = SongFactory(semester=semester)
        role = RoleFactory()
        requirement = SongRoleRequirementFactory(song=song, role=role, count=2)
        other_requirement = SongRoleRequirementFactory(song=other_song, role=role, count=1)
        admin_client(self)

        response = self.client.post(
            reverse('scheduling:song-requirements-edit', args=[song.pk]),
            post_data(song, [requirement], edits={requirement.pk: {'remove': True}}),
        )

        self.assertRedirects(response, reverse('scheduling:song-detail', args=[song.pk]))
        self.assertFalse(SongRoleRequirement.objects.filter(pk=requirement.pk).exists())
        self.assertTrue(SongRoleRequirement.objects.filter(pk=other_requirement.pk).exists())
        role.refresh_from_db()
        self.assertTrue(role.is_active)

    def test_add_requirement_row_creates_a_new_requirement(self):
        """A "+ Add requirement" row submits as a new SongRoleRequirement on Save."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        role = RoleFactory()
        admin_client(self)

        response = self.client.post(
            reverse('scheduling:song-requirements-edit', args=[song.pk]),
            post_data(song, [], add_rows=[{'role': role.pk, 'count': 2}]),
        )

        self.assertRedirects(response, reverse('scheduling:song-detail', args=[song.pk]))
        requirement = SongRoleRequirement.objects.get(song=song, role=role)
        self.assertEqual(requirement.count, 2)

    def test_a_duplicate_role_across_add_rows_is_a_validation_error_that_writes_nothing(self):
        """Two "+ Add requirement" rows naming the same Role block the save as a Validation Error, writing nothing."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        role = RoleFactory()
        admin_client(self)

        response = self.client.post(
            reverse('scheduling:song-requirements-edit', args=[song.pk]),
            post_data(song, [], add_rows=[{'role': role.pk, 'count': 1}, {'role': role.pk, 'count': 2}]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SongRoleRequirement.objects.filter(song=song, role=role).exists())
        self.assertContains(response, 'one Requirement per Song')

    def test_a_count_of_zero_is_rejected_by_the_form(self):
        """A submitted count of zero is rejected as a field error, writing nothing."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        requirement = SongRoleRequirementFactory(song=song, count=2)
        admin_client(self)

        response = self.client.post(
            reverse('scheduling:song-requirements-edit', args=[song.pk]),
            post_data(song, [requirement], edits={requirement.pk: {'count': 0}}),
        )

        self.assertEqual(response.status_code, 200)
        requirement.refresh_from_db()
        self.assertEqual(requirement.count, 2)

    def test_a_batch_with_one_invalid_row_writes_nothing_and_preserves_every_value(self):
        """One invalid row's count blocks the whole batch; every submitted value re-renders unchanged."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        first = SongRoleRequirementFactory(song=song, count=1)
        second = SongRoleRequirementFactory(song=song, count=1)
        admin_client(self)

        response = self.client.post(
            reverse('scheduling:song-requirements-edit', args=[song.pk]),
            post_data(song, [first, second], edits={first.pk: {'count': 0}, second.pk: {'count': 5}}),
        )

        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.count, 1)
        self.assertEqual(second.count, 1)
        self.assertContains(response, 'value="5"')

    def test_cancel_link_returns_to_read_mode(self):
        """The edit table renders a plain Cancel link back to the Song's read-mode page."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        admin_client(self)

        response = self.client.get(reverse('scheduling:song-requirements-edit', args=[song.pk]))

        self.assertContains(response, reverse('scheduling:song-detail', args=[song.pk]))

    def test_a_stale_stamp_is_rejected_wholesale_and_writes_nothing(self):
        """A save carrying an older Semester stamp than the current one is rejected, writing nothing."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        requirement = SongRoleRequirementFactory(song=song, count=1)
        stale_stamp = semester.updated_at.isoformat()
        semester.updated_at = timezone.now() + timedelta(seconds=1)
        semester.save(update_fields=['updated_at'])
        admin_client(self)

        response = self.client.post(
            reverse('scheduling:song-requirements-edit', args=[song.pk]),
            post_data(song, [requirement], edits={requirement.pk: {'count': 9}}, stamp=stale_stamp),
        )

        self.assertEqual(response.status_code, 200)
        requirement.refresh_from_db()
        self.assertEqual(requirement.count, 1)
        self.assertContains(response, 'reload and reapply')

    def test_a_successful_save_advances_the_stamp_so_a_subsequent_stale_save_is_rejected(self):
        """After one Save Changes succeeds, a second save still carrying the original stamp is rejected."""
        semester = SemesterFactory()
        song = SongFactory(semester=semester)
        requirement = SongRoleRequirementFactory(song=song, count=1)
        original_stamp = semester.updated_at.isoformat()
        admin_client(self)

        first_response = self.client.post(
            reverse('scheduling:song-requirements-edit', args=[song.pk]),
            post_data(song, [requirement], edits={requirement.pk: {'count': 2}}, stamp=original_stamp),
        )
        self.assertRedirects(first_response, reverse('scheduling:song-detail', args=[song.pk]))

        second_response = self.client.post(
            reverse('scheduling:song-requirements-edit', args=[song.pk]),
            post_data(song, [requirement], edits={requirement.pk: {'count': 3}}, stamp=original_stamp),
        )

        self.assertEqual(second_response.status_code, 200)
        self.assertContains(second_response, 'reload and reapply')
        requirement.refresh_from_db()
        self.assertEqual(requirement.count, 2)

    def test_a_mismatched_hidden_semester_id_hard_fails_and_writes_nothing(self):
        """A hidden Semester id that doesn't match the Semester now selected hard-fails, writing nothing."""
        semester = SemesterFactory()
        other_semester = SemesterFactory()
        song = SongFactory(semester=semester)
        requirement = SongRoleRequirementFactory(song=song, count=1)
        admin_client(self)
        select(self, semester)

        response = self.client.post(
            reverse('scheduling:song-requirements-edit', args=[song.pk]),
            post_data(song, [requirement], edits={requirement.pk: {'count': 9}}, semester_id=other_semester.pk),
        )

        self.assertEqual(response.status_code, 200)
        requirement.refresh_from_db()
        self.assertEqual(requirement.count, 1)

    def test_saving_into_a_draft_semester_leaves_the_live_semester_untouched(self):
        """An admin viewing a draft Semester saves into that draft; the live Semester's Songs are unchanged."""
        live = SemesterFactory()
        live_song = SongFactory(semester=live)
        live_requirement = SongRoleRequirementFactory(song=live_song, count=1)
        draft = SemesterFactory(draft=True)
        draft_song = SongFactory(semester=draft)
        draft_requirement = SongRoleRequirementFactory(song=draft_song, count=1)
        admin_client(self)
        select(self, draft)

        response = self.client.post(
            reverse('scheduling:song-requirements-edit', args=[draft_song.pk]),
            post_data(draft_song, [draft_requirement], edits={draft_requirement.pk: {'count': 4}}),
        )

        self.assertRedirects(response, reverse('scheduling:song-detail', args=[draft_song.pk]))
        draft_requirement.refresh_from_db()
        live_requirement.refresh_from_db()
        self.assertEqual(draft_requirement.count, 4)
        self.assertEqual(live_requirement.count, 1)


class NoPreviewEndpointTests(TestCase):
    """This surface ships no `preview_` sibling, deliberately (see `apply_song_role_requirements()`'s docstring).

    Deleting a Requirement destroys nothing and cascades nowhere, and
    unfilled count is target minus actual — both already rendered on the
    Song page in read mode — so ADR 0008's "is there fallout only the
    server can compute?" test comes back negative for this surface. A
    later "fix for consistency" adding a preview endpoint or a
    `preview_song_role_requirements()` service function should fail this
    test, not pass review.
    """

    def test_no_preview_route_exists_for_song_requirements(self):
        """No URL name resembling a Song-requirements Preview endpoint resolves."""
        for name in ('song-requirements-preview', 'song-requirements-edit-preview'):
            with self.assertRaises(NoReverseMatch):
                reverse(f'scheduling:{name}')

    def test_apply_song_role_requirements_has_no_preview_sibling(self):
        """No `preview_song_role_requirements` function exists in the services layer."""
        import scheduling.services as services_module

        self.assertFalse(hasattr(services_module, 'preview_song_role_requirements'))
        self.assertTrue(callable(apply_song_role_requirements))
