from django.contrib import admin
from django.urls import include, path

from config.views import SpaIndexView

# Route ordering here is load-bearing (issue #325): each of the first
# several patterns claims one namespace, and the catch-all at the end picks
# up anything none of them claimed. Reordering any of this changes which
# paths reach the SPA shell instead of their intended handler.
urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('identity.urls')),
    # Ahead of the catch-all and the existing app routes below (issue #326):
    # includes each app's own /api/ URLConf and ends in its own terminal
    # JSON-404 route, which is what stops a mistyped API path from falling
    # through to the SPA shell and getting an HTML 200 where the client
    # expected JSON.
    path('api/', include('config.api_urls')),
    # No explicit /static/ entry is needed: `runserver` serves STATICFILES_DIRS
    # itself when DEBUG is True, and WhiteNoise's middleware serves STATIC_ROOT
    # in production — neither goes through this URLconf.
    path('', include('scheduling.urls')),
    # Catch-all, deliberately last: every path not claimed above hands the
    # SPA its shell, which renders its own 404 client-side (issue #325).
    # This is what lets the old Django portal and the in-progress SPA
    # coexist on this branch with no feature flag — the catch-all only ever
    # picks up paths the old app never claimed.
    path('<path:unmatched_path>', SpaIndexView.as_view(), name='spa-index'),
]
