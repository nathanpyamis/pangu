from django.urls import path

from apps.members.views import VerifyMemberView

from . import views

urlpatterns = [
    # Member cards (the original QR format, unchanged)
    path("<uuid:member_id>/", VerifyMemberView.as_view(), name="verify_member"),
    path("candidate/<uuid:pk>/", views.verify_candidate, name="verify_candidate"),
    path("candidate/<uuid:pk>/photo.jpg", views.candidate_photo, name="verify_candidate_photo"),
    path("staff/<uuid:pk>/", views.verify_staff, name="verify_staff"),
]
