"""Deploy-time system check for the Vite build output (issue #325)."""

from django.conf import settings
from django.core.checks import Error, register


@register()
def spa_build_output_exists(app_configs, **kwargs):
    """Fail `manage.py check --deploy` when the Vite build is missing outside DEBUG.

    Without this, an out-of-order `build.sh` (npm build running after
    `collectstatic`, or not at all) would only surface as a raised
    `ImproperlyConfigured` the first time a browser hits the SPA route —
    too late for a deploy pipeline that should fail before that.
    """
    from config.spa import build_output_exists

    if settings.DEBUG or build_output_exists():
        return []
    return [
        Error(
            'The Vite build output is missing.',
            hint=(
                f'No manifest at {settings.FRONTEND_MANIFEST_PATH}. Run '
                '`npm ci && npm run build` inside frontend/ before deploying.'
            ),
            id='config.E001',
        )
    ]
