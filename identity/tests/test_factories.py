import unittest

from identity.factories import PersonFactory


class PersonFactoryTests(unittest.TestCase):
    """Demonstrates the factory_boy + Faker convention (see CONTRIBUTING.md).

    identity.migrations is deliberately empty until the Identity & Auth spec
    designs the real Person model (see test_person.py), so this uses
    .build() rather than .create() to avoid requiring a database table.
    """

    def test_builds_person_with_synthetic_data(self):
        person = PersonFactory.build()

        self.assertTrue(person.username)
        self.assertTrue(person.first_name)
        self.assertTrue(person.last_name)
        self.assertTrue(
            person.email.endswith(('@example.com', '@example.org', '@example.net')),
            f"expected a synthetic @example.* email, got {person.email!r}",
        )

    def test_generates_distinct_data_per_instance(self):
        first = PersonFactory.build()
        second = PersonFactory.build()

        self.assertNotEqual(first.username, second.username)
