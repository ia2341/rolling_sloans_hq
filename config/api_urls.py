"""The project-level `/api/` URLConf (issue #326), included at `api/` ahead of the SPA catch-all.

Includes each app's own `/api/` URLConf and ends with a terminal
catch-all returning a JSON 404 for any path neither one claimed. That
catch-all must be declared last across *both* apps, which is why it lives
here rather than in either app's own `api_urls.py` — a per-app catch-all
would only ever see its own app's un-matched paths, not the other app's.

Without this terminal route, a mistyped or renamed `/api/` path would fall
through to #325's SPA catch-all and get back an HTML 200 where the client
expected JSON. The terminal view inherits `ApiView`, so an anonymous typo
still gets the same 401 every other `/api/` path gives, and the structural
test in `config/tests/test_url_conf_structure.py` needs no allowlist entry
for it.
"""

from django.http import JsonResponse
from django.urls import include, path
from django.views import View

from config.views import ApiView


class ApiNotFoundView(ApiView, View):
    """Answers any method on an unclaimed `/api/` path with the documented JSON 404 (issue #326)."""

    def _not_found(self, request, *args, **kwargs):
        """Return the JSON 404 body for an unknown `/api/` path."""
        return JsonResponse({'error': 'not_found'}, status=404)

    get = _not_found
    post = _not_found
    put = _not_found
    patch = _not_found
    delete = _not_found


urlpatterns = [
    path('', include('scheduling.api_urls')),
    path('', include('identity.api_urls')),
    path('<path:unmatched_path>', ApiNotFoundView.as_view(), name='api-not-found'),
]
