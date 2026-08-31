from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('identity.urls')),
    path('', include('scheduling.urls')),
]
