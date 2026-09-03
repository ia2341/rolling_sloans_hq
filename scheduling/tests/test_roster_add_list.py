"""The Roster editor's add list and "Import from <prior semester>" prefill (issue #229)."""

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    MembershipFactory,
    MembershipRoleFactory,
    RoleFactory,
    SemesterFactory,
)
from scheduling.models import Membership, MembershipRole
from scheduling.services import VIEWING_SEMESTER_SESSION_KEY

PASSWORD = 'a-strong-test-password-123'


def _edit_url():
    """Return the same /members/ URL the reader is already on, with the edit-mode query string."""
    return f"{reverse('scheduling:members')}?mode=edit"


def _import_url():
    """Return the standalone Import fragment's URL."""
    return reverse('scheduling:members-roster-import')


def _add_row_payload(prefix_index, person, add=False, role_ids=()):
    """Build one RosterAddFormSet row's POST fields for `person`, at formset index `prefix_index`."""
    fields = {
        f'roster_add-{prefix_index}-person_id': str(person.pk),
        f'roster_add-{prefix_index}-roles': [str(role_id) for role_id in role_ids],
    }
    if add:
        fields[f'roster_add-{prefix_index}-add'] = 'on'
    return fields


def _full_payload(semester, edit_rows=(), add_rows=()):
    """Assemble a full POST body: both formsets' management forms, the hidden stamp, and every row."""
    payload = {
        'roster-TOTAL_FORMS': str(len(edit_rows)),
        'roster-INITIAL_FORMS': str(len(edit_rows)),
        'roster-MIN_NUM_FORMS': '0',
        'roster-MAX_NUM_FORMS': '1000',
        'roster_add-TOTAL_FORMS': str(len(add_rows)),
        'roster_add-INITIAL_FORMS': str(len(add_rows)),
        'roster_add-MIN_NUM_FORMS': '0',
        'roster_add-MAX_NUM_FORMS': '1000',
        'roster_semester_id': str(semester.pk),
        'roster_semester_updated_at': semester.updated_at.isoformat(),
    }
    for row in edit_rows:
        payload.update(row)
    for row in add_rows:
        payload.update(row)
    return payload


@override_settings(SECURE_SSL_REDIRECT=False)
class AddListRenderingTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person against a Semester with nobody rostered yet."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True, name='Admin Placeholder')
        self.client.login(username=self.admin.email, password=PASSWORD)
        self.semester = SemesterFactory()

    def test_edit_mode_lists_every_unrostered_active_person_ordered_by_name(self):
        """The add list shows every active Person with no Membership in the Semester, ordered by name."""
        MembershipFactory(semester=self.semester, person=self.admin)
        zed = PersonFactory(name='Zed Placeholder')
        amy = PersonFactory(name='Amy Placeholder')

        response = self.client.get(_edit_url())
        content = response.content.decode()

        self.assertContains(response, 'id="roster-add-table"')
        self.assertLess(content.index(amy.name), content.index(zed.name))

    def test_deactivated_person_is_absent_with_no_error(self):
        """A deactivated Person never appears in the add list, and the page renders cleanly."""
        PersonFactory(is_active=False, name='Retired Placeholder')

        response = self.client.get(_edit_url())

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Retired Placeholder')

    def test_already_rostered_person_is_absent_from_the_add_list(self):
        """A Person already holding a Membership in the Semester doesn't reappear in the add list."""
        membership = MembershipFactory(semester=self.semester)

        response = self.client.get(_edit_url())

        self.assertNotRegex(
            response.content.decode(),
            rf'name="roster_add-\d+-person_id" value="{membership.person.pk}"',
        )

    def test_empty_add_list_renders_a_usable_empty_state(self):
        """With nobody left to add, the add list renders empty-state copy rather than an empty table."""
        MembershipFactory(semester=self.semester, person=self.admin)

        response = self.client.get(_edit_url())

        self.assertContains(response, 'Everyone active is already on the roster.')
        self.assertNotContains(response, 'id="roster-add-table"')

    def test_no_prior_semester_hides_the_import_button(self):
        """With no earlier Semester to import from, the Import button doesn't render at all."""
        response = self.client.get(_edit_url())

        self.assertNotContains(response, 'id="import-roster-button"')

    def test_import_button_names_the_prior_semester_before_being_pressed(self):
        """The Import button's own label names the Semester it will draw from, before it is pressed."""
        prior = self.semester
        target = SemesterFactory()
        session = self.client.session
        session[VIEWING_SEMESTER_SESSION_KEY] = target.pk
        session.save()

        response = self.client.get(_edit_url())

        self.assertContains(response, 'id="import-roster-button"')
        self.assertContains(response, f'Import from {prior}')


@override_settings(SECURE_SSL_REDIRECT=False)
class ImportPrefillTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person, with a prior Semester's Roster to import from."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=self.admin.email, password=PASSWORD)
        self.prior = SemesterFactory()
        self.target = SemesterFactory()
        self.role = RoleFactory(name='Bassist')
        self.imported_person = PersonFactory(name='Imported Placeholder')
        self.prior_membership = MembershipFactory(semester=self.prior, person=self.imported_person)
        MembershipRoleFactory(membership=self.prior_membership, role=self.role)
        session = self.client.session
        session[VIEWING_SEMESTER_SESSION_KEY] = self.target.pk
        session.save()

    def test_pressing_import_prefills_the_ticks_and_writes_nothing(self):
        """Import renders the imported Person's row pre-ticked with their prior Role, and creates no rows at all."""
        membership_count_before = Membership.objects.count()
        membership_role_count_before = MembershipRole.objects.count()

        response = self.client.get(_import_url())

        self.assertContains(response, 'checked')
        self.assertContains(response, f'value="{self.role.pk}"')
        self.assertEqual(Membership.objects.count(), membership_count_before)
        self.assertEqual(MembershipRole.objects.count(), membership_role_count_before)

    def test_pressing_import_preserves_a_hand_ticked_row_the_import_proposal_does_not_cover(self):
        """A row an admin already hand-ticked for someone outside the import proposal survives pressing Import."""
        hand_picked = PersonFactory(name='Hand Picked Placeholder')
        query = {
            'roster_add-TOTAL_FORMS': '2',
            'roster_add-INITIAL_FORMS': '2',
            'roster_add-MIN_NUM_FORMS': '0',
            'roster_add-MAX_NUM_FORMS': '1000',
            'roster_add-0-person_id': str(self.imported_person.pk),
            'roster_add-1-person_id': str(hand_picked.pk),
            'roster_add-1-add': 'on',
        }

        response = self.client.get(_import_url(), query)

        self.assertContains(response, f'value="{hand_picked.pk}"')
        content = response.content.decode()
        hand_picked_row_start = content.index(f'value="{hand_picked.pk}"')
        self.assertIn('checked', content[hand_picked_row_start:content.index('</tr>', hand_picked_row_start)])

    def test_saving_after_import_creates_new_declarations_leaving_the_prior_semester_untouched(self):
        """Saving an imported row creates a fresh Membership/MembershipRole for the target Semester; the prior Semester's rows survive."""
        payload = _full_payload(
            self.target,
            add_rows=[_add_row_payload(0, self.imported_person, add=True, role_ids=[self.role.pk])],
        )

        response = self.client.post(reverse('scheduling:members'), payload)

        self.assertRedirects(response, reverse('scheduling:members'))
        new_membership = Membership.objects.get(person=self.imported_person, semester=self.target)
        self.assertEqual(
            set(MembershipRole.objects.filter(membership=new_membership).values_list('role_id', flat=True)),
            {self.role.pk},
        )
        # The prior Semester's own declaration rows are untouched (ADR 0001): a distinct row, not the same one.
        self.assertTrue(MembershipRole.objects.filter(membership=self.prior_membership, role=self.role).exists())
        self.assertNotEqual(
            MembershipRole.objects.get(membership=new_membership).pk,
            MembershipRole.objects.get(membership=self.prior_membership).pk,
        )

    def test_admin_can_import_then_untick_some_and_hand_tick_others_in_one_save(self):
        """An admin can import, drop the imported Person, hand-tick someone else instead, and save the combined result."""
        hand_picked = PersonFactory(name='Hand Picked Placeholder')
        payload = _full_payload(
            self.target,
            add_rows=[
                _add_row_payload(0, self.imported_person, add=False, role_ids=[self.role.pk]),
                _add_row_payload(1, hand_picked, add=True),
            ],
        )

        response = self.client.post(reverse('scheduling:members'), payload)

        self.assertRedirects(response, reverse('scheduling:members'))
        self.assertFalse(Membership.objects.filter(person=self.imported_person, semester=self.target).exists())
        self.assertTrue(Membership.objects.filter(person=hand_picked, semester=self.target).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class SaveWithAddListTests(TestCase):
    def setUp(self):
        """Log in a synthetic admin Person against a Semester with one active Role and no rostered members yet."""
        self.admin = PersonFactory(password=PASSWORD, is_admin=True)
        self.client.login(username=self.admin.email, password=PASSWORD)
        self.semester = SemesterFactory()
        self.role = RoleFactory(name='Bassist')

    def test_ticking_a_person_and_saving_creates_their_membership_with_declared_roles(self):
        """A hand-ticked add-list row lands as a fresh Membership plus MembershipRole in the selected Semester."""
        new_person = PersonFactory(name='New Placeholder')
        payload = _full_payload(
            self.semester,
            add_rows=[_add_row_payload(0, new_person, add=True, role_ids=[self.role.pk])],
        )

        response = self.client.post(reverse('scheduling:members'), payload)

        self.assertRedirects(response, reverse('scheduling:members'))
        membership = Membership.objects.get(person=new_person, semester=self.semester)
        self.assertEqual(
            set(MembershipRole.objects.filter(membership=membership).values_list('role_id', flat=True)),
            {self.role.pk},
        )

    def test_an_added_person_with_no_roles_ticked_is_still_rostered(self):
        """A ticked add-list row with no Roles selected still creates a bare Membership (a newly ticked Person with nothing declared)."""
        new_person = PersonFactory(name='Bare Placeholder')
        payload = _full_payload(self.semester, add_rows=[_add_row_payload(0, new_person, add=True)])

        response = self.client.post(reverse('scheduling:members'), payload)

        self.assertRedirects(response, reverse('scheduling:members'))
        self.assertTrue(Membership.objects.filter(person=new_person, semester=self.semester).exists())

    def test_an_unticked_row_creates_no_membership(self):
        """A row present in the add-list POST body but not ticked 'add' creates nothing."""
        untouched_person = PersonFactory(name='Untouched Placeholder')
        payload = _full_payload(
            self.semester,
            add_rows=[_add_row_payload(0, untouched_person, add=False, role_ids=[self.role.pk])],
        )

        response = self.client.post(reverse('scheduling:members'), payload)

        self.assertRedirects(response, reverse('scheduling:members'))
        self.assertFalse(Membership.objects.filter(person=untouched_person, semester=self.semester).exists())
