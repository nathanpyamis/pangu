from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("", views.staff_list, name="list"),
    path("<int:user_id>/", views.staff_detail, name="detail"),
    path("<int:user_id>/card.pdf", views.staff_card_pdf, name="card"),
    path("cards.pdf", views.staff_cards_batch, name="cards_batch"),
]
