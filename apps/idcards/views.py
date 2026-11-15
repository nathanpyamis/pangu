from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import StaffProfile, User
from apps.candidates.models import CandidateApplication
from apps.portal.access import is_exec, portal_required, scope_province

from .builders import pdf_response, staff_card
from .forms import StaffCardForm


# ===========================================================================
# Public QR checks
# ===========================================================================

def verify_candidate(request, pk):
    """Target of the candidate card QR: endorsed candidates only, no personal data."""
    app = (CandidateApplication.objects.select_related("electorate__province")
           .filter(pk=pk).first())
    valid = bool(app and app.card_is_valid)
    ctx = {"valid": valid, "kind": "Candidate", "valid_title": "Endorsed party candidate",
           "invalid_text": "This card does not match a currently endorsed candidate. "
                           "Contact the party secretariat."}
    if valid:
        ctx.update(
            photo_url=reverse("verify_candidate_photo", args=[app.pk]) if app.photo else "",
            rows=[("Name", app.full_name),
                  ("Candidate No.", app.candidate_number),
                  ("Seat", f"{app.electorate.name}, {app.electorate.province.name}"),
                  ("Endorsed", app.decided_at.strftime("%d %b %Y") if app.decided_at else "")],
            number_row=1)
    return render(request, "idcards/verify.html", ctx)


def candidate_photo(request, pk):
    """The endorsed candidate's photo for the QR page. Nothing for anyone else."""
    app = get_object_or_404(CandidateApplication, pk=pk)
    if not app.card_is_valid or not app.photo:
        raise Http404
    from django.http import FileResponse
    return FileResponse(app.photo.open("rb"), content_type="image/jpeg")


def verify_staff(request, pk):
    """Target of the staff card QR: shows whether the officer is authorised right now."""
    profile = (StaffProfile.objects.select_related("user__assigned_province", "user__assigned_electorate")
               .filter(pk=pk).first())
    valid = bool(profile and profile.staff_number and profile.is_valid)
    ctx = {"valid": valid, "kind": "Officer", "valid_title": "Authorised party officer",
           "invalid_text": "This officer is not currently authorised by the party. Do not give them "
                           "personal details. Contact the provincial office."}
    if valid:
        rows = [("Name", profile.display_name), ("Staff No.", profile.staff_number),
                ("Role", profile.user.get_role_display()), ("Area", profile.area)]
        if profile.valid_until:
            rows.append(("Valid until", profile.valid_until.strftime("%d %b %Y")))
        ctx.update(photo_url=profile.photo.url if profile.photo else "", rows=rows, number_row=1)
    return render(request, "idcards/verify.html", ctx)


# ===========================================================================
# Portal: field officers (staff cards)
# ===========================================================================

def staff_visible_to(user):
    """Executives: agents and coordinators nationwide. Coordinators: agents in their province."""
    qs = User.objects.filter(role__in=[User.Role.AGENT, User.Role.COORDINATOR]).select_related(
        "assigned_province", "assigned_electorate", "staff_profile")
    if not is_exec(user):
        qs = qs.filter(role=User.Role.AGENT)
    return scope_province(qs, user, "assigned_province_id")


@portal_required
def staff_list(request):
    qs = staff_visible_to(request.user).annotate(
        registered=Count("registered_members", distinct=True),
        last_sync=Max("sync_logs__received_at"))
    role, q, card = request.GET.get("role", ""), request.GET.get("q", "").strip(), request.GET.get("card", "")
    if role in (User.Role.AGENT, User.Role.COORDINATOR):
        qs = qs.filter(role=role)
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                       | Q(staff_profile__staff_number__icontains=q))
    if card == "none":
        qs = qs.filter(Q(staff_profile__isnull=True) | Q(staff_profile__staff_number__isnull=True))
    elif card == "suspended":
        qs = qs.filter(staff_profile__card_status=StaffProfile.CardStatus.SUSPENDED)
    elif card == "unprinted":
        qs = qs.filter(staff_profile__staff_number__isnull=False, staff_profile__id_card_printed=False)
    return render(request, "idcards/staff_list.html", {
        "section": "staff", "staff": qs.order_by("assigned_province__name", "last_name", "username"),
        "role": role, "q": q, "card": card,
    })


@portal_required
def staff_detail(request, user_id):
    member = get_object_or_404(staff_visible_to(request.user), pk=user_id)
    profile, _ = StaffProfile.objects.get_or_create(user=member)
    form = StaffCardForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == "POST":
        if form.is_valid():
            profile = form.save()
            profile.ensure_number()
            messages.success(request, f"Card details saved for {profile.display_name}.")
            return redirect("staff:detail", user_id=member.pk)
    recent = member.registered_members.select_related("electorate").order_by("-server_synced_at")[:8]
    return render(request, "idcards/staff_detail.html", {
        "section": "staff", "staff_user": member, "profile": profile, "form": form,
        "registered": member.registered_members.count(),
        "verified": member.registered_members.filter(is_verified=True).count(),
        "syncs": member.sync_logs.all()[:8], "recent": recent,
    })


def _issue(profile):
    if not profile.staff_number:
        profile.ensure_number()
    return profile


@portal_required
def staff_card_pdf(request, user_id):
    member = get_object_or_404(staff_visible_to(request.user), pk=user_id)
    profile, _ = StaffProfile.objects.get_or_create(user=member)
    _issue(profile)
    if not profile.is_valid:
        messages.error(request, "This card is suspended, expired or the user is inactive. Fix that first.")
        return redirect("staff:detail", user_id=member.pk)
    resp = pdf_response([staff_card(profile)], "cr80", f"{profile.staff_number}.pdf")
    StaffProfile.objects.filter(pk=profile.pk).update(id_card_printed=True, id_card_printed_at=timezone.now())
    return resp


@portal_required
@require_POST
def staff_cards_batch(request):
    ids = request.POST.getlist("ids")
    if not ids:
        messages.error(request, "Tick the officers whose cards you want to print.")
        return redirect("staff:list")
    profiles = []
    for member in staff_visible_to(request.user).filter(pk__in=ids, is_active=True):
        profile, _ = StaffProfile.objects.get_or_create(user=member)
        _issue(profile)
        if profile.is_valid:
            profiles.append(profile)
    if not profiles:
        messages.error(request, "None of the selected officers has a valid card.")
        return redirect("staff:list")
    resp = pdf_response([staff_card(p) for p in profiles], request.POST.get("layout", "a4-10"),
                        "officer-cards.pdf")
    StaffProfile.objects.filter(pk__in=[p.pk for p in profiles]).update(
        id_card_printed=True, id_card_printed_at=timezone.now())
    return resp
