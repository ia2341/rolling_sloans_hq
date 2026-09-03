"""apply_song_role_requirements(): the batch write, and the two staleness checks (issue #209)."""

from django.test import TestCase
from django.utils import timezone

from scheduling.factories import (
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleRequirementFactory,
)
from scheduling.models import SongRoleRequirement
from scheduling.services import (
    SongRoleRequirementBuffer,
    SongRoleRequirementEntry,
    StaleSongRoleRequirementsError,
    WrongViewingSemesterError,
    apply_song_role_requirements,
)


class ApplySongRoleRequirementsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Build a Semester with one Song and one Role to submit Buffers against."""
        cls.semester = SemesterFactory()
        cls.song = SongFactory(semester=cls.semester)
        cls.role = RoleFactory()

    def _buffer(self, entries=(), semester=None, song=None, updated_at=None):
        """Build a SongRoleRequirementBuffer against self.semester/self.song unless overridden."""
        semester = semester or self.semester
        song = song or self.song
        return SongRoleRequirementBuffer(
            song_id=song.pk,
            semester_id=semester.pk,
            semester_updated_at=updated_at if updated_at is not None else semester.updated_at,
            entries=list(entries),
        )

    def test_creates_a_new_requirement(self):
        """A Buffer entry naming a Role with no existing Requirement creates one at the given count."""
        buffer = self._buffer(entries=[SongRoleRequirementEntry(role_id=self.role.pk, count=2)])

        apply_song_role_requirements(buffer, viewing_semester=self.semester)

        requirement = SongRoleRequirement.objects.get(song=self.song, role=self.role)
        self.assertEqual(requirement.count, 2)

    def test_changes_an_existing_requirements_count(self):
        """An entry for an already-required Role with a different count updates that row in place."""
        SongRoleRequirementFactory(song=self.song, role=self.role, count=2)
        buffer = self._buffer(entries=[SongRoleRequirementEntry(role_id=self.role.pk, count=3)])

        apply_song_role_requirements(buffer, viewing_semester=self.semester)

        requirement = SongRoleRequirement.objects.get(song=self.song, role=self.role)
        self.assertEqual(requirement.count, 3)

    def test_deletes_a_requirement_missing_from_the_buffer(self):
        """An existing Requirement whose Role isn't named in the Buffer's entries is deleted."""
        SongRoleRequirementFactory(song=self.song, role=self.role, count=2)
        buffer = self._buffer(entries=[])

        apply_song_role_requirements(buffer, viewing_semester=self.semester)

        self.assertFalse(SongRoleRequirement.objects.filter(song=self.song, role=self.role).exists())

    def test_deleting_a_requirement_leaves_other_rows_untouched(self):
        """Deleting one Song's Requirement leaves the Role, other Songs' Requirements untouched."""
        other_song = SongFactory(semester=self.semester)
        SongRoleRequirementFactory(song=self.song, role=self.role, count=2)
        other_requirement = SongRoleRequirementFactory(song=other_song, role=self.role, count=1)
        buffer = self._buffer(entries=[])

        apply_song_role_requirements(buffer, viewing_semester=self.semester)

        self.assertTrue(SongRoleRequirement.objects.filter(pk=other_requirement.pk).exists())
        self.role.refresh_from_db()
        self.assertTrue(self.role.is_active)

    def test_a_failure_mid_batch_applies_nothing(self):
        """A stale stamp rolls back every create/update/delete in the same Buffer, not just the offending row."""
        existing_role = RoleFactory()
        SongRoleRequirementFactory(song=self.song, role=existing_role, count=1)
        buffer = self._buffer(
            entries=[SongRoleRequirementEntry(role_id=self.role.pk, count=1)],
            updated_at=self.semester.updated_at,
        )
        self.semester.updated_at = timezone.now()
        self.semester.save(update_fields=['updated_at'])  # bump updated_at so the buffer's stamp goes stale

        with self.assertRaises(StaleSongRoleRequirementsError):
            apply_song_role_requirements(buffer, viewing_semester=self.semester)

        self.assertTrue(SongRoleRequirement.objects.filter(song=self.song, role=existing_role).exists())
        self.assertFalse(SongRoleRequirement.objects.filter(song=self.song, role=self.role).exists())

    def test_stale_semester_stamp_is_rejected_with_a_readable_message(self):
        """A stale stamp raises StaleSongRoleRequirementsError with reload-and-reapply guidance."""
        stale_stamp = self.semester.updated_at
        self.semester.updated_at = timezone.now()
        self.semester.save(update_fields=['updated_at'])
        buffer = self._buffer(
            entries=[SongRoleRequirementEntry(role_id=self.role.pk, count=1)],
            updated_at=stale_stamp,
        )

        with self.assertRaisesMessage(StaleSongRoleRequirementsError, 'reload and reapply'):
            apply_song_role_requirements(buffer, viewing_semester=self.semester)

    def test_wrong_viewing_semester_hard_fails(self):
        """A Buffer built against a different Semester than the one currently being viewed is rejected outright."""
        other_semester = SemesterFactory()
        buffer = self._buffer(semester=other_semester)

        with self.assertRaises(WrongViewingSemesterError):
            apply_song_role_requirements(buffer, viewing_semester=self.semester)

    def test_stamp_bumps_on_success(self):
        """A successful apply advances the Semester's updated_at, so a stale re-save is rejected next time."""
        before = self.semester.updated_at
        buffer = self._buffer(entries=[SongRoleRequirementEntry(role_id=self.role.pk, count=1)])

        apply_song_role_requirements(buffer, viewing_semester=self.semester)

        self.semester.refresh_from_db()
        self.assertGreater(self.semester.updated_at, before)
