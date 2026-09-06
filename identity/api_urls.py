"""`identity`'s `/api/` routes (issue #326), included by `config/api_urls.py`.

Issue #333 adds the Profile page's change-password endpoint — the one auth
act performed with a session, so it's the one piece of `identity`'s auth
model that lives in the SPA rather than server-rendered outside it (#327).
"""

from django.urls import path

from identity import api_views

urlpatterns = [
    path('password/', api_views.PasswordChangeApiView.as_view(), name='api-password-change'),
]
