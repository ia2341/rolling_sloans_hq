"""Executable counterpart to `docs/person-page-visibility.md` (issue #316).

`test_members_view.py` and `test_member_detail_view.py` already assert most
of the doc's field-by-field verdicts inline with the tests that cover a
surface's happy path. This module fills the verdicts neither file exercises
for a **non-admin** viewer — `is_role_mismatch`, `Conflict`/`ConflictWindow`,
the Roster's remove control, and `Backup.covering_for` — on both member-facing
roster routes, so the doc's table has no row left unbacked by a test. As
`/api/` payloads land (per the doc's own note), the same forbidden-value
assertions apply to their bodies too.
"""

from datetime import time

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    BackupFactory,
    ConflictFactory,
    ConflictWindowFactory,
    MembershipFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Conflict

PASSWORD = 'a-strong-test-password-123'


def member_detail_url(person):
    """Return `/members/<pk>/` for `person`."""
    return reverse('scheduling:member-detail', args=[person.pk])


@override_settings(SECURE_SSL_REDIRECT=False)
class MembersListPrivacyTests(TestCase):
    """`/members/` verdicts for a non-admin viewer that no other test module exercises.

    `is_role_mismatch`, `Conflict`/`ConflictWindow`, and the remove control
    are all `never` for a Teammate and for Self alike, per the roster table
    in `docs/person-page-visibility.md`.
    """

    @classmethod
    def setUpTestData(cls):
        """Build a viewer and a teammate, both rostered on the current Semester."""
        cls.semester = SemesterFactory()
        cls.viewer = PersonFactory(password=PASSWORD, name='Viewer Placeholder')
        cls.viewer_membership = MembershipFactory(person=cls.viewer, semester=cls.semester)
        cls.teammate = PersonFactory(name='Teammate Placeholder')
        cls.teammate_membership = MembershipFactory(person=cls.teammate, semester=cls.semester)

    def setUp(self):
        """Log in as the viewer before each test."""
        self.client.login(username=self.viewer.email, password=PASSWORD)

    def _assign_mismatched_song(self, person, role_name):
        """Assign `person` to a fresh current-Semester Song under an undeclared Role, so is_role_mismatch is True."""
        song = SongFactory(semester=self.semester, title='Song M')
        assignment = SongRoleAssignmentFactory(song=song, person=person, role=RoleFactory(name=role_name))
        self.assertTrue(assignment.is_role_mismatch)
        return assignment

    def test_role_mismatch_is_never_rendered_for_a_teammate_or_self(self):
        """A row's `songs_count` reflects a mismatched assignment, but the flag itself never renders."""
        self._assign_mismatched_song(self.teammate, 'Undeclared Role A')
        self._assign_mismatched_song(self.viewer, 'Undeclared Role B')

        response = self.client.get(reverse('scheduling:members'))

        self.assertContains(response, '1 Song', count=2)
        self.assertNotContains(response, 'mismatch')

    def test_conflict_data_is_never_rendered_for_a_teammate_or_self(self):
        """ADR 0005's boundary is drawn around the surface, not the viewer: no Conflict field reaches the roster."""
        for person in (self.teammate, self.viewer):
            conflict = ConflictFactory(
                person=person,
                rehearsal=RehearsalFactory(semester=self.semester),
                type=Conflict.PARTIAL,
                reason='A distinctive placeholder reason',
            )
            ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 15), unavailable_end=time(18, 45))

        response = self.client.get(reverse('scheduling:members'))

        self.assertNotContains(response, 'A distinctive placeholder reason')
        self.assertNotContains(response, '18:15')

    def test_no_remove_control_for_a_non_admin(self):
        """The Roster editor's remove control is admin-edit-mode-only; a non-admin's read mode has none at all."""
        response = self.client.get(reverse('scheduling:members'))

        self.assertNotContains(response, 'Remove')

    def test_own_row_shows_no_email_either(self):
        """`Person.email` is `never` on this route even for your own row — the invite form is the only place it renders."""
        response = self.client.get(reverse('scheduling:members'))

        self.assertNotContains(response, self.viewer.email)


@override_settings(SECURE_SSL_REDIRECT=False)
class MemberDetailBackupPrivacyTests(TestCase):
    """`/members/<pk>/` verdicts for `Backup` (ADR 0007), untested elsewhere.

    Every `Backup` field is `never` on this route for anyone, `covering_for`
    above all: naming the covered Person would disclose that they declared
    a `Conflict` for that date, exactly what ADR 0005 keeps off member-facing
    routes.
    """

    @classmethod
    def setUpTestData(cls):
        """Build a viewer, a teammate, and a Backup covering a third Person on a current-Semester Rehearsal slot."""
        cls.semester = SemesterFactory()
        cls.viewer = PersonFactory(password=PASSWORD, name='Viewer Placeholder')
        MembershipFactory(person=cls.viewer, semester=cls.semester)
        cls.teammate = PersonFactory(name='Teammate Placeholder')
        MembershipFactory(person=cls.teammate, semester=cls.semester)
        cls.covered_person = PersonFactory(name='Covered Placeholder')
        rehearsal_song = RehearsalSongFactory(
            song=SongFactory(semester=cls.semester), rehearsal=RehearsalFactory(semester=cls.semester),
        )
        cls.backup = BackupFactory(
            rehearsal_song=rehearsal_song, person=cls.teammate, covering_for=cls.covered_person,
        )

    def setUp(self):
        """Log in as the viewer before each test."""
        self.client.login(username=self.viewer.email, password=PASSWORD)

    def test_covering_for_is_never_rendered_on_a_teammates_page(self):
        """The teammate standing in as a Backup has their page render with no trace of who they're covering."""
        response = self.client.get(member_detail_url(self.teammate))

        self.assertNotContains(response, 'Covered Placeholder')

    def test_no_backup_or_rehearsal_data_on_the_covered_persons_own_page(self):
        """The covered Person's own page carries no Backup or Rehearsal trace — this route has no Rehearsal in scope."""
        self.covered_person.set_password(PASSWORD)
        self.covered_person.save()
        MembershipFactory(person=self.covered_person, semester=self.semester)
        self.client.login(username=self.covered_person.email, password=PASSWORD)

        response = self.client.get(member_detail_url(self.covered_person))

        self.assertNotContains(response, 'backup')
        self.assertNotContains(response, str(self.backup.rehearsal_song.rehearsal.date))
        self.assertNotContains(response, self.teammate.name)
