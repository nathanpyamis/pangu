from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("join/", views.join, name="join"),
    path("contact/", views.contact, name="contact"),
    path("news/<slug:slug>/", views.news_detail, name="news_detail"),
]
