"""Configuration checks for settings that must hold regardless of DEBUG.

Settings are read once at process startup, so DEBUG-dependent behavior is
exercised by spawning a subprocess with a controlled environment rather than
mutating django.conf.settings in-process.
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
    'SITE_URL': 'https://example.com',
}

PRINT_SETTINGS_SCRIPT = """
import django
django.setup()
import json
from django.conf import settings
print(json.dumps({
    'DEBUG': settings.DEBUG,
    'SECURE_SSL_REDIRECT': getattr(settings, 'SECURE_SSL_REDIRECT', False),
    'SESSION_COOKIE_SECURE': getattr(settings, 'SESSION_COOKIE_SECURE', False),
    'CSRF_COOKIE_SECURE': getattr(settings, 'CSRF_COOKIE_SECURE', False),
    'SECURE_HSTS_SECONDS': getattr(settings, 'SECURE_HSTS_SECONDS', 0),
    'DATABASE_OPTIONS': settings.DATABASES['default'].get('OPTIONS', {}),
}))
"""


def run_settings_subprocess(debug_value, env_overrides=None):
    """
    Run the Django settings module in a fresh process with the specified debug setting and environment overrides.
    
    Parameters:
        debug_value: Value assigned to `DJANGO_DEBUG`.
        env_overrides: Optional environment values that override the shared test environment.
    
    Returns:
        The completed subprocess result, including its exit status, standard output, and standard error.
    """
    env = os.environ.copy()
    env.update(BASE_ENV)
    env.update(env_overrides or {})
    env['DJANGO_DEBUG'] = debug_value
    env['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    return subprocess.run(
        [sys.executable, '-c', PRINT_SETTINGS_SCRIPT],
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def load_settings_with_debug(debug_value):
    """
    Load Django settings for the specified debug mode.
    
    Parameters:
        debug_value: The value assigned to DJANGO_DEBUG.
    
    Returns:
        dict: The settings printed by the subprocess.
    
    """
    result = run_settings_subprocess(debug_value)
    result.check_returncode()
    return json.loads(result.stdout)


class ProductionSecuritySettingsTests(unittest.TestCase):
    def test_tls_settings_enabled_when_debug_false(self):
        values = load_settings_with_debug('False')

        self.assertIs(values['DEBUG'], False)
        self.assertIs(values['SECURE_SSL_REDIRECT'], True)
        self.assertIs(values['SESSION_COOKIE_SECURE'], True)
        self.assertIs(values['CSRF_COOKIE_SECURE'], True)
        self.assertGreater(values['SECURE_HSTS_SECONDS'], 0)

    def test_database_connection_requires_ssl(self):
        values = load_settings_with_debug('False')

        self.assertEqual(values['DATABASE_OPTIONS'].get('sslmode'), 'require')

    def test_startup_fails_without_site_url(self):
        """In production, settings must fail to load rather than silently fall back to the localhost SITE_URL default."""
        result = run_settings_subprocess('False', env_overrides={'SITE_URL': ''})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SITE_URL', result.stderr)


class DevSettingsTests(unittest.TestCase):
    def test_tls_settings_not_forced_when_debug_true(self):
        values = load_settings_with_debug('True')

        self.assertIs(values['DEBUG'], True)
        self.assertIs(values['SECURE_SSL_REDIRECT'], False)
        self.assertIs(values['SESSION_COOKIE_SECURE'], False)
        self.assertIs(values['CSRF_COOKIE_SECURE'], False)
        self.assertEqual(values['SECURE_HSTS_SECONDS'], 0)

    def test_localhost_fallback_used_without_site_url(self):
        """In dev, settings must still load successfully without SITE_URL, falling back to the localhost default."""
        result = run_settings_subprocess('True', env_overrides={'SITE_URL': ''})

        result.check_returncode()


class EnvExampleTests(unittest.TestCase):
    """No value in .env.example should look like a real credential."""

    PLACEHOLDER_MARKERS = (
        'changeme', 'localhost', '127.0.0.1', 'True', 'False',
        'user:password@host', 'dbname',
    )

    def test_every_value_is_a_placeholder(self):
        content = (BASE_DIR / '.env.example').read_text()

        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            with self.subTest(key=key):
                self.assertTrue(
                    any(marker in value for marker in self.PLACEHOLDER_MARKERS),
                    f"{key} does not look like a placeholder value: {value!r}",
                )

    def test_declares_every_required_variable(self):
        content = (BASE_DIR / '.env.example').read_text()
        required_vars = [
            'DJANGO_SECRET_KEY',
            'DATABASE_URL',
            'AWS_ACCESS_KEY_ID',
            'AWS_SECRET_ACCESS_KEY',
            'AWS_STORAGE_BUCKET_NAME',
            'AWS_S3_ENDPOINT_URL',
            'RESEND_API_KEY',
            'DJANGO_ALLOWED_HOSTS',
            'DJANGO_DEBUG',
        ]
        for var in required_vars:
            with self.subTest(var=var):
                self.assertIn(f'{var}=', content)
