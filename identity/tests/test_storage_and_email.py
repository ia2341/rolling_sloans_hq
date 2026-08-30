"""Config checks for the R2 storage and Resend email backends (issue #19).

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
    'DJANGO_ALLOWED_HOSTS': 'example.com',
    'DATABASE_URL': 'postgres://user:password@dbhost:5432/rolling_sloans?sslmode=require',
    'AWS_ACCESS_KEY_ID': 'test-access-key-id',
    'AWS_SECRET_ACCESS_KEY': 'test-secret-access-key',
    'AWS_STORAGE_BUCKET_NAME': 'test-bucket',
    'AWS_S3_ENDPOINT_URL': 'https://test-account.r2.cloudflarestorage.com',
    'RESEND_API_KEY': 'test-resend-api-key',
    'CLUB_EMAIL_FROM': 'noreply@example.com',
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
    'EMAIL_BACKEND': settings.EMAIL_BACKEND,
    'ANYMAIL': settings.ANYMAIL,
    'DEFAULT_FROM_EMAIL': settings.DEFAULT_FROM_EMAIL,
    'INSTALLED_APPS': settings.INSTALLED_APPS,
}))
"""


def run_settings():
    env = os.environ.copy()
    env.update(BASE_ENV)
    env['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    result = subprocess.run(
        [sys.executable, '-c', PRINT_SETTINGS_SCRIPT],
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


class StorageBackendTests(unittest.TestCase):
    def setUp(self):
        self.values = run_settings()

    def test_storages_and_anymail_apps_installed(self):
        self.assertIn('storages', self.values['INSTALLED_APPS'])
        self.assertIn('anymail', self.values['INSTALLED_APPS'])

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


class EmailBackendTests(unittest.TestCase):
    def setUp(self):
        self.values = run_settings()

    def test_email_backend_is_anymail(self):
        self.assertEqual(
            self.values['EMAIL_BACKEND'],
            'anymail.backends.resend.EmailBackend',
        )

    def test_resend_api_key_comes_from_env(self):
        self.assertEqual(
            self.values['ANYMAIL'].get('RESEND_API_KEY'),
            'test-resend-api-key',
        )

    def test_default_from_email_comes_from_env_not_hardcoded(self):
        self.assertEqual(self.values['DEFAULT_FROM_EMAIL'], 'noreply@example.com')


class StorageEmailEnvExampleTests(unittest.TestCase):
    def test_declares_club_email_from(self):
        content = (BASE_DIR / '.env.example').read_text()
        self.assertIn('CLUB_EMAIL_FROM=', content)

    def test_club_email_from_is_a_placeholder(self):
        content = (BASE_DIR / '.env.example').read_text()
        for line in content.splitlines():
            line = line.strip()
            if line.startswith('CLUB_EMAIL_FROM='):
                _, _, value = line.partition('=')
                self.assertNotIn('@rollingsloans', value)
                return
        self.fail('CLUB_EMAIL_FROM not found in .env.example')
