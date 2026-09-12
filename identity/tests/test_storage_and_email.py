"""Config checks for the R2 storage backend (issue #19).

Settings are read once at process startup, so these are exercised the same
way as the production security settings: spawn a subprocess with a
controlled environment rather than mutating django.conf.settings in-process.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

BASE_ENV = {
    'DJANGO_SECRET_KEY': 'test-secret-key-not-used-anywhere-real',
    'DJANGO_DEBUG': 'False',
    'DJANGO_ALLOWED_HOSTS': 'example.com',
    'DATABASE_URL': 'postgres://user:password@dbhost:5432/rolling_sloans?sslmode=require',
    'AWS_ACCESS_KEY_ID': 'test-access-key-id',
    'AWS_SECRET_ACCESS_KEY': 'test-secret-access-key',
    'AWS_STORAGE_BUCKET_NAME': 'test-bucket',
    'AWS_S3_ENDPOINT_URL': 'https://test-account.r2.cloudflarestorage.com',
}

PRINT_SETTINGS_SCRIPT = """
import django
django.setup()
import json
from django.conf import settings
print(json.dumps({
    'STORAGES': settings.STORAGES,
    'AWS_ACCESS_KEY_ID': settings.AWS_ACCESS_KEY_ID,
    'AWS_SECRET_ACCESS_KEY': settings.AWS_SECRET_ACCESS_KEY,
    'AWS_STORAGE_BUCKET_NAME': settings.AWS_STORAGE_BUCKET_NAME,
    'AWS_S3_ENDPOINT_URL': settings.AWS_S3_ENDPOINT_URL,
    'AWS_DEFAULT_ACL': getattr(settings, 'AWS_DEFAULT_ACL', None),
    'AWS_QUERYSTRING_AUTH': getattr(settings, 'AWS_QUERYSTRING_AUTH', None),
    'INSTALLED_APPS': settings.INSTALLED_APPS,
}))
"""


def run_settings_subprocess(env_overrides=None):
    """
    Load the settings module in a fresh process and capture the printed settings.

    Parameters:
        env_overrides: Optional environment values that override the shared
            test environment. Pass an empty string to model an unconfigured
            variable — popping the key instead would let django-environ
            backfill it from the developer's own .env.

    Returns:
        The completed subprocess result, including exit status, stdout and stderr.
    """
    env = os.environ.copy()
    env.update(BASE_ENV)
    env.update(env_overrides or {})
    env['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    return subprocess.run(
        [sys.executable, '-c', PRINT_SETTINGS_SCRIPT],
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def run_settings(env_overrides=None):
    """Load settings in a subprocess that must succeed, and return the printed values."""
    result = run_settings_subprocess(env_overrides)
    result.check_returncode()
    return json.loads(result.stdout)


class StorageBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Shell out once for the settings this whole class's tests read from."""
        super().setUpClass()
        cls.values = run_settings()

    def test_storages_app_installed(self):
        self.assertIn('storages', self.values['INSTALLED_APPS'])

    def test_default_file_storage_is_s3_backend(self):
        backend = self.values['STORAGES']['default']['BACKEND']
        self.assertEqual(backend, 'storages.backends.s3.S3Storage')

    def test_r2_credentials_and_bucket_come_from_env(self):
        self.assertEqual(self.values['AWS_ACCESS_KEY_ID'], 'test-access-key-id')
        self.assertEqual(self.values['AWS_SECRET_ACCESS_KEY'], 'test-secret-access-key')
        self.assertEqual(self.values['AWS_STORAGE_BUCKET_NAME'], 'test-bucket')
        self.assertEqual(
            self.values['AWS_S3_ENDPOINT_URL'],
            'https://test-account.r2.cloudflarestorage.com',
        )

    def test_bucket_is_not_public(self):
        self.assertNotEqual(self.values['AWS_DEFAULT_ACL'], 'public-read')

    def test_urls_are_not_signed_query_string_by_default(self):
        # Playback/upload URLs are explicitly presigned per the storage-access
        # ADR (docs/adr/0004), not left to django-storages' default query-auth
        # signing, which this ticket does not configure.
        self.assertIsNone(self.values['AWS_QUERYSTRING_AUTH'])
