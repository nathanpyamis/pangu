"""
python manage.py seed_party

Creates the party profile, Morobe's open electorates and placeholder policy
pillars so the site has something to show. Safe to run more than once: it
never overwrites anything you have edited in /admin/.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.cms.models import PartyProfile, PolicyDocument
from apps.geo.models import Electorate, Province

# Verify against the PNG Electoral Commission list before the 2027 writs.
MOROBE_OPEN = ["Bulolo", "Finschhafen", "Huon Gulf", "Kabwum", "Lae",
               "Markham", "Menyamya", "Nawae", "Tewai-Siassi"]

PILLARS = [
    (PolicyDocument.Pillar.ECONOMY, "[Placeholder] Economy policy title"),
    (PolicyDocument.Pillar.AGRICULTURE, "[Placeholder] Agriculture policy title"),
    (PolicyDocument.Pillar.INFRASTRUCTURE, "[Placeholder] Infrastructure policy title"),
    (PolicyDocument.Pillar.EDUCATION, "[Placeholder] Education policy title"),
    (PolicyDocument.Pillar.HEALTH, "[Placeholder] Health policy title"),
    (PolicyDocument.Pillar.LAW_ORDER, "[Placeholder] Law & Order policy title"),
]


class Command(BaseCommand):
    help = "Seed party profile, Morobe open electorates and placeholder policies."

    @transaction.atomic
    def handle(self, *args, **opts):
        if not Province.objects.filter(code="MOR").exists():
            call_command("seed_provinces")
        morobe = Province.objects.get(code="MOR")
        for name in MOROBE_OPEN:
            Electorate.objects.get_or_create(province=morobe, name=f"{name} Open",
                                             defaults={"electorate_type": Electorate.Type.OPEN})
        PartyProfile.load()
        if not PolicyDocument.objects.exists():
            for i, (pillar, title) in enumerate(PILLARS):
                PolicyDocument.objects.create(
                    pillar=pillar, title=title, order=i,
                    summary="[Placeholder] Two or three sentences on the party's policy. "
                            "Edit in Admin > Policy documents and attach the PDF summary.",
                )
        self.stdout.write(self.style.SUCCESS("Party seeded. Edit everything in /admin/."))
