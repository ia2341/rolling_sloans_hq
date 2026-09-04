"""The advisory's doors: standing-overlap links to the Running Order and the assignment grid (issue #195)."""

import json
from datetime import time

from django.test import TestCase, override_settings
from django.urls import reverse

from identity.factories import PersonFactory
from scheduling.factories import (
    BackupFactory,
    ConflictFactory,
    ConflictWindowFactory,
    RehearsalFactory,
    RehearsalSongFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
)
from scheduling.models import Backup, Conflict, RehearsalSong
from scheduling.services import conflict_feasibility_for

PASSWORD = 'a-strong-test-password-123'


class ConflictFeasibilityRowOverlapTargetTests(TestCase):
    """`conflict_feasibility_for()` also names the (Song, Role) cell a standing overlap sits at."""

    def test_overlap_target_names_the_song_and_role_the_advisory_is_about(self):
        """A row carrying the advisory also carries the Song/Role id the overlap was found at."""
        semester = SemesterFactory(default_song_slot_count=1)
        rehearsal = RehearsalFactory(
            semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(18, 30),
        )
        song = SongFactory(semester=semester)
        RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1, slot_count=1)
        role = RoleFactory()
        person = PersonFactory()
        SongRoleAssignmentFactory(song=song, person=person, role=role)
        conflict = ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL, status=Conflict.APPROVED)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

        rows = {row.conflict_id: row for row in conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict.pk})}

        row = rows[conflict.pk]
        self.assertTrue(row.has_standing_overlap)
        self.assertEqual(row.overlap_song_id, song.pk)
        self.assertEqual(row.overlap_role_id, role.pk)

    def test_no_overlap_target_when_the_advisory_is_silent(self):
        """A row with no standing overlap carries no overlap target either."""
        semester = SemesterFactory(default_song_slot_count=1)
        rehearsal = RehearsalFactory(
            semester=semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(18, 30),
        )
        song = SongFactory(semester=semester)
        rehearsal_song = RehearsalSongFactory(rehearsal=rehearsal, song=song, order=1, slot_count=1)
        role = RoleFactory()
        person = PersonFactory()
        SongRoleAssignmentFactory(song=song, person=person, role=role)
        conflict = ConflictFactory(person=person, rehearsal=rehearsal, type=Conflict.PARTIAL, status=Conflict.APPROVED)
        ConflictWindowFactory(conflict=conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))
        BackupFactory(rehearsal_song=rehearsal_song, role=role, person=PersonFactory())

        rows = {row.conflict_id: row for row in conflict_feasibility_for(rehearsal, approved_conflict_ids={conflict.pk})}

        row = rows[conflict.pk]
        self.assertFalse(row.has_standing_overlap)
        self.assertIsNone(row.overlap_song_id)
        self.assertIsNone(row.overlap_role_id)


@override_settings(SECURE_SSL_REDIRECT=False)
class AdjudicationTableAdvisoryDoorTests(TestCase):
    """The `/manage/conflicts/<rehearsal_id>/` table's advisory column, for a row with a standing overlap."""

    @classmethod
    def setUpTestData(cls):
        """Build an admin, a Semester, a Rehearsal, an assigned Person with an approved overlapping Conflict."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.semester = SemesterFactory(default_song_slot_count=1)
        cls.rehearsal = RehearsalFactory(
            semester=cls.semester, is_full_setlist=False, start_time=time(18, 0), end_time=time(18, 30),
        )
        cls.song = SongFactory(semester=cls.semester)
        RehearsalSongFactory(rehearsal=cls.rehearsal, song=cls.song, order=1, slot_count=1)
        cls.role = RoleFactory()
        cls.person = PersonFactory()
        SongRoleAssignmentFactory(song=cls.song, person=cls.person, role=cls.role)
        cls.conflict = ConflictFactory(
            person=cls.person, rehearsal=cls.rehearsal, type=Conflict.PARTIAL, status=Conflict.APPROVED,
        )
        ConflictWindowFactory(conflict=cls.conflict, unavailable_start=time(18, 0), unavailable_end=time(18, 30))

    def setUp(self):
        """Log in as the synthetic admin Person before each test."""
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_row_with_standing_overlap_links_to_the_running_order(self):
        """The advisory carries a link to the Rehearsal's Running Order, anchored on its row."""
        response = self.client.get(reverse('scheduling:manage-conflicts-detail', args=[self.rehearsal.pk]))

        expected = f"{reverse('scheduling:schedule-edit')}#schedule-edit-row-{self.rehearsal.pk}"
        self.assertContains(response, expected)
        self.assertContains(response, 'data-testid="advisory-running-order-link"')

    def test_row_with_standing_overlap_links_to_the_assignment_grid_with_covering_for_prefilled(self):
        """The advisory's second link names the overlapping (Song, Role) cell and the covered Person."""
        response = self.client.get(reverse('scheduling:manage-conflicts-detail', args=[self.rehearsal.pk]))

        schedule_url = reverse('scheduling:schedule')
        expected = (
            f"{schedule_url}?rehearsal={self.rehearsal.pk}"
            f"&backup_song_id={self.song.pk}&backup_role_id={self.role.pk}&covering_for_id={self.person.pk}"
        )
        self.assertContains(response, expected)
        self.assertContains(response, 'data-testid="advisory-assignment-grid-link"')

    def test_row_with_no_advisory_carries_neither_link(self):
        """A row with no standing overlap renders no Running Order or assignment-grid link."""
        other_semester = SemesterFactory(default_song_slot_count=1)
        other_rehearsal = RehearsalFactory(semester=other_semester, is_full_setlist=False)
        quiet_conflict = ConflictFactory(rehearsal=other_rehearsal, type=Conflict.FULL_CONFLICT)

        response = self.client.get(reverse('scheduling:manage-conflicts-detail', args=[other_rehearsal.pk]))

        self.assertEqual({triple[0].conflict.pk for triple in response.context['triples']}, {quiet_conflict.pk})
        self.assertNotContains(response, 'data-testid="advisory-running-order-link"')
        self.assertNotContains(response, 'data-testid="advisory-assignment-grid-link"')
        self.assertIsNotNone(quiet_conflict)

    def test_backup_silences_the_advisory_and_removes_both_links(self):
        """Once a Backup covers the overlapping cell, the advisory (and its doors) fall silent."""
        rehearsal_song = self.rehearsal.rehearsalsong_set.get(song=self.song)
        BackupFactory(rehearsal_song=rehearsal_song, role=self.role, person=PersonFactory())

        response = self.client.get(reverse('scheduling:manage-conflicts-detail', args=[self.rehearsal.pk]))

        self.assertNotContains(response, 'data-testid="advisory-running-order-link"')
        self.assertNotContains(response, 'data-testid="advisory-assignment-grid-link"')


@override_settings(SECURE_SSL_REDIRECT=False)
class AssignmentGridBackupPrefillTests(TestCase):
    """`/schedule/`'s `?backup_song_id=&backup_role_id=&covering_for_id=` prefill (issue #195)."""

    @classmethod
    def setUpTestData(cls):
        """Build an admin, a non-admin, a Semester, a future Rehearsal, a Song/Role and a covered Person."""
        cls.admin = PersonFactory(password=PASSWORD, is_admin=True)
        cls.member = PersonFactory(password=PASSWORD, is_admin=False)
        cls.semester = SemesterFactory()
        cls.rehearsal = RehearsalFactory(semester=cls.semester, is_full_setlist=False)
        cls.song = SongFactory(semester=cls.semester, position=1)
        RehearsalSongFactory(rehearsal=cls.rehearsal, song=cls.song, order=1)
        cls.role = RoleFactory()
        cls.covered_person = PersonFactory()
        SongRoleAssignmentFactory(song=cls.song, role=cls.role, person=cls.covered_person)

    def _url(self, song=None, role=None, covering_for=None):
        """Build /schedule/?rehearsal=<id> with the optional backup-prefill query params."""
        base = f"{reverse('scheduling:schedule')}?rehearsal={self.rehearsal.pk}"
        if song is not None:
            base += f'&backup_song_id={song}'
        if role is not None:
            base += f'&backup_role_id={role}'
        if covering_for is not None:
            base += f'&covering_for_id={covering_for}'
        return base

    def test_admin_with_valid_params_gets_a_populated_prefill(self):
        """A well-formed prefill link populates the grid's prefill data for an admin."""
        self.client.login(username=self.admin.email, password=PASSWORD)

        response = self.client.get(self._url(self.song.pk, self.role.pk, self.covered_person.pk))

        prefill = json.loads(response.context['prefill_backup_json'])
        self.assertEqual(prefill, {
            'songId': self.song.pk,
            'roleId': self.role.pk,
            'coveringForId': self.covered_person.pk,
        })

    def test_no_params_yields_no_prefill(self):
        """A plain grid visit with no query params carries no prefill."""
        self.client.login(username=self.admin.email, password=PASSWORD)

        response = self.client.get(self._url())

        self.assertEqual(response.context['prefill_backup_json'], 'null')

    def test_non_admin_gets_no_prefill_even_with_a_prefill_link(self):
        """A non-admin can't edit assignments at all, so a prefill link builds no prefill data for them."""
        self.client.login(username=self.member.email, password=PASSWORD)

        response = self.client.get(self._url(self.song.pk, self.role.pk, self.covered_person.pk))

        self.assertEqual(response.context['prefill_backup_json'], 'null')

    def test_malformed_ids_are_ignored_rather_than_erroring(self):
        """Non-numeric query values silently drop the prefill instead of raising a 500."""
        self.client.login(username=self.admin.email, password=PASSWORD)
        url = f"{reverse('scheduling:schedule')}?rehearsal={self.rehearsal.pk}&backup_song_id=not-a-number&backup_role_id=1&covering_for_id=1"

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '"coveringForId"')

    def test_unknown_covering_for_person_drops_the_prefill(self):
        """A covering_for_id naming no real Person silently drops the prefill."""
        self.client.login(username=self.admin.email, password=PASSWORD)

        response = self.client.get(self._url(self.song.pk, self.role.pk, 999999))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '"coveringForId"')

    def test_prefilling_creates_no_backup_and_writes_no_running_order(self):
        """Arriving with a prefill link is a pure read — nothing is created or reordered."""
        self.client.login(username=self.admin.email, password=PASSWORD)
        backup_count = Backup.objects.count()
        order_values = list(RehearsalSong.objects.filter(rehearsal=self.rehearsal).values_list('order', flat=True))

        self.client.get(self._url(self.song.pk, self.role.pk, self.covered_person.pk))

        self.assertEqual(Backup.objects.count(), backup_count)
        self.assertEqual(
            list(RehearsalSong.objects.filter(rehearsal=self.rehearsal).values_list('order', flat=True)),
            order_values,
        )
