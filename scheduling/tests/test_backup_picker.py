"""The picker's Backup (this rehearsal only) section, Backup chips, and covering_for (issue #216)."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from identity.factories import PersonFactory
from scheduling.factories import (
    BackupFactory,
    ConflictFactory,
    MembershipFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import Backup

PASSWORD = 'a-strong-test-password-123'


def _schedule_url(rehearsal):
    """Return /schedule/?rehearsal=<id> for `rehearsal`."""
    return f"{reverse('scheduling:schedule')}?rehearsal={rehearsal.pk}"


def _save_url(rehearsal):
    """Return the assignment-save POST endpoint for `rehearsal`."""
    return reverse('scheduling:schedule-assignments-save', args=[rehearsal.pk])


def _picker_url(rehearsal, song, role):
    """Return the "+" picker's fetch endpoint for one (Song, Role) cell on `rehearsal`'s grid."""
    return reverse('scheduling:schedule-assignments-picker', args=[rehearsal.pk, song.pk, role.pk])


def _save_payload(rehearsal, *, added_backup_entries=(), removed_backup_ids=(), backup_covering_for_updates=()):
    """Build a Save Changes POST body naming Backup adds/removals/covering_for updates against `rehearsal`'s Semester."""
    semester = rehearsal.semester
    payload = {
        'assignment_semester_id': str(semester.pk),
        'assignment_semester_updated_at': semester.updated_at.isoformat(),
    }
    if added_backup_entries:
        payload['added_backup_entry'] = [
            f"{rehearsal_song_id}:{role_id}:{person_id}:{'' if covering_for_id is None else covering_for_id}"
            for rehearsal_song_id, role_id, person_id, covering_for_id in added_backup_entries
        ]
    if removed_backup_ids:
        payload['removed_backup_id'] = [str(pk) for pk in removed_backup_ids]
    for backup_id, covering_for_id in backup_covering_for_updates:
        payload[f'backup_covering_for_{backup_id}'] = '' if covering_for_id is None else str(covering_for_id)
    return payload


@override_settings(SECURE_SSL_REDIRECT=False)
class BackupPickerSectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build an admin, a future Rehearsal with one Song/Role column scheduled on it."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False)
        cls.song = SongFactory(semester=cls.semester, position=1)
        cls.role = RoleFactory(name='Bassist')
        SongRoleRequirementFactory(song=cls.song, role=cls.role, count=1)
        cls.rehearsal_song = RehearsalSongFactory(song=cls.song, rehearsal=cls.rehearsal, order=1)

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_backup_section_is_labelled_as_this_rehearsal_only(self):
        """The picker's second section is labelled distinctly from the standing-assignment section."""
        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertContains(response, 'Backup (this rehearsal only)')
        self.assertContains(response, 'Assigned (every rehearsal + concert)')

    def test_a_rostered_member_is_offered_in_the_backup_section(self):
        """A rostered Member appears as a pickable Backup option."""
        member = PersonFactory(name='Bailey Backup')
        MembershipFactory(person=member, semester=self.semester)

        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertContains(response, f'data-backup-picker-person-id="{member.pk}"')

    def test_a_non_rostered_person_is_not_offered_as_a_backup(self):
        """A Person with no Membership in the viewed Semester never appears in the Backup section."""
        PersonFactory(name='Outsider Olga')

        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertNotContains(response, 'Outsider Olga')

    def test_a_person_already_backed_up_on_this_cell_is_not_reoffered(self):
        """A Person who already has a Backup on this exact (rehearsal_song, role) isn't offered again."""
        already = BackupFactory(rehearsal_song=self.rehearsal_song, role=self.role)
        MembershipFactory(person=already.person, semester=self.semester)

        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertNotContains(response, f'data-backup-picker-person-id="{already.person.pk}"')

    def test_a_standing_assignee_is_still_offered_as_a_backup(self):
        """A Person already assigned to the cell may still be offered as a Backup — the two are independent."""
        assignment = SongRoleAssignmentFactory(song=self.song, role=self.role)
        MembershipFactory(person=assignment.person, semester=self.semester)

        response = self.client.get(_picker_url(self.rehearsal, self.song, self.role))

        self.assertContains(response, f'data-backup-picker-person-id="{assignment.person.pk}"')

    def test_dress_rehearsal_offers_no_backup_section_with_structural_copy(self):
        """The Dress Rehearsal's picker explains the missing Backup section structurally, not as a permission gap."""
        dress = RehearsalFactory(semester=self.semester, is_full_setlist=True)
        song = SongFactory(semester=self.semester, position=2)
        SongRoleRequirementFactory(song=song, role=self.role, count=1)

        response = self.client.get(_picker_url(dress, song, self.role))

        self.assertNotContains(response, 'data-backup-picker-person-id')
        self.assertContains(response, 'no per-song schedule of its own')
        self.assertNotContains(response, 'permission')

    def test_backup_picker_on_a_past_rehearsal_404s(self):
        """A hand-crafted picker fetch against a non-editable (past-dated) Rehearsal's grid 404s, same as the standing-assignment picker."""
        past_rehearsal = RehearsalFactory(
            semester=self.semester, is_full_setlist=False, date=timezone.localdate() - timedelta(days=1),
        )

        response = self.client.get(_picker_url(past_rehearsal, self.song, self.role))

        self.assertEqual(response.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class SaveBackupEditsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build an admin, a future Rehearsal with one scheduled Song/Role, and a standing assignee on it."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False)
        cls.song = SongFactory(semester=cls.semester, position=1)
        cls.role = RoleFactory()
        SongRoleRequirementFactory(song=cls.song, role=cls.role, count=1)
        cls.rehearsal_song = RehearsalSongFactory(song=cls.song, rehearsal=cls.rehearsal, order=1)
        cls.assignment = SongRoleAssignmentFactory(song=cls.song, role=cls.role)

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_adding_from_the_backup_section_creates_a_backup_on_the_cells_song_role_and_person(self):
        """Saving an added Backup entry creates a Backup anchored on the cell's RehearsalSong, Role and Person."""
        member = MembershipFactory(semester=self.semester)

        response = self.client.post(
            _save_url(self.rehearsal),
            _save_payload(
                self.rehearsal,
                added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, member.person.pk, None)],
            ),
        )

        self.assertRedirects(response, _schedule_url(self.rehearsal))
        self.assertTrue(
            Backup.objects.filter(
                rehearsal_song=self.rehearsal_song, role=self.role, person=member.person,
            ).exists()
        )

    def test_saving_a_backup_with_covering_for_empty_succeeds(self):
        """A Backup save with no covering_for selection succeeds, leaving covering_for null."""
        member = MembershipFactory(semester=self.semester)

        self.client.post(
            _save_url(self.rehearsal),
            _save_payload(
                self.rehearsal,
                added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, member.person.pk, None)],
            ),
        )

        backup = Backup.objects.get(rehearsal_song=self.rehearsal_song, role=self.role, person=member.person)
        self.assertIsNone(backup.covering_for)

    def test_saving_a_backup_with_covering_for_set_records_it(self):
        """A Backup save naming a covering_for Person records that Person on the created row."""
        backer = MembershipFactory(semester=self.semester)
        covered = MembershipFactory(semester=self.semester)

        self.client.post(
            _save_url(self.rehearsal),
            _save_payload(
                self.rehearsal,
                added_backup_entries=[
                    (self.rehearsal_song.pk, self.role.pk, backer.person.pk, covered.person.pk),
                ],
            ),
        )

        backup = Backup.objects.get(rehearsal_song=self.rehearsal_song, role=self.role, person=backer.person)
        self.assertEqual(backup.covering_for, covered.person)

    def test_a_covering_for_pick_naming_the_backup_person_themself_is_dropped_rather_than_failing_the_save(self):
        """A tampered covering_for equal to the Backup's own person is silently dropped to None, not a 500."""
        member = MembershipFactory(semester=self.semester)

        response = self.client.post(
            _save_url(self.rehearsal),
            _save_payload(
                self.rehearsal,
                added_backup_entries=[
                    (self.rehearsal_song.pk, self.role.pk, member.person.pk, member.person.pk),
                ],
            ),
        )

        self.assertRedirects(response, _schedule_url(self.rehearsal))
        backup = Backup.objects.get(rehearsal_song=self.rehearsal_song, role=self.role, person=member.person)
        self.assertIsNone(backup.covering_for)

    def test_several_backups_on_the_same_slot_and_role_are_all_created(self):
        """Several Backups on the same slot and role — a genuinely shared cover — are all creatable together."""
        first = MembershipFactory(semester=self.semester)
        second = MembershipFactory(semester=self.semester)

        self.client.post(
            _save_url(self.rehearsal),
            _save_payload(
                self.rehearsal,
                added_backup_entries=[
                    (self.rehearsal_song.pk, self.role.pk, first.person.pk, None),
                    (self.rehearsal_song.pk, self.role.pk, second.person.pk, None),
                ],
            ),
        )

        self.assertEqual(
            Backup.objects.filter(rehearsal_song=self.rehearsal_song, role=self.role).count(), 2,
        )

    def test_a_backup_with_no_standing_assignee_at_all_is_legal(self):
        """A Backup can be added on a cell that carries no standing SongRoleAssignment at all."""
        unfilled_role = RoleFactory()
        SongRoleRequirementFactory(song=self.song, role=unfilled_role, count=1)
        member = MembershipFactory(semester=self.semester)

        response = self.client.post(
            _save_url(self.rehearsal),
            _save_payload(
                self.rehearsal,
                added_backup_entries=[(self.rehearsal_song.pk, unfilled_role.pk, member.person.pk, None)],
            ),
        )

        self.assertRedirects(response, _schedule_url(self.rehearsal))
        self.assertTrue(
            Backup.objects.filter(rehearsal_song=self.rehearsal_song, role=unfilled_role, person=member.person).exists()
        )

    def test_removing_a_backup_chip_deletes_the_backup(self):
        """A Save Changes POST naming a Backup id in removed_backup_id deletes that row."""
        backup = BackupFactory(rehearsal_song=self.rehearsal_song, role=self.role)

        response = self.client.post(
            _save_url(self.rehearsal), _save_payload(self.rehearsal, removed_backup_ids=[backup.pk]),
        )

        self.assertRedirects(response, _schedule_url(self.rehearsal))
        self.assertFalse(Backup.objects.filter(pk=backup.pk).exists())

    def test_updating_a_persisted_backups_covering_for_select_saves_it(self):
        """Resubmitting a persisted Backup's covering_for select with a new pick updates that Backup's covering_for."""
        backup = BackupFactory(rehearsal_song=self.rehearsal_song, role=self.role, covering_for=None)
        covered = MembershipFactory(semester=self.semester)

        response = self.client.post(
            _save_url(self.rehearsal),
            _save_payload(
                self.rehearsal, backup_covering_for_updates=[(backup.pk, covered.person.pk)],
            ),
        )

        self.assertRedirects(response, _schedule_url(self.rehearsal))
        backup.refresh_from_db()
        self.assertEqual(backup.covering_for, covered.person)

    def test_a_removed_backups_covering_for_update_is_a_no_op(self):
        """A covering_for update naming a Backup id that was also removed this save doesn't resurrect it."""
        backup = BackupFactory(rehearsal_song=self.rehearsal_song, role=self.role, covering_for=None)

        self.client.post(
            _save_url(self.rehearsal),
            _save_payload(
                self.rehearsal,
                removed_backup_ids=[backup.pk],
                backup_covering_for_updates=[(backup.pk, self.assignment.person.pk)],
            ),
        )

        self.assertFalse(Backup.objects.filter(pk=backup.pk).exists())

    def test_no_backup_can_be_created_against_the_dress_rehearsal(self):
        """A hand-crafted POST naming a RehearsalSong that doesn't exist (the Dress Rehearsal's case) creates nothing."""
        member = MembershipFactory(semester=self.semester)
        bogus_rehearsal_song_id = self.rehearsal_song.pk + 1000

        response = self.client.post(
            _save_url(self.rehearsal),
            _save_payload(
                self.rehearsal,
                added_backup_entries=[(bogus_rehearsal_song_id, self.role.pk, member.person.pk, None)],
            ),
        )

        self.assertRedirects(response, _schedule_url(self.rehearsal))
        self.assertEqual(Backup.objects.filter(role=self.role, person=member.person).count(), 0)

    def test_non_admin_backup_save_is_forbidden(self):
        """A logged-in non-admin's Backup-adding Save Changes POST is rejected with 403 and writes nothing."""
        self.client.logout()
        person = PersonFactory(password=PASSWORD)
        self.client.login(username=person.email, password=PASSWORD)
        member = MembershipFactory(semester=self.semester)

        response = self.client.post(
            _save_url(self.rehearsal),
            _save_payload(
                self.rehearsal,
                added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, member.person.pk, None)],
            ),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Backup.objects.filter(role=self.role, person=member.person).count(), 0)

    def test_anonymous_backup_save_post_redirects_to_login(self):
        """An anonymous Save Changes POST carrying a Backup add redirects to login rather than applying anything."""
        self.client.logout()
        member = MembershipFactory(semester=self.semester)

        response = self.client.post(
            _save_url(self.rehearsal),
            _save_payload(
                self.rehearsal,
                added_backup_entries=[(self.rehearsal_song.pk, self.role.pk, member.person.pk, None)],
            ),
        )

        self.assertRedirects(response, f"{reverse('identity:login')}?next={_save_url(self.rehearsal)}")
        self.assertEqual(Backup.objects.filter(role=self.role, person=member.person).count(), 0)


@override_settings(SECURE_SSL_REDIRECT=False)
class BackupChipRenderingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Rehearsal with a scheduled Song/Role carrying one standing assignment and one Backup."""
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False)
        cls.song = SongFactory(semester=cls.semester, position=1)
        cls.role = RoleFactory()
        SongRoleRequirementFactory(song=cls.song, role=cls.role, count=1)
        cls.rehearsal_song = RehearsalSongFactory(song=cls.song, rehearsal=cls.rehearsal, order=1)
        cls.assignment = SongRoleAssignmentFactory(song=cls.song, role=cls.role)
        cls.covered = PersonFactory(name='Covered Cara')
        MembershipFactory(person=cls.covered, semester=cls.semester)
        cls.backup = BackupFactory(
            rehearsal_song=cls.rehearsal_song, role=cls.role, covering_for=cls.covered,
        )
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.member = PersonFactory(password=PASSWORD)
        MembershipFactory(person=cls.member, semester=cls.semester)

    def test_backup_chip_renders_as_name_backup(self):
        """A Backup chip reads as '<name> (backup)'."""
        self.client.login(username=self.member.email, password=PASSWORD)

        response = self.client.get(_schedule_url(self.rehearsal))

        self.assertContains(response, f'{self.backup.person.name} (backup)')

    def test_backup_chip_carries_a_distinct_style_class(self):
        """A Backup chip carries the backup-chip class, distinct from a plain assignment-chip."""
        self.client.login(username=self.admin.email, password=PASSWORD)

        response = self.client.get(_schedule_url(self.rehearsal))

        self.assertContains(response, 'backup-chip')

    def test_covering_for_renders_for_an_admin(self):
        """An admin's rendered grid names who the Backup covers for."""
        self.client.login(username=self.admin.email, password=PASSWORD)

        response = self.client.get(_schedule_url(self.rehearsal))

        self.assertContains(response, self.covered.name)

    def test_covering_for_never_renders_for_a_member(self):
        """A member's rendered grid shows the Backup chip but never who it covers for (ADR-0005), asserted from their own session."""
        self.client.login(username=self.member.email, password=PASSWORD)

        response = self.client.get(_schedule_url(self.rehearsal))

        self.assertContains(response, f'{self.backup.person.name} (backup)')
        self.assertNotContains(response, self.covered.name)

    def test_backup_renders_on_the_member_facing_schedule(self):
        """The Backup itself (not its covering_for) is visible on a member's Schedule."""
        self.client.login(username=self.member.email, password=PASSWORD)

        response = self.client.get(_schedule_url(self.rehearsal))

        self.assertContains(response, self.backup.person.name)

    def test_withdrawing_the_covered_persons_conflict_leaves_the_backup_standing(self):
        """Withdrawing the covered Person's Conflict leaves the Backup row (and its covering_for) untouched."""
        conflict = ConflictFactory(person=self.covered, rehearsal=self.rehearsal)
        self.assertFalse(Backup.objects.get(pk=self.backup.pk).is_stale())

        conflict.delete()

        backup = Backup.objects.get(pk=self.backup.pk)
        self.assertEqual(backup.covering_for, self.covered)
        self.assertTrue(backup.is_stale())

    def test_dress_rehearsal_matrix_carries_no_backup_entries(self):
        """The Dress Rehearsal's matrix carries no BACKUP-kind entry anywhere — structurally, since it has no RehearsalSong to anchor one on."""
        from scheduling.services import AssignmentMatrixEntryKind, assignment_matrix_for

        dress = RehearsalFactory(semester=self.semester, is_full_setlist=True)

        matrix = assignment_matrix_for(dress)

        kinds = {entry.kind for row in matrix.rows for cell in row.cells for entry in cell.entries}
        self.assertNotIn(AssignmentMatrixEntryKind.BACKUP, kinds)
