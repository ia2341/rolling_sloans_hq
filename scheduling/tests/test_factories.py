import unittest

from scheduling.factories import RoleFactory, SemesterFactory, SongFactory


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
