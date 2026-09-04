"""
Django settings for config project.

Settings are sourced from environment variables (loaded from a local .env
file via django-environ in development; injected directly by the host in
production). No setting here is ever a literal secret.
"""

import sys
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse_lazy

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('DJANGO_SECRET_KEY')

DEBUG = env('DJANGO_DEBUG')

ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=[])


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'storages',
    'anymail',
    'identity',
    'scheduling',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Serves everything under STATIC_ROOT in production, where nothing else
    # is fronting the app. It has to sit directly after SecurityMiddleware
    # so a static response still gets the security headers but skips the
    # session, auth and CSRF work it has no use for.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # The non-live Semester banner renders from the shared nav shell
                # on every page, so it can't be per-view context (issue #169).
                'scheduling.context_processors.semester_banner',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# DATABASE_URL is expected to include sslmode=require (enforced against
# Neon Postgres); django-environ parses the connection string as-is, so the
# query string is what makes SSL mandatory rather than optional.

DATABASES = {
    'default': env.db('DATABASE_URL'),
}


# Custom user model.
#
# AUTH_USER_MODEL must be set correctly before the first migration is ever
# run — changing it later requires a full migration reset. `identity.Person`
# is a placeholder pointed at by this setting now; its real fields and
# behavior are designed in the Identity & Auth spec (issue #5).
AUTH_USER_MODEL = 'identity.Person'


# Auth entry/exit points (issue #296).
#
# LOGIN_URL is pinned explicitly rather than left to Django's default
# ('/accounts/login/'), which happens to match this project's login route
# today only by coincidence — an unrelated rename of that route would
# otherwise silently break every LoginRequiredMixin bounce. LOGIN_REDIRECT_URL
# is Django's fallback destination for a next-less login (no ?next= in the
# querystring); left unset it defaults to '/accounts/profile/', a route this
# project doesn't have, so every next-less login — notably a brand-new
# member's very first login right after setting their password — 404ed.
# Both are derived from route names, via reverse_lazy (not reverse: this
# module is imported before the URLconf is loaded, so a module-scope
# reverse() call would raise), so a route rename keeps these honest instead
# of drifting from a hardcoded URL literal.
LOGIN_URL = reverse_lazy('identity:login')
LOGIN_REDIRECT_URL = reverse_lazy('scheduling:overview')


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Under `manage.py test`, swap in a much cheaper hasher: the default PBKDF2
# hasher is deliberately slow (that's the point in production), but the test
# suite creates and logs in hundreds of Persons, so its iteration count adds
# real minutes to the run. MD5 is unusable for production but fine for
# throwaway test-database rows.
if 'test' in sys.argv:
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


# Sessions: a 30-day sliding expiry, so members aren't forced to re-login
# mid-semester as long as they keep using the site. No JWT, no third-party
# session library — Django's built-in session framework covers this.
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 days
SESSION_SAVE_EVERY_REQUEST = True


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = 'static/'

# The top-level static/ directory holds the vendored admin UI stack (HTMX,
# Alpine, Pico.css, SortableJS — each pinned by version in its filename) and
# the hand-written override sheet. Per-app static/ directories are still
# picked up by AppDirectoriesFinder; this only adds the project-wide one.
STATICFILES_DIRS = [BASE_DIR / 'static']

# collectstatic target. Not committed; the deploy build regenerates it (see
# build.sh), and WhiteNoise serves it from there.
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Object storage (Cloudflare R2, S3-compatible), via django-storages.
#
# The bucket is private: no AWS_DEFAULT_ACL='public-read', and
# AWS_QUERYSTRING_AUTH is left unset here, so django-storages falls back to
# its own default (True) rather than us ever setting it False and handing
# out unsigned public URLs. Actual upload/playback access
# uses short-lived presigned URLs issued explicitly per the storage-access
# ADR (docs/adr/0004) — that presigning logic belongs to the Recordings
# feature, not this base configuration.

STORAGES = {
    'default': {
        'BACKEND': 'storages.backends.s3.S3Storage',
    },
    # WhiteNoise's non-manifest backend: it gzips/brotlis each collected file
    # alongside the original, but does not rewrite filenames into content
    # hashes. Hashing is deliberately skipped — the vendored libraries already
    # carry their version in the filename, and a manifest backend makes every
    # {% static %} call fail until collectstatic has run, which would mean
    # running it before the test suite for no gain here.
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}

AWS_ACCESS_KEY_ID = env('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = env('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = env('AWS_STORAGE_BUCKET_NAME')
AWS_S3_ENDPOINT_URL = env('AWS_S3_ENDPOINT_URL')


# Outbound email (Resend), via django-anymail. CLUB_EMAIL_FROM is the one
# address the club sends from; it's an env var so it's never hardcoded.

EMAIL_BACKEND = 'anymail.backends.resend.EmailBackend'
ANYMAIL = {
    'RESEND_API_KEY': env('RESEND_API_KEY'),
}
DEFAULT_FROM_EMAIL = env('CLUB_EMAIL_FROM')

# Base URL used to build absolute links (e.g. invite set-password links) in
# contexts with no request object, like a signal or admin action. The
# localhost fallback is a dev-only convenience; in production (DEBUG=False)
# it must be set explicitly, since silently falling back there would build
# invite/reset links members can't actually use.
SITE_URL = env('SITE_URL', default=None)
if not DEBUG and not SITE_URL:
    raise ImproperlyConfigured(
        'SITE_URL must be set via the environment when DJANGO_DEBUG is False.'
    )
SITE_URL = SITE_URL or 'http://localhost:8000'

# Spotify Client Credentials Flow, for the public-playlist import
# (scheduling.spotify). Optional: absent locally, the import reports itself
# unavailable instead of raising, so a fresh checkout isn't broken by it.
SPOTIFY_CLIENT_ID = env('SPOTIFY_CLIENT_ID', default=None)
SPOTIFY_CLIENT_SECRET = env('SPOTIFY_CLIENT_SECRET', default=None)


# Production security settings ("TLS everywhere").
#
# Local dev runs with DEBUG=True over plain HTTP and must not be broken by
# these; they only activate in the DEBUG=False (production) branch.
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
