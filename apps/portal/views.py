import csv
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.candidates.models import CandidateApplication
from apps.geo.models import Electorate, Province, Region
from apps.members.models import Member, SyncLog
from apps.members.permissions import members_visible_to

from .access import is_exec, landing_url, portal_required, scope_province

S = CandidateApplication.Status


# ===========================================================================
# Login
# ===========================================================================

class PortalLoginView(auth_views.LoginView):
    """One login for the whole team: executives and coordinators land on the
    dashboard, field agents are sent on to the offline agent app."""
    template_name = "portal/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return self.get_redirect_url() or landing_url(self.request.user)


class PortalLogoutView(auth_views.LogoutView):
    next_page = "/"


# ===========================================================================
# Overall progress (executive dashboard)
# ===========================================================================

def _pct(part, whole):
    return round(100 * part / whole) if whole else 0


@portal_required
def dashboard(request):
    user = request.user
    members = members_visible_to(user)
    live = members.filter(duplicate_of__isnull=True)
    apps = scope_province(CandidateApplication.objects.all(), user, "electorate__province_id")
    electorates = scope_province(Electorate.objects.all(), user, "province_id")
    provinces = scope_province(Province.objects.all(), user, "pk")
    staff = scope_province(User.objects.filter(role__in=[User.Role.AGENT, User.Role.COORDINATOR]),
                           user, "assigned_province_id")

    today = timezone.localdate()
    week_ago = timezone.now() - timedelta(days=7)

    # --- Members ----------------------------------------------------------
    m = live.aggregate(
        total=Count("id"),
        verified=Count("id", filter=Q(is_verified=True)),
        printed=Count("id", filter=Q(id_card_printed=True)),
        field=Count("id", filter=Q(source=Member.Source.FIELD)),
        online=Count("id", filter=Q(source=Member.Source.ONLINE)),
        female=Count("id", filter=Q(gender="F")),
        week=Count("id", filter=Q(server_synced_at__gte=week_ago)),
    )
    m["pending"] = m["total"] - m["verified"]
    m["flagged"] = members.exclude(review_flag="").count()
    m["verified_pct"] = _pct(m["verified"], m["total"])
    m["printed_pct"] = _pct(m["printed"], m["verified"])
    m["female_pct"] = _pct(m["female"], m["total"])

    # Registrations per day, last 14 days (single series)
    start = today - timedelta(days=13)
    per_day = dict(live.filter(server_synced_at__date__gte=start)
                   .annotate(d=TruncDate("server_synced_at")).order_by()
                   .values_list("d").annotate(n=Count("id")))
    days = [start + timedelta(days=i) for i in range(14)]
    peak = max([per_day.get(d, 0) for d in days] + [1])
    daily = [{"day": d, "n": per_day.get(d, 0), "h": round(100 * per_day.get(d, 0) / peak)} for d in days]

    # --- Candidates -------------------------------------------------------
    counts = {r["status"]: r["n"] for r in apps.order_by().values("status").annotate(n=Count("id"))}
    pipeline = [(code, label, counts.get(code, 0)) for code, label in S.choices]
    c_open = sum(counts.get(s, 0) for s in CandidateApplication.OPEN_STATUSES)
    seats_total = electorates.count()
    endorsed_seats = (apps.filter(status=S.APPROVED).order_by()
                      .values("electorate_id").distinct().count())
    seats_with_applicants = (apps.exclude(status__in=[S.REJECTED, S.WITHDRAWN]).order_by()
                             .values("electorate_id").distinct().count())
    contested = (apps.exclude(status__in=[S.REJECTED, S.WITHDRAWN]).order_by()
                 .values("electorate__name", "electorate__province__name")
                 .annotate(n=Count("id")).filter(n__gt=1).order_by("-n")[:6])

    # --- By province ------------------------------------------------------
    rows = []
    mem_by = {r["electorate__province_id"]: r for r in live.order_by().values("electorate__province_id").annotate(
        total=Count("id"), verified=Count("id", filter=Q(is_verified=True)),
        printed=Count("id", filter=Q(id_card_printed=True)))}
    app_by = {r["electorate__province_id"]: r for r in apps.order_by().values("electorate__province_id").annotate(
        total=Count("id"),
        open=Count("id", filter=Q(status__in=CandidateApplication.OPEN_STATUSES)),
        endorsed=Count("electorate_id", filter=Q(status=S.APPROVED), distinct=True))}
    seats_by = dict(electorates.order_by().values_list("province_id").annotate(n=Count("id")))
    agents_by = dict(staff.filter(role=User.Role.AGENT, is_active=True).order_by()
                     .values_list("assigned_province_id").annotate(n=Count("id")))
    region_labels = dict(Region.choices)
    for p in provinces.order_by("region", "name"):
        mm, aa = mem_by.get(p.pk, {}), app_by.get(p.pk, {})
        seats = seats_by.get(p.pk, 0)
        rows.append({
            "province": p, "region": region_labels.get(p.region, p.region),
            "members": mm.get("total", 0), "verified": mm.get("verified", 0),
            "verified_pct": _pct(mm.get("verified", 0), mm.get("total", 0)),
            "printed": mm.get("printed", 0),
            "applications": aa.get("total", 0), "open": aa.get("open", 0),
            "endorsed": aa.get("endorsed", 0), "seats": seats,
            "coverage_pct": _pct(aa.get("endorsed", 0), seats),
            "agents": agents_by.get(p.pk, 0),
        })

    # --- Field agents -----------------------------------------------------
    agents = (staff.filter(role=User.Role.AGENT)
              .annotate(registered=Count("registered_members", distinct=True),
                        last_sync=Max("sync_logs__received_at"))
              .select_related("assigned_electorate")
              .order_by("-registered")[:10])
    agent_totals = staff.filter(role=User.Role.AGENT).aggregate(
        total=Count("id", filter=Q(is_active=True), distinct=True),
        active_week=Count("id", filter=Q(sync_logs__received_at__gte=week_ago), distinct=True))
    cards_issued = staff.filter(staff_profile__staff_number__isnull=False).count()

    return render(request, "portal/dashboard.html", {
        "section": "dashboard", "m": m, "daily": daily, "peak": peak,
        "pipeline": pipeline, "c_total": sum(counts.values()), "c_open": c_open,
        "c_endorsed": counts.get(S.APPROVED, 0), "c_flagged": apps.filter(flagged=True).count(),
        "seats_total": seats_total, "endorsed_seats": endorsed_seats,
        "coverage_pct": _pct(endorsed_seats, seats_total),
        "seats_with_applicants": seats_with_applicants,
        "applicant_pct": _pct(seats_with_applicants, seats_total),
        "contested": contested, "rows": rows,
        "totals": {k: sum(r[k] for r in rows) for k in
                   ("members", "verified", "printed", "applications", "open", "endorsed", "seats", "agents")},
        "agents": agents, "agent_totals": agent_totals, "cards_issued": cards_issued,
        "recent_syncs": SyncLog.objects.filter(agent__in=staff).select_related("agent")[:6],
        "scope_label": "Nationwide" if is_exec(user) else (user.assigned_province.name if user.assigned_province_id else ""),
    })


# ===========================================================================
# Members database
# ===========================================================================

@portal_required
def members(request):
    base = members_visible_to(request.user)
    qs = base.select_related("electorate__province", "registered_by")
    g = request.GET
    q, prov, elec = g.get("q", "").strip(), g.get("province", ""), g.get("electorate", "")
    state, source, gender, card = g.get("state", ""), g.get("source", ""), g.get("gender", ""), g.get("card", "")
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(membership_number__icontains=q)
                       | Q(phone_number__icontains=q) | Q(nid_number__icontains=q)
                       | Q(village_or_street__icontains=q) | Q(llg_ward__icontains=q)
                       | Q(residential_address__icontains=q))
    if prov:
        qs = qs.filter(electorate__province_id=prov)
    if elec:
        qs = qs.filter(electorate_id=elec)
    if state == "verified":
        qs = qs.filter(is_verified=True)
    elif state == "pending":
        qs = qs.filter(is_verified=False, review_flag="")
    elif state == "flagged":
        qs = qs.exclude(review_flag="")
    if source in Member.Source.values:
        qs = qs.filter(source=source)
    if gender in ("F", "M"):
        qs = qs.filter(gender=gender)
    if card == "printed":
        qs = qs.filter(id_card_printed=True)
    elif card == "unprinted":
        qs = qs.filter(is_verified=True, id_card_printed=False)

    if g.get("export") == "csv":
        return _members_csv(qs)

    stats = base.aggregate(total=Count("id"), verified=Count("id", filter=Q(is_verified=True)),
                           flagged=Count("id", filter=~Q(review_flag="")),
                           unprinted=Count("id", filter=Q(is_verified=True, id_card_printed=False)))
    page = Paginator(qs, 50).get_page(g.get("page"))
    params = g.copy()
    params.pop("page", None)
    params.pop("export", None)
    provinces = scope_province(Province.objects.all(), request.user, "pk")
    electorates = scope_province(Electorate.objects.select_related("province"), request.user, "province_id")
    if prov:
        electorates = electorates.filter(province_id=prov)
    return render(request, "portal/members.html", {
        "section": "members", "page": page, "stats": stats, "querystring": params.urlencode(),
        "q": q, "prov": prov, "elec": elec, "state": state, "source": source, "gender": gender, "card": card,
        "provinces": provinces, "electorates": electorates.order_by("name"),
        "sources": Member.Source.choices,
    })


@portal_required
@require_POST
def members_verify(request):
    """Verify the ticked members (skips flagged duplicates)."""
    ids = request.POST.getlist("ids")
    ok = skipped = 0
    for m in members_visible_to(request.user).filter(pk__in=ids, is_verified=False):
        try:
            m.verify(request.user)
            ok += 1
        except ValueError:
            skipped += 1
    if ok:
        messages.success(request, f"Verified {ok} member{'s' if ok != 1 else ''}.")
    if skipped:
        messages.warning(request, f"Skipped {skipped} flagged duplicate{'s' if skipped != 1 else ''}: "
                                  "resolve the flag in Admin → Members first.")
    if not ok and not skipped:
        messages.info(request, "Nothing to verify in that selection.")
    return redirect(request.POST.get("next") or "portal:members")


def _members_csv(qs):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="pangu-members-{timezone.localdate()}.csv"'
    w = csv.writer(resp)
    w.writerow(["Membership No.", "Name", "Gender", "Date of birth", "Province", "Electorate",
                "LLG / Ward", "Village / Street", "Residential address", "Latitude", "Longitude",
                "Location from", "Phone", "Source", "Verified", "Card printed",
                "Review flag", "Registered by", "Registered"])
    for m in qs.iterator(chunk_size=500):
        w.writerow([m.membership_number or "", m.full_name, m.get_gender_display(),
                    m.date_of_birth or "", m.electorate.province.name, m.electorate.name,
                    m.llg_ward, m.village_or_street, m.residential_address,
                    m.latitude if m.latitude is not None else "", m.longitude if m.longitude is not None else "",
                    m.get_location_source_display() if m.location_source else "",
                    m.phone_number, m.get_source_display(),
                    "yes" if m.is_verified else "", "yes" if m.id_card_printed else "",
                    m.get_review_flag_display() if m.review_flag else "",
                    m.registered_by.get_username() if m.registered_by_id else "",
                    timezone.localtime(m.server_synced_at).strftime("%Y-%m-%d")])
    return resp
