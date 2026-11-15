from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.accounts.field_access import FieldLoginView, FieldRefreshView
from apps.geo.views import ElectorateLookupView

admin.site.site_header = "Pangu Pati administration"
admin.site.site_title = "Pangu Pati admin"
admin.site.index_title = "Party records"

urlpatterns = [
    path("admin/", admin.site.urls),

    # --- API (field agent PWA) ---
    path("api/auth/token/", FieldLoginView.as_view(), name="token_obtain"),
    path("api/auth/token/refresh/", FieldRefreshView.as_view(), name="token_refresh"),
    path("api/geo/electorates/", ElectorateLookupView.as_view(), name="electorate_lookup"),
    path("api/members/", include("apps.members.api_urls")),

    # --- Staff portal: login, executive dashboard, databases (session auth) ---
    path("portal/", include("apps.portal.urls")),
    path("portal/members/", include("apps.members.portal_urls")),
    path("portal/candidates/", include("apps.candidates.portal_urls")),
    path("portal/staff/", include("apps.idcards.staff_urls")),

    # --- Public candidate application ---
    path("candidates/", include("apps.candidates.urls")),

    # --- Field agent PWA shell ---
    path("agent/", include("apps.pwa.urls")),

    # --- Public card verification (QR targets) ---
    path("verify/", include("apps.idcards.verify_urls")),

    # --- Public party website (Kitzu-style one-pager) ---
    path("", include("apps.cms.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
