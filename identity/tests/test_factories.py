import unittest

from identity.factories import PersonFactory


class PersonFactoryTests(unittest.TestCase):
    """Demonstrates the factory_boy + Faker convention (see CONTRIBUTING.md)."""

    def test_builds_person_with_synthetic_data(self):
        person = PersonFactory.build()

        self.assertTrue(person.name)
        self.assertTrue(
            person.email.endswith('@example.com'),
            f"expected an @example.com email, got {person.email!r}",
        )

    def test_email_domain_is_always_example_com(self):
        for _ in range(50):
            person = PersonFactory.build()
            self.assertTrue(
                person.email.endswith('@example.com'),
                f"expected an @example.com email, got {person.email!r}",
            )

    def test_generates_distinct_data_per_instance(self):
        first = PersonFactory.build()
        second = PersonFactory.build()

        self.assertNotEqual(first.email, second.email)
