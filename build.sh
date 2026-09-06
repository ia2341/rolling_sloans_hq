#!/usr/bin/env bash
#
# Deploy build. The host (Render) runs this as its build command; it is the
# only place collectstatic happens, and without it WhiteNoise has nothing to
# serve and the site ships with no CSS.
set -o errexit

pip install -r requirements.txt

# The Vite build has to exist on disk before collectstatic walks
# STATICFILES_DIRS (issue #325) — otherwise the site ships with no
# JavaScript at all. `set -o errexit` means a failed frontend build aborts
# the deploy here, before migrations run.
npm ci --prefix frontend
npm run build --prefix frontend

python manage.py collectstatic --no-input
python manage.py migrate
