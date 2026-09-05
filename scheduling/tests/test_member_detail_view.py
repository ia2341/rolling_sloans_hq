"""Single per-person page: /members/<int:pk>/ (issue #138, slice 2 of map #135).

The verdicts asserted here come from `docs/person-page-visibility.md`
field-by-field, including the negative assertions that a self-only or
never-rendered field is absent from a teammate's response body rather than
merely un-linked. ADR 0005 supplies the Conflict/attendance boundary.
"""

from datetime import time
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    ConflictFactory,
    ConflictWindowFactory,
    MembershipFactory,
    MembershipRoleFactory,
    RecordingFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Conflict, Membership, MembershipRole
from scheduling.views import MemberDetailView

PASSWORD = 'a-strong-test-password-123'


def member_detail_url(person):
    """Return `/members/<pk>/` for `person`."""
    return reverse('scheduling:member-detail', args=[person.pk])


@override_settings(SECURE_SSL_REDIRECT=False)
class AnonymousAccessTests(TestCase):
    def test_member_detail_redirects_anonymous_users_to_login(self):
        """An anonymous request to /members/<pk>/ redirects to the login page."""
        url = member_detail_url(PersonFactory())

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('identity:login')}?next={url}")


@override_settings(SECURE_SSL_REDIRECT=False)
class TeammateViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a viewer and roster a separate teammate on the current Semester."""
        cls.semester = SemesterFactory()
        cls.viewer = PersonFactory(password=PASSWORD, name='Viewer Placeholder')
        cls.teammate = PersonFactory(name='Teammate Placeholder')
        cls.membership = MembershipFactory(person=cls.teammate, semester=cls.semester)

    def setUp(self):
        """Log in as the viewer before each test."""
        self.client.login(username=self.viewer.email, password=PASSWORD)

    def test_renders_the_teammates_name_and_the_current_semester(self):
        """A teammate's page renders their name and the current Semester's name."""
        response = self.client.get(member_detail_url(self.teammate))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['is_self'])
        self.assertContains(response, 'Teammate Placeholder')
        self.assertContains(response, self.semester.name)

    def test_renders_the_teammates_declared_roles(self):
        """A teammate's declared Roles for the current Semester render by name."""
        MembershipRoleFactory(membership=self.membership, role=RoleFactory(name='Bassist'))
        MembershipRoleFactory(membership=self.membership, role=RoleFactory(name='Singer'))

        response = self.client.get(member_detail_url(self.teammate))

        self.assertContains(response, 'Bassist')
        self.assertContains(response, 'Singer')

    def test_renders_a_declared_role_that_has_since_been_retired(self):
        """A declared Role with is_active=False still renders by name; the flag itself is never shown."""
        MembershipRoleFactory(membership=self.membership, role=RoleFactory(name='Retired Role', is_active=False))

        response = self.client.get(member_detail_url(self.teammate))

        self.assertContains(response, 'Retired Role')
        self.assertNotContains(response, 'is_active')

    def test_renders_assigned_songs_with_the_role_filled_linking_to_each_song(self):
        """Each assigned Song in the current Semester renders its title, the Role filled, and a link to the Song page."""
        song = SongFactory(semester=self.semester, title='Song A')
        SongRoleAssignmentFactory(song=song, person=self.teammate, role=RoleFactory(name='Drummer'))

        response = self.client.get(member_detail_url(self.teammate))

        self.assertContains(response, 'Song A')
        self.assertContains(response, 'Drummer')
        self.assertContains(response, reverse('scheduling:song-detail', args=[song.pk]))

    def test_assigned_songs_are_scoped_to_the_current_semester(self):
        """A Song from an older Semester is absent from the assigned-Songs section (per ADR 0001)."""
        old_song = SongFactory(semester=self.semester, title='Song Z')
        SongRoleAssignmentFactory(song=old_song, person=self.teammate)
        current_membership = MembershipFactory(person=self.teammate, semester=SemesterFactory())

        response = self.client.get(member_detail_url(self.teammate))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['membership'], current_membership)
        self.assertNotContains(response, 'Song Z')

    def test_teammates_email_is_never_rendered(self):
        """`email` is self-only: a teammate's page body does not contain their email address."""
        response = self.client.get(member_detail_url(self.teammate))

        self.assertNotContains(response, self.teammate.email)

    def test_no_password_change_route_exists(self):
        """identity:password-change no longer exists: change password moved into the SPA (#327, built by #333)."""
        with self.assertRaises(NoReverseMatch):
            reverse('identity:password-change')

    def test_teammates_page_exposes_no_roles_form(self):
        """A teammate's page carries no MembershipRolesForm and no roles input at all."""
        response = self.client.get(member_detail_url(self.teammate))

        self.assertNotIn('form', response.context)
        self.assertNotContains(response, 'name="roles"')
        self.assertNotContains(response, 'Save')

    def test_post_to_a_teammates_page_404s_and_changes_nothing(self):
        """POSTing another Person's pk is a 404, not a Role edit — the read path has no mutation surface."""
        role = RoleFactory()

        response = self.client.post(member_detail_url(self.teammate), {'roles': [role.pk]})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(MembershipRole.objects.filter(membership=self.membership).exists())

    def test_404_for_a_person_with_no_current_semester_membership(self):
        """A Person who holds no Membership for the current Semester is not reachable by pk."""
        response = self.client.get(member_detail_url(PersonFactory()))

        self.assertEqual(response.status_code, 404)

    def test_404_for_a_person_rostered_only_in_an_older_semester(self):
        """A Membership in a non-current Semester does not make its Person reachable (per ADR 0001)."""
        past_member = PersonFactory()
        MembershipFactory(person=past_member, semester=self.semester)
        SemesterFactory()  # becomes the current Semester

        response = self.client.get(member_detail_url(past_member))

        self.assertEqual(response.status_code, 404)

    def test_404_for_an_unknown_person_id(self):
        """A request for a nonexistent Person id returns 404."""
        response = self.client.get(reverse('scheduling:member-detail', args=[999999]))

        self.assertEqual(response.status_code, 404)

    def test_404_for_a_teammates_pk_when_there_is_no_current_semester(self):
        """With no Semester at all, nobody holds a current-Semester Membership, so a teammate's pk 404s."""
        self.semester.delete()  # cascades the teammate's Membership away with it

        response = self.client.get(member_detail_url(self.teammate))

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class NeverRenderedFieldTests(TestCase):
    """The `never` verdicts, asserted against both a teammate's page and the owner's own."""

    @classmethod
    def setUpTestData(cls):
        """Build a viewer and roster a teammate, both on the current Semester."""
        cls.semester = SemesterFactory()
        cls.viewer = PersonFactory(password=PASSWORD, name='Viewer Placeholder')
        cls.own_membership = MembershipFactory(person=cls.viewer, semester=cls.semester)
        cls.teammate = PersonFactory(name='Teammate Placeholder', is_admin=True)
        cls.teammate_membership = MembershipFactory(person=cls.teammate, semester=cls.semester)

    def setUp(self):
        """Log in as the viewer before each test."""
        self.client.login(username=self.viewer.email, password=PASSWORD)

    def _assign_mismatched_song(self, person):
        """Assign `person` to a fresh current-Semester Song under an undeclared Role, so is_role_mismatch is True."""
        song = SongFactory(semester=self.semester, title='Song M')
        assignment = SongRoleAssignmentFactory(song=song, person=person, role=RoleFactory(name='Undeclared Role'))
        self.assertTrue(assignment.is_role_mismatch)
        return assignment

    def _declare_conflict(self, person):
        """Give `person` a partial Conflict carrying a distinctive free-text reason on a current-Semester Rehearsal."""
        conflict = ConflictFactory(
            person=person,
            rehearsal=RehearsalFactory(semester=self.semester),
            type=Conflict.PARTIAL,
            reason='A distinctive placeholder reason',
        )
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 15), unavailable_end=time(18, 45))
        return conflict

    def test_role_mismatch_is_never_rendered_on_a_teammates_page(self):
        """`is_role_mismatch` is an admin queue marker (ADR 0002), never surfaced to a teammate."""
        self._assign_mismatched_song(self.teammate)

        response = self.client.get(member_detail_url(self.teammate))

        self.assertContains(response, 'Song M')
        self.assertNotContains(response, 'mismatch')

    def test_role_mismatch_is_never_rendered_on_your_own_page(self):
        """`is_role_mismatch` is withheld from the Person themselves too — ADR 0002 assigns the call to an admin."""
        self._assign_mismatched_song(self.viewer)

        response = self.client.get(member_detail_url(self.viewer))

        self.assertContains(response, 'Song M')
        self.assertNotContains(response, 'mismatch')

    def test_conflict_reason_is_never_rendered_on_a_teammates_page(self):
        """No member-facing page renders another Person's Conflict data (ADR 0005)."""
        self._declare_conflict(self.teammate)

        response = self.client.get(member_detail_url(self.teammate))

        self.assertNotContains(response, 'A distinctive placeholder reason')

    def test_conflict_data_is_never_rendered_on_your_own_page(self):
        """The owner reads their Conflicts at /conflicts/; /members/<pk>/ renders none for anyone (ADR 0005)."""
        conflict = self._declare_conflict(self.viewer)

        response = self.client.get(member_detail_url(self.viewer))

        self.assertNotContains(response, 'A distinctive placeholder reason')
        self.assertNotContains(response, str(conflict.rehearsal.date))
        self.assertNotContains(response, '18:15')

    def test_no_derived_attendance_data_for_either_viewer(self):
        """Derived attendance data is absent from the page for teammate and owner alike (ADR 0005)."""
        rehearsal = RehearsalFactory(semester=self.semester)

        for person in (self.teammate, self.viewer):
            with self.subTest(person=person.name):
                response = self.client.get(member_detail_url(person))

                for context_key in ('attendance', 'breaks', 'next_rehearsal', 'attendance_suggestion', 'rehearsals'):
                    self.assertNotIn(context_key, response.context)
                self.assertNotContains(response, str(rehearsal.date))

    def test_admin_status_is_never_rendered_on_either_page(self):
        """Admin status is not member-facing: no badge on a teammate's page, nor on an admin's own."""
        admin_viewer = PersonFactory(password=PASSWORD, name='Boss Placeholder', is_admin=True)
        MembershipFactory(person=admin_viewer, semester=self.semester)
        self.client.login(username=admin_viewer.email, password=PASSWORD)

        for person in (self.teammate, admin_viewer):
            with self.subTest(person=person.name):
                response = self.client.get(member_detail_url(person))

                self.assertNotContains(response, 'Admin')

    def test_the_auth_surface_is_never_rendered_on_either_page(self):
        """The AbstractBaseUser/PermissionsMixin surface — password, last_login, is_active — is never rendered."""
        self.client.login(username=self.viewer.email, password=PASSWORD)  # refreshes last_login

        for person in (self.teammate, self.viewer):
            with self.subTest(person=person.name):
                person.refresh_from_db()
                response = self.client.get(member_detail_url(person))

                self.assertNotContains(response, person.password)
                self.assertNotContains(response, 'last_login')
                self.assertNotContains(response, 'is_active')

    def test_recordings_are_never_rendered_on_either_page(self):
        """A Recording is reached from the Song side only; neither page lists a Person's uploads."""
        song = SongFactory(semester=self.semester, title='Song R')
        rehearsal_song = RehearsalSongFactory(song=song, rehearsal=RehearsalFactory(semester=self.semester))

        for person in (self.teammate, self.viewer):
            with self.subTest(person=person.name):
                recording = RecordingFactory(
                    rehearsal_song=rehearsal_song, uploaded_by=person, note=f'Upload note for {person.name}',
                )
                SongRoleAssignmentFactory(song=song, person=person)

                response = self.client.get(member_detail_url(person))

                self.assertNotContains(response, recording.note)
                self.assertNotContains(response, str(recording.file))
                self.assertNotIn('recording_groups', response.context)

    def test_song_detail_fields_beyond_title_and_role_are_never_rendered(self):
        """Song detail (artist, notes) belongs on the Song page, not on a Person's."""
        song = SongFactory(
            semester=self.semester, title='Song A', artist='A Placeholder Artist',
            notes='A distinctive placeholder note',
        )
        SongRoleAssignmentFactory(song=song, person=self.teammate)

        response = self.client.get(member_detail_url(self.teammate))

        self.assertContains(response, 'Song A')
        self.assertNotContains(response, 'A Placeholder Artist')
        self.assertNotContains(response, 'A distinctive placeholder note')


@override_settings(SECURE_SSL_REDIRECT=False)
class SelfViewGetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic Person and the current Semester."""
        cls.semester = SemesterFactory()
        cls.person = PersonFactory(password=PASSWORD, name='Owner Placeholder')

    def setUp(self):
        """Log in as the synthetic Person before each test."""
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_renders_own_name_and_email(self):
        """Your own page shows your name and your email — self-only fields.

        The change-password link used to live here too (issue #90); #327
        removes it from this server-rendered page in favor of an SPA
        affordance #333 builds.
        """
        MembershipFactory(person=self.person, semester=self.semester)

        response = self.client.get(member_detail_url(self.person))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_self'])
        self.assertContains(response, 'Owner Placeholder')
        self.assertContains(response, self.person.email)

    def test_renders_the_roles_form_always_inline(self):
        """The MembershipRolesForm renders inline with a Save button — no edit toggle."""
        membership = MembershipFactory(person=self.person, semester=self.semester)
        role = RoleFactory(name='Guitarist')
        MembershipRoleFactory(membership=membership, role=role)

        response = self.client.get(member_detail_url(self.person))

        self.assertEqual(response.context['form'].instance, membership)
        self.assertIn(role, response.context['form'].fields['roles'].initial)
        self.assertContains(response, 'name="roles"')
        self.assertContains(response, 'Save')

    def test_own_page_with_no_membership_yet_renders_the_form_without_creating_one(self):
        """Your own pk is reachable with no current-Semester Membership, on an unsaved instance (no row created)."""
        response = self.client.get(member_detail_url(self.person))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].instance.pk)
        self.assertFalse(Membership.objects.filter(person=self.person, semester=self.semester).exists())

    def test_own_page_with_no_membership_omits_the_roles_and_songs_sections(self):
        """Not on the roster yet: an explicit empty state instead of declared-Roles and assigned-Songs sections."""
        response = self.client.get(member_detail_url(self.person))

        self.assertIsNone(response.context['membership'].pk)
        self.assertContains(response, 'You are not on the roster for this semester yet.')
        self.assertNotContains(response, 'Declared roles')
        self.assertNotContains(response, 'Songs assigned')

    def test_own_page_shows_no_active_semester_message_when_none_exists(self):
        """With no Semester at all, your own page renders an empty state without a form instead of erroring."""
        self.semester.delete()

        response = self.client.get(member_detail_url(self.person))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('form', response.context)
        self.assertContains(response, 'There is no active semester yet.')

    def test_own_page_renders_declared_roles_and_assigned_songs(self):
        """A rostered owner sees the same declared-Roles and assigned-Songs sections a teammate would."""
        membership = MembershipFactory(person=self.person, semester=self.semester)
        role = RoleFactory(name='Keyboardist')
        MembershipRoleFactory(membership=membership, role=role)
        song = SongFactory(semester=self.semester, title='Song A')
        SongRoleAssignmentFactory(song=song, person=self.person, role=role)

        response = self.client.get(member_detail_url(self.person))

        self.assertContains(response, 'Declared roles')
        self.assertContains(response, 'Songs assigned')
        self.assertContains(response, 'Song A')
        self.assertContains(response, 'Keyboardist')


@override_settings(SECURE_SSL_REDIRECT=False)
class SelfViewPostTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a synthetic Person and the current Semester."""
        cls.semester = SemesterFactory()
        cls.person = PersonFactory(password=PASSWORD, name='Owner Placeholder')

    def setUp(self):
        """Log in as the synthetic Person before each test."""
        self.client.login(username=self.person.email, password=PASSWORD)

    def test_valid_post_creates_membership_and_roles_and_redirects_with_message(self):
        """A valid POST with no prior Membership creates one, sets its Roles, and redirects back with a message."""
        role = RoleFactory()

        response = self.client.post(member_detail_url(self.person), {'roles': [role.pk]}, follow=True)

        self.assertRedirects(response, member_detail_url(self.person))
        membership = Membership.objects.get(person=self.person, semester=self.semester)
        self.assertEqual(
            list(MembershipRole.objects.filter(membership=membership).values_list('role', flat=True)), [role.pk],
        )
        self.assertIn('Profile updated.', [str(message) for message in response.context['messages']])

    def test_valid_post_replaces_previously_declared_roles(self):
        """A valid POST removes previously declared Roles that weren't resubmitted."""
        membership = MembershipFactory(person=self.person, semester=self.semester)
        new_role = RoleFactory()
        MembershipRoleFactory(membership=membership, role=RoleFactory())

        self.client.post(member_detail_url(self.person), {'roles': [new_role.pk]})

        declared_role_ids = set(MembershipRole.objects.filter(membership=membership).values_list('role_id', flat=True))
        self.assertEqual(declared_role_ids, {new_role.pk})

    def test_invalid_post_rerenders_the_form_with_errors(self):
        """A POST referencing a nonexistent Role id re-renders the form with a field error, not a 500."""
        response = self.client.post(member_detail_url(self.person), {'roles': [999999]})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'is not one of the available choices')
        self.assertFalse(Membership.objects.filter(person=self.person, semester=self.semester).exists())

    def test_first_time_post_that_loses_the_creation_race_still_saves_its_roles(self):
        """A concurrent first submission whose Membership was created under it writes its Roles to that row.

        Both requests read no Membership and build an unsaved one; patching
        the lookup to return a stale unsaved instance stands in for the
        loser, which must not 500 on
        `unique_membership_per_person_per_semester`.
        """
        role = RoleFactory()
        winner = Membership.objects.create(person=self.person, semester=self.semester)
        stale = Membership(person=self.person, semester=self.semester)

        with patch.object(MemberDetailView, '_get_or_build_membership', return_value=stale):
            response = self.client.post(member_detail_url(self.person), {'roles': [role.pk]})

        self.assertRedirects(response, member_detail_url(self.person))
        self.assertEqual(Membership.objects.filter(person=self.person, semester=self.semester).count(), 1)
        self.assertEqual(
            list(MembershipRole.objects.filter(membership=winner).values_list('role', flat=True)), [role.pk],
        )

    def test_post_with_no_current_semester_saves_nothing(self):
        """With no Semester at all, a POST to your own page re-renders the empty state instead of erroring."""
        self.semester.delete()

        response = self.client.post(member_detail_url(self.person), {'roles': []})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'There is no active semester yet.')
        self.assertFalse(Membership.objects.exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class AdminEditTests(TestCase):
    """Issue #232: the POST guard relaxes to your own pk *or* an admin's, on anyone's page."""

    @classmethod
    def setUpTestData(cls):
        """Build an admin viewer and roster a separate teammate on the current Semester."""
        cls.semester = SemesterFactory()
        cls.admin = PersonFactory(password=PASSWORD, name='Admin Placeholder', is_admin=True)
        cls.teammate = PersonFactory(name='Teammate Placeholder')
        cls.membership = MembershipFactory(person=cls.teammate, semester=cls.semester)

    def setUp(self):
        """Log in as the admin viewer before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_admin_sees_the_roles_form_on_a_teammates_page(self):
        """An admin viewing another Person's page gets the always-inline MembershipRolesForm."""
        RoleFactory()

        response = self.client.get(member_detail_url(self.teammate))

        self.assertEqual(response.context['form'].instance, self.membership)
        self.assertContains(response, 'name="roles"')
        self.assertContains(response, 'Save')

    def test_admin_can_save_a_teammates_declared_roles(self):
        """A valid admin POST writes the teammate's Roles through the existing form and redirects to their page."""
        role = RoleFactory(name='Bassist')

        response = self.client.post(member_detail_url(self.teammate), {'roles': [role.pk]}, follow=True)

        self.assertRedirects(response, member_detail_url(self.teammate))
        self.assertEqual(
            list(MembershipRole.objects.filter(membership=self.membership).values_list('role', flat=True)),
            [role.pk],
        )

    def test_admin_post_replaces_previously_declared_roles(self):
        """An admin POST removes previously declared Roles that weren't resubmitted, same as a self edit."""
        new_role = RoleFactory()
        MembershipRoleFactory(membership=self.membership, role=RoleFactory())

        self.client.post(member_detail_url(self.teammate), {'roles': [new_role.pk]})

        declared_role_ids = set(
            MembershipRole.objects.filter(membership=self.membership).values_list('role_id', flat=True),
        )
        self.assertEqual(declared_role_ids, {new_role.pk})

    def test_admin_post_re_evaluates_mismatch_through_the_model(self):
        """After an admin's save, is_role_mismatch on an existing assignment is re-derived from the new Roles."""
        song = SongFactory(semester=self.semester, title='Song A')
        role = RoleFactory(name='Drummer')
        assignment = SongRoleAssignmentFactory(song=song, person=self.teammate, role=role)
        self.assertTrue(assignment.is_role_mismatch)

        self.client.post(member_detail_url(self.teammate), {'roles': [role.pk]})

        assignment.refresh_from_db()
        self.assertFalse(assignment.is_role_mismatch)

    def test_admin_invalid_post_rerenders_the_form_with_errors(self):
        """An admin POST referencing a nonexistent Role id re-renders the form with a field error, not a 500."""
        response = self.client.post(member_detail_url(self.teammate), {'roles': [999999]})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'is not one of the available choices')

    def test_admin_first_time_post_that_loses_the_creation_race_still_saves_its_roles(self):
        """A concurrent first submission whose Membership was created under it writes its Roles to that row.

        Mirrors the self-edit race test: patching the lookup to return a
        stale unsaved instance stands in for the loser of a concurrent
        first submission, which must not 500 on
        `unique_membership_per_person_per_semester`.
        """
        never_rostered = PersonFactory(name='Fresh Invite Placeholder')
        role = RoleFactory()
        winner = Membership.objects.create(person=never_rostered, semester=self.semester)
        stale = Membership(person=never_rostered, semester=self.semester)

        with patch.object(MemberDetailView, '_get_or_build_membership', return_value=stale):
            response = self.client.post(member_detail_url(never_rostered), {'roles': [role.pk]})

        self.assertRedirects(response, member_detail_url(never_rostered))
        self.assertEqual(Membership.objects.filter(person=never_rostered, semester=self.semester).count(), 1)
        self.assertEqual(
            list(MembershipRole.objects.filter(membership=winner).values_list('role', flat=True)), [role.pk],
        )

    def test_no_remove_control_on_an_admins_view_of_a_teammates_page(self):
        """Removal stays list-only (`/members/`); this page has no remove control at any cardinality."""
        response = self.client.get(member_detail_url(self.teammate))

        self.assertNotContains(response, 'Remove')

    def test_no_conflict_field_renders_for_an_admin_viewer(self):
        """Per ADR 0005, no Conflict field — reason included — appears on this page for an admin viewer either."""
        conflict = ConflictFactory(
            person=self.teammate,
            rehearsal=RehearsalFactory(semester=self.semester),
            type=Conflict.PARTIAL,
            reason='A distinctive placeholder reason',
        )

        response = self.client.get(member_detail_url(self.teammate))

        self.assertNotContains(response, 'A distinctive placeholder reason')
        self.assertNotContains(response, str(conflict.rehearsal.date))

    def test_admins_own_page_is_byte_identical_to_a_non_admins_own_page(self):
        """An admin's own GET/POST flow is unaffected — is_self alone already granted the form."""
        response = self.client.get(member_detail_url(self.admin))

        self.assertTrue(response.context['is_self'])
        self.assertIn('form', response.context)

        role = RoleFactory()
        post_response = self.client.post(member_detail_url(self.admin), {'roles': [role.pk]}, follow=True)

        self.assertRedirects(post_response, member_detail_url(self.admin))
        membership = Membership.objects.get(person=self.admin, semester=self.semester)
        self.assertEqual(
            list(MembershipRole.objects.filter(membership=membership).values_list('role', flat=True)), [role.pk],
        )
