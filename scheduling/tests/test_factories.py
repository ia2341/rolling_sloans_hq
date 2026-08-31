import unittest

from scheduling.factories import RoleFactory, SemesterFactory


class SemesterFactoryTests(unittest.TestCase):
    def test_builds_semester_with_synthetic_data(self):
        semester = SemesterFactory.build()

        self.assertTrue(semester.name)
        self.assertGreater(semester.default_rehearsal_duration_minutes, 0)

    def test_generates_distinct_names_per_instance(self):
        first = SemesterFactory.build()
        second = SemesterFactory.build()

        self.assertNotEqual(first.name, second.name)


class RoleFactoryTests(unittest.TestCase):
    def test_builds_active_role_by_default(self):
        role = RoleFactory.build()

        self.assertTrue(role.name)
        self.assertTrue(role.is_active)

    def test_generates_distinct_names_per_instance(self):
        first = RoleFactory.build()
        second = RoleFactory.build()

        self.assertNotEqual(first.name, second.name)
