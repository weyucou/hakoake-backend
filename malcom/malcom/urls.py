"""malcom URL Configuration"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

# update displayed header/title
admin.site.site_header = settings.SITE_HEADER
admin.site.site_title = settings.SITE_TITLE

urlpatterns = [
    path("", include(("commons.urls", "commons"), namespace="commons")),
    path("", include(("houses.urls", "houses"), namespace="houses")),
    path("", include(("performers.urls", "performers"), namespace="performers")),
    path("admin/", admin.site.urls),
]
