"""
Django glue for the three card kinds. The drawing itself is in cardpdf.py.

    member_card(member)          -> card dict
    candidate_card(application)  -> card dict
    staff_card(profile)          -> card dict
    pdf_response(cards, ...)     -> HttpResponse (inline PDF)
"""
from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.utils import timezone

from .cardpdf import build_pdf

LAYOUTS = {
    "cr80": ("single", 10),
    "a4-10": ("batch", 10),
    "a4-8": ("batch", 8),
}


def _base_url():
    return settings.PUBLIC_BASE_URL.rstrip("/")


def _read(field):
    if not field:
        return None
    try:
        with field.open("rb") as f:
            return f.read()
    except (FileNotFoundError, OSError, ValueError):
        return None


def _today():
    return timezone.localdate().strftime("%d %b %Y")


def member_card(member):
    return {
        "kind": "MEMBER",
        "name": member.full_name,
        "number": member.membership_number or "",
        "line1_label": "Electorate", "line1": member.electorate.name,
        "line2_label": "Province", "line2": member.electorate.province.name,
        "issued": _today(),
        "verify_url": f"{_base_url()}/verify/{member.pk}/",
        "photo": _read(member.photo),
    }


def candidate_card(app):
    return {
        "kind": "CANDIDATE",
        "name": app.full_name,
        "number": app.candidate_number or "",
        "line1_label": "Seat", "line1": app.electorate.name,
        "line2_label": "Province", "line2": app.electorate.province.name,
        "issued": _today(),
        "verify_url": f"{_base_url()}/verify/candidate/{app.pk}/",
        "photo": _read(app.photo),
    }


def staff_card(profile):
    return {
        "kind": "STAFF",
        "name": profile.display_name,
        "number": profile.staff_number or "",
        "line1_label": "Role", "line1": profile.user.get_role_display(),
        "line2_label": "Area", "line2": profile.area,
        "issued": _today(),
        "valid_until": profile.valid_until.strftime("%d %b %Y") if profile.valid_until else "",
        "verify_url": f"{_base_url()}/verify/staff/{profile.pk}/",
        "photo": _read(profile.photo),
    }


def _logo_bytes():
    from apps.cms.models import PartyProfile
    try:
        party = PartyProfile.load()
        data = _read(party.logo)
        if data:
            return data, party.name
        name = party.name
    except Exception:
        name = "Pangu Pati"
    path = finders.find("site/img/pangu-logo.png")
    if path:
        with open(path, "rb") as f:
            return f.read(), name
    return None, name


def pdf_response(cards, layout="cr80", filename="cards.pdf"):
    mode, per_page = LAYOUTS.get(layout, LAYOUTS["cr80"])
    logo, party_name = _logo_bytes()
    pdf = build_pdf(cards, layout=mode, per_page=per_page,
                    title=f"{party_name} ID cards", party_name=party_name, logo_bytes=logo)
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{filename}"'
    return resp
