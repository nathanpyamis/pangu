from django.urls import path

from . import views

app_name = "candidate_db"

urlpatterns = [
    path("", views.database, name="database"),
    path("cards.pdf", views.cards_batch, name="cards_batch"),
    path("<uuid:pk>/", views.detail, name="detail"),
    path("<uuid:pk>/file/<str:field>/", views.document, name="document"),
    path("<uuid:pk>/letter.pdf", views.letter, name="letter"),
    path("<uuid:pk>/card.pdf", views.card, name="card"),
]
