import unittest
from pathlib import Path

from django.conf import settings


class AuthUserModelTests(unittest.TestCase):
    def test_auth_user_model_points_at_identity_person(self):
        self.assertEqual(settings.AUTH_USER_MODEL, 'identity.Person')

    def test_no_migrations_have_been_generated_yet(self):
        migrations_dir = Path(__file__).resolve().parent.parent / 'migrations'
        migration_files = [
            f for f in migrations_dir.glob('*.py') if f.name != '__init__.py'
        ]
        self.assertEqual(
            migration_files,
            [],
            "identity/migrations should stay empty until the Identity & Auth "
            "spec designs the real Person model.",
        )
