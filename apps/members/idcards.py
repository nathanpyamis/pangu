"""
Member ID card PDFs. Card drawing lives in apps.idcards (shared with
candidate and staff cards); this module keeps the member-specific glue.
"""
from django.utils import timezone

from apps.idcards.builders import member_card, pdf_response

from .models import Member


def _layout(layout, per_page):
    if layout == "single":
        return "cr80"
    return "a4-8" if per_page == 8 else "a4-10"


def card_pdf_response(members, layout="single", per_page=10, filename="cards.pdf"):
    resp = pdf_response([member_card(m) for m in members], _layout(layout, per_page), filename)
    Member.objects.filter(pk__in=[m.pk for m in members]).update(
        id_card_printed=True, id_card_printed_at=timezone.now()
    )
    return resp
