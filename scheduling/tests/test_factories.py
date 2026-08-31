import unittest

from scheduling.factories import (
    RehearsalFactory,
    RoleFactory,
    SemesterFactory,
    SongFactory,
    SongRoleAssignmentFactory,
    SongRoleRequirementFactory,
)


class SemesterFactoryTests(unittest.TestCase):
    def test_builds_semester_with_synthetic_data(self):
        semester = SemesterFactory.build()

        self.assertTrue(semester.name)
        self.assertGreater(semester.default_rehearsal_duration_minutes, 0)


class RoleFactoryTests(unittest.TestCase):
    def test_builds_active_role_by_default(self):
        role = RoleFactory.build()

        self.assertTrue(role.name)
        self.assertTrue(role.is_active)

    def test_generates_distinct_names_per_instance(self):
        first = RoleFactory.build()
        second = RoleFactory.build()

        self.assertNotEqual(first.name, second.name)


class SongFactoryTests(unittest.TestCase):
    def test_builds_song_with_synthetic_data(self):
        """SongFactory builds a Song with a synthetic title, artist, positive length, and position."""
        song = SongFactory.build()

        self.assertTrue(song.title)
        self.assertTrue(song.artist)
        self.assertGreater(song.length.total_seconds(), 0)
        self.assertGreater(song.position, 0)

    def test_generates_distinct_titles_and_positions_per_instance(self):
        """Successive SongFactory builds get distinct titles and positions."""
        first = SongFactory.build()
        second = SongFactory.build()

        self.assertNotEqual(first.title, second.title)
        self.assertNotEqual(first.position, second.position)


class SongRoleRequirementFactoryTests(unittest.TestCase):
    def test_builds_requirement_with_synthetic_data(self):
        """SongRoleRequirementFactory builds a requirement with a Song, Role, and positive count."""
        requirement = SongRoleRequirementFactory.build()

        self.assertIsNotNone(requirement.song)
        self.assertIsNotNone(requirement.role)
        self.assertGreater(requirement.count, 0)


class SongRoleAssignmentFactoryTests(unittest.TestCase):
    def test_builds_assignment_with_synthetic_data(self):
        """SongRoleAssignmentFactory builds an assignment with a Song, Role, and Person."""
        assignment = SongRoleAssignmentFactory.build()

        self.assertIsNotNone(assignment.song)
        self.assertIsNotNone(assignment.role)
        self.assertIsNotNone(assignment.person)


class RehearsalFactoryTests(unittest.TestCase):
    def test_builds_rehearsal_with_synthetic_data(self):
        """RehearsalFactory builds a Rehearsal with a semester, date, and start time."""
        rehearsal = RehearsalFactory.build()

        self.assertIsNotNone(rehearsal.semester)
        self.assertIsNotNone(rehearsal.date)
        self.assertIsNotNone(rehearsal.start_time)

    def test_leaves_grace_periods_and_end_time_unset_for_save_time_defaulting(self):
        """The factory leaves grace periods/end_time as None so Rehearsal.save() defaults them."""
        rehearsal = RehearsalFactory.build()

        self.assertIsNone(rehearsal.setup_grace_minutes)
        self.assertIsNone(rehearsal.teardown_grace_minutes)
        self.assertIsNone(rehearsal.end_time)
