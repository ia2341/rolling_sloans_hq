#!/usr/bin/env bash
#
# Deploy build. The host (Render) runs this as its build command; it is the
# only place collectstatic happens, and without it WhiteNoise has nothing to
# serve and the site ships with no CSS.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
