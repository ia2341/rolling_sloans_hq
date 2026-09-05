"""A tiny URLConf used only by `config/tests/test_api_view.py`, swapped in via `ROOT_URLCONF`.

Exists because `ApiView`/`AdminApiView` behaviour is generic to every
`/api/` endpoint and has no concrete endpoint of its own yet (every real
one is a later ticket, #330-#340) — these two dummy views exercise the
base classes' dispatch chain without depending on any endpoint this ticket
doesn't own.
"""

from django.urls import path
from django.views import View

from config.views import AdminApiView, ApiView


class DummyApiView(ApiView, View):
    """A minimal `/api/` read endpoint, used only to exercise `ApiView`'s dispatch chain in tests."""

    def get(self, request):
        """Return the read envelope with a fixed `data` payload."""
        return self.read_response(request, {'ok': True})

    def post(self, request):
        """Parse the request body as JSON and echo it back in the read envelope, to exercise `parse_json_body()`."""
        payload = self.parse_json_body(request)
        return self.read_response(request, payload)


class DummyAdminApiView(AdminApiView, View):
    """A minimal admin-only `/api/` read endpoint, used only to exercise `AdminApiView`'s dispatch chain in tests."""

    def get(self, request):
        """Return the read envelope with a fixed `data` payload."""
        return self.read_response(request, {'ok': True})


urlpatterns = [
    path('member/', DummyApiView.as_view(), name='dummy-api-member'),
    path('admin/', DummyAdminApiView.as_view(), name='dummy-api-admin'),
]
