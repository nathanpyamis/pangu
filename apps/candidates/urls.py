from django.urls import path

from . import views

app_name = "candidates"

urlpatterns = [
    path("apply/", views.apply, name="apply"),
    path("apply/thank-you/", views.apply_done, name="apply_done"),
    path("status/", views.status, name="status"),
]
