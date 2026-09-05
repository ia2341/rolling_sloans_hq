"""`identity/serializers.py`'s exact key-set (issue #326)."""

from django.test import TestCase

from identity.factories import PersonFactory
from identity.serializers import serialize_viewer


class SerializeViewerTests(TestCase):
    """`serialize_viewer()` emits exactly `id`, `name`, `email`, `is_admin`."""

    def test_exact_key_set(self):
        """The emitted dict has exactly the four documented keys — no more, no fewer."""
        person = PersonFactory()

        payload = serialize_viewer(person)

        self.assertEqual(set(payload), {'id', 'name', 'email', 'is_admin'})

    def test_values(self):
        """Each key carries the matching field off the Person, with is_admin as the #307 admin flag."""
        person = PersonFactory(is_admin=True)

        payload = serialize_viewer(person)

        self.assertEqual(payload['id'], person.pk)
        self.assertEqual(payload['name'], person.name)
        self.assertEqual(payload['email'], person.email)
        self.assertIs(payload['is_admin'], True)
