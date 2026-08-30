"""Smoke test that `manage.py check --deploy` passes under a production-like
environment, per issue #20's config smoke-test requirement.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

PRODUCTION_ENV = {
    'DJANGO_SECRET_KEY': 'test-secret-key-not-used-anywhere-real',
    'DJANGO_DEBUG': 'False',
    'DJANGO_ALLOWED_HOSTS': 'example.com',
    'DATABASE_URL': 'postgres://user:password@dbhost:5432/rolling_sloans?sslmode=require',
    'AWS_ACCESS_KEY_ID': 'test-access-key',
    'AWS_SECRET_ACCESS_KEY': 'test-secret-key',
    'AWS_STORAGE_BUCKET_NAME': 'test-bucket',
    'AWS_S3_ENDPOINT_URL': 'https://test.r2.cloudflarestorage.com',
    'RESEND_API_KEY': 'test-resend-key',
    'CLUB_EMAIL_FROM': 'test@example.com',
}


class DeployCheckTests(unittest.TestCase):
    def test_check_deploy_passes_with_production_env(self):
        env = os.environ.copy()
        env.update(PRODUCTION_ENV)
        env['DJANGO_SETTINGS_MODULE'] = 'config.settings'

        result = subprocess.run(
            [sys.executable, 'manage.py', 'check', '--deploy'],
            cwd=BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            f"manage.py check --deploy failed:\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )
