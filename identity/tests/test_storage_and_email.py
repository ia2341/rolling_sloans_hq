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
    # DEBUG is pinned rather than inherited: EMAIL_BACKEND now depends on it,
    # so a developer's own DJANGO_DEBUG=True must not leak in and change what
    # these production-facing assertions are actually checking. SITE_URL comes
    # along because DEBUG=False requires it.
    'DJANGO_DEBUG': 'False',
    'SITE_URL': 'https://example.com',
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
    @classmethod
    def setUpClass(cls):
        """Shell out once for the settings this whole class's tests read from."""
        super().setUpClass()
        cls.values = run_settings()

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


class DevEmailBackendTests(unittest.TestCase):
    """The local-dev escape from a live Resend key (issue #299)."""

    def test_console_backend_is_the_default_when_debug(self):
        """With DEBUG=True the invite email prints to the runserver terminal rather than calling Resend."""
        values = run_settings({'DJANGO_DEBUG': 'True'})

        self.assertEqual(
            values['EMAIL_BACKEND'],
            'django.core.mail.backends.console.EmailBackend',
        )

    def test_settings_load_when_debug_and_no_resend_key(self):
        """A fresh dev checkout with no RESEND_API_KEY at all must still boot."""
        values = run_settings({'DJANGO_DEBUG': 'True', 'RESEND_API_KEY': ''})

        self.assertEqual(
            values['EMAIL_BACKEND'],
            'django.core.mail.backends.console.EmailBackend',
        )

    def test_env_var_overrides_the_dev_default(self):
        """A dev holding a real key can opt back into sending for real."""
        values = run_settings({
            'DJANGO_DEBUG': 'True',
            'DJANGO_EMAIL_BACKEND': 'anymail.backends.resend.EmailBackend',
        })

        self.assertEqual(values['EMAIL_BACKEND'], 'anymail.backends.resend.EmailBackend')

    def test_env_var_cannot_override_production(self):
        """DJANGO_EMAIL_BACKEND is ignored when DEBUG=False, so a stray host env var can't swallow a real invite."""
        values = run_settings({
            'DJANGO_DEBUG': 'False',
            'DJANGO_EMAIL_BACKEND': 'django.core.mail.backends.console.EmailBackend',
        })

        self.assertEqual(values['EMAIL_BACKEND'], 'anymail.backends.resend.EmailBackend')

    def test_startup_fails_without_resend_key_when_not_debug(self):
        """Production must fail loudly rather than boot with no way to send an invite."""
        result = run_settings_subprocess({'DJANGO_DEBUG': 'False', 'RESEND_API_KEY': ''})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('RESEND_API_KEY', result.stderr)


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

    def test_documents_the_dev_email_backend_override(self):
        """.env.example must tell a developer the local-dev email option exists (issue #299)."""
        content = (BASE_DIR / '.env.example').read_text()
        self.assertIn('DJANGO_EMAIL_BACKEND', content)
