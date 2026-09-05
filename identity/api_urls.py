"""`identity`'s `/api/` routes (issue #326), included by `config/api_urls.py`.

Empty for now: the sign-in page's `/api/` endpoint and the rest of the
auth model on the SPA side are #327's ticket. This module exists so that
work adds routes here rather than deciding where `identity`'s API routes
live.
"""

urlpatterns = []
