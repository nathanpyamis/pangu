"""
python manage.py seed_electorates
python manage.py seed_electorates --file C:\\path\\to\\my_list.csv
python manage.py seed_electorates --dry-run

Loads OPEN electorates from a CSV file (default: apps/geo/data/open_electorates.csv).

    province_code,electorate_name
    MOR,Lae Open
    EHP,Goroka Open

- Lines starting with # are ignored, so the file can carry notes.
- Safe to run again and again: existing electorates are kept as they are,
  only new rows are added. Nothing is ever deleted or renamed, because
  members and candidate applications point at electorates.
- Run seed_provinces first (it creates the provinces and their Provincial seats).
- To rename or remove an electorate, use Admin -> Geo -> Electorates.
"""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.geo.models import Electorate, Province

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "data" / "open_electorates.csv"


class Command(BaseCommand):
    help = "Load open electorates from a CSV file (province_code,electorate_name)."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(DEFAULT_FILE),
                            help="CSV file to load (default: apps/geo/data/open_electorates.csv)")
        parser.add_argument("--dry-run", action="store_true",
                            help="Check the file and report what would be added, without saving.")

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        provinces = {p.code.upper(): p for p in Province.objects.all()}
        if not provinces:
            raise CommandError("No provinces yet. Run: python manage.py seed_provinces")

        rows, problems = [], []
        # utf-8-sig copes with the byte-order mark Excel adds when saving CSV
        with path.open(newline="", encoding="utf-8-sig") as f:
            for lineno, raw in enumerate(csv.reader(f), start=1):
                if not raw or not raw[0].strip() or raw[0].strip().startswith("#"):
                    continue
                if lineno == 1 and raw[0].strip().lower() == "province_code":
                    continue   # header
                if len(raw) < 2 or not raw[1].strip():
                    problems.append(f"line {lineno}: needs province_code,electorate_name")
                    continue
                code, name = raw[0].strip().upper(), " ".join(raw[1].split())
                if code not in provinces:
                    problems.append(f"line {lineno}: unknown province code '{code}'")
                    continue
                if name.lower().endswith("provincial"):
                    problems.append(f"line {lineno}: '{name}' looks like a Provincial seat; "
                                    "those come from seed_provinces")
                    continue
                rows.append((lineno, provinces[code], name))

        seen, created, existing = set(), [], 0
        with transaction.atomic():
            for lineno, province, name in rows:
                key = (province.pk, name.lower())
                if key in seen:
                    problems.append(f"line {lineno}: '{name}' is listed twice for {province.name}")
                    continue
                seen.add(key)
                match = Electorate.objects.filter(province=province, name__iexact=name).first()
                if match:
                    existing += 1
                    continue
                if not opts["dry_run"]:
                    Electorate.objects.create(province=province, name=name,
                                              electorate_type=Electorate.Type.OPEN)
                created.append(f"{province.code} {name}")
            if opts["dry_run"]:
                transaction.set_rollback(True)

        for p in problems:
            self.stdout.write(self.style.WARNING("  skipped " + p))
        verb = "Would add" if opts["dry_run"] else "Added"
        for c in created:
            self.stdout.write(f"  {verb.lower()} {c}")
        total_open = Electorate.objects.filter(electorate_type=Electorate.Type.OPEN).count()
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {len(created)} open electorate(s); {existing} already there; "
            f"{len(problems)} line(s) skipped. Open electorates in the database: {total_open}."))
        # Show provinces that still have no open electorate, so gaps are obvious
        empty = [p.name for p in Province.objects.order_by("name")
                 if not p.electorates.filter(electorate_type=Electorate.Type.OPEN).exists()]
        if empty:
            self.stdout.write(self.style.WARNING(
                f"{len(empty)} province(s) with no open electorates yet: " + ", ".join(empty)))
