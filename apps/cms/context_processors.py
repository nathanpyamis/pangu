from django.db.utils import OperationalError, ProgrammingError
from django.templatetags.static import static

from .models import PartyProfile


def party(request):
    """`party`, `party_logo` and `party_header` in every template (site, portal, agent app, verify pages, admin)."""
    try:
        profile = PartyProfile.load()
    except (OperationalError, ProgrammingError):  # before migrations have run
        profile = PartyProfile()
    return {
        "party": profile,
        "party_logo": profile.logo.url if profile.logo else static("site/img/pangu-logo.png"),
        "party_header": profile.header_image.url if profile.header_image else static("site/img/leaders-header.jpg"),
    }
