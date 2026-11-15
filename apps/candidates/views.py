import csv
import mimetypes
from pathlib import Path

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.cms.models import PartyProfile
from apps.geo.models import Province
from apps.idcards.builders import candidate_card, pdf_response
from apps.portal.access import exec_required, is_exec, portal_required, scope_province

from .forms import ApplicationForm, DecisionForm, ReviewForm, StatusLookupForm
from .letters import endorsement_letter
from .models import ApplicationEvent, ApplicationReview, CandidateApplication, make_reference

S = CandidateApplication.Status
DOC_FIELDS = ("photo", "cv", "nid_copy", "police_clearance")


def _client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) or None


def visible_applications(user):
    qs = CandidateApplication.objects.select_related("electorate__province")
    return scope_province(qs, user, "electorate__province_id")


# ===========================================================================
# Public: apply and check status
# ===========================================================================

def apply(request):
    party = PartyProfile.load()
    if not party.applications_are_open:
        return render(request, "candidates/closed.html")

    form = ApplicationForm(request.POST or None, request.FILES or None,
                           election_date=party.election_date)
    if request.method == "POST" and form.is_valid():
        app = form.save(commit=False)
        app.submitted_ip = _client_ip(request)
        app.detect_duplicates()
        for _ in range(3):   # a reference collision is near-impossible; retry anyway
            try:
                with transaction.atomic():
                    app.save()
                break
            except IntegrityError:
                app.reference = make_reference()
        ApplicationEvent.objects.create(application=app, to_status=app.status, note="Submitted online")
        request.session["candidate_ref"] = app.reference
        return redirect("candidates:apply_done")
    return render(request, "candidates/apply.html", {"form": form})


def apply_done(request):
    ref = request.session.get("candidate_ref")
    app = CandidateApplication.objects.filter(reference=ref).select_related("electorate").first() if ref else None
    if not app:
        return redirect("candidates:apply")
    return render(request, "candidates/apply_done.html", {"app": app})


def status(request):
    form = StatusLookupForm(request.POST or None)
    app = None
    if request.method == "POST" and form.is_valid():
        app = CandidateApplication.objects.filter(
            reference=form.cleaned_data["reference"], phone=form.cleaned_data["phone"]
        ).select_related("electorate").first()
        if not app:
            form.add_error(None, "No application matches that reference and phone number.")
    steps = [S.SUBMITTED, S.UNDER_REVIEW, S.SHORTLISTED, S.INTERVIEW, S.APPROVED]
    return render(request, "candidates/status.html", {
        "form": form, "app": app,
        "steps": [(s, S(s).label) for s in steps],
        "step_index": steps.index(app.status) if app and app.status in steps else -1,
    })


# ===========================================================================
# Portal: candidate database
# ===========================================================================

@portal_required
def database(request):
    base = visible_applications(request.user)
    qs = base
    q = request.GET.get("q", "").strip()
    st = request.GET.get("status", "")
    prov = request.GET.get("province", "")
    flagged = request.GET.get("flagged", "")
    gender = request.GET.get("gender", "")
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(reference__icontains=q)
                       | Q(candidate_number__icontains=q) | Q(phone__icontains=q)
                       | Q(electorate__name__icontains=q))
    if st == "open":
        qs = qs.filter(status__in=CandidateApplication.OPEN_STATUSES)
    elif st:
        qs = qs.filter(status=st)
    if prov:
        qs = qs.filter(electorate__province_id=prov)
    if flagged:
        qs = qs.filter(flagged=True)
    if gender in ("F", "M"):
        qs = qs.filter(gender=gender)
    qs = qs.annotate(review_count=Count("reviews"))

    if request.GET.get("export") == "csv":
        if not is_exec(request.user):
            raise PermissionDenied
        return _export_csv(qs)

    counts = {r["status"]: r["n"] for r in base.order_by().values("status").annotate(n=Count("id"))}
    seat_counts = dict(base.exclude(status__in=[S.REJECTED, S.WITHDRAWN]).order_by()
                       .values_list("electorate_id").annotate(n=Count("id")))
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    for a in page:
        a.seat_rivals = seat_counts.get(a.electorate_id, 1) - 1

    provinces = scope_province(Province.objects.all(), request.user, "pk")
    params = request.GET.copy()
    params.pop("page", None)
    params.pop("export", None)
    return render(request, "candidates/database.html", {
        "page": page, "q": q, "st": st, "prov": prov, "flagged": flagged, "gender": gender,
        "counts": counts, "total": sum(counts.values()), "statuses": S.choices,
        "provinces": provinces, "querystring": params.urlencode(), "section": "candidates",
    })


@portal_required
def detail(request, pk):
    app = get_object_or_404(visible_applications(request.user), pk=pk)
    mine = ApplicationReview.objects.filter(application=app, reviewer=request.user).first()
    review_form = ReviewForm(instance=mine, prefix="rv")
    decision_form = DecisionForm(application=app, prefix="dc") if is_exec(request.user) else None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "review" and app.is_open:
            review_form = ReviewForm(request.POST, instance=mine, prefix="rv")
            if review_form.is_valid():
                r = review_form.save(commit=False)
                r.application, r.reviewer = app, request.user
                r.reviewer_role = "EXEC" if is_exec(request.user) else request.user.role
                r.save()
                if app.status == S.SUBMITTED:
                    move(app, S.UNDER_REVIEW, request.user, "First review recorded")
                messages.success(request, "Your review was saved.")
                return redirect("candidate_db:detail", pk=app.pk)
        elif action == "decide":
            if not is_exec(request.user):
                raise PermissionDenied
            decision_form = DecisionForm(request.POST, application=app, prefix="dc")
            if decision_form.is_valid():
                cd = decision_form.cleaned_data
                if cd.get("interview_at"):
                    app.interview_at = cd["interview_at"]
                    app.interview_place = cd.get("interview_place", "")
                if cd.get("applicant_message"):
                    app.applicant_message = cd["applicant_message"]
                move(app, cd["to_status"], request.user, cd.get("note", ""))
                messages.success(request, f"Status changed to {app.get_status_display()}.")
                return redirect("candidate_db:detail", pk=app.pk)
        elif action == "clear_flag" and is_exec(request.user):
            app.flagged, app.flag_reason, app.duplicate_of = False, "", None
            app.save(update_fields=["flagged", "flag_reason", "duplicate_of", "updated_at"])
            ApplicationEvent.objects.create(application=app, actor=request.user, note="Duplicate flag cleared")
            return redirect("candidate_db:detail", pk=app.pk)

    party = PartyProfile.load()
    return render(request, "candidates/detail.html", {
        "app": app,
        "age": app.age_on(party.election_date or timezone.localdate()),
        "reviews": app.reviews.select_related("reviewer"),
        "events": app.events.select_related("actor")[:50],
        "rivals": app.rivals().select_related("electorate"),
        "scores": app.average_scores(),
        "criteria": ApplicationReview.CRITERIA,
        "review_form": review_form, "decision_form": decision_form,
        "my_review": mine, "section": "candidates",
    })


def move(app, to, actor, note=""):
    """Change status, keep the audit trail, issue numbers on endorsement."""
    frm = app.status
    app.status = to
    fields = ["status", "updated_at", "interview_at", "interview_place", "applicant_message"]
    if to in CandidateApplication.FINAL_STATUSES:
        app.decided_by, app.decided_at, app.decision_note = actor, timezone.now(), note
        fields += ["decided_by", "decided_at", "decision_note"]
    if to == S.APPROVED:
        if not app.letter_number:
            app.letter_number = f"PANGU/END/27/{app.reference[-6:]}"
            fields.append("letter_number")
        if not app.candidate_number:
            app.issue_candidate_number()
            fields.append("candidate_number")
    app.save(update_fields=fields)
    ApplicationEvent.objects.create(application=app, actor=actor, from_status=frm, to_status=to, note=note)


@portal_required
def document(request, pk, field):
    if field not in DOC_FIELDS:
        raise Http404
    app = get_object_or_404(visible_applications(request.user), pk=pk)
    f = getattr(app, field)
    if not f:
        raise Http404
    ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    inline = ctype.startswith("image/") or ctype == "application/pdf"
    resp = FileResponse(f.open("rb"), content_type=ctype, as_attachment=not inline,
                        filename=f"{app.reference}-{field}{Path(f.name).suffix}")
    resp["Cache-Control"] = "private, no-store"
    return resp


@exec_required
def letter(request, pk):
    app = get_object_or_404(CandidateApplication, pk=pk, status=S.APPROVED)
    party = PartyProfile.load()
    if party.logo:
        logo = party.logo.path
    else:
        from django.contrib.staticfiles import finders
        logo = finders.find("site/img/pangu-logo.png")
    party.address = party.office_address   # letterhead fields
    pdf = endorsement_letter(app, party, party.signatory_name, party.signatory_title, logo)
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="endorsement-{app.reference}.pdf"'
    return resp


@portal_required
def card(request, pk):
    """Candidate ID card, CR80. Endorsed candidates only."""
    app = get_object_or_404(visible_applications(request.user), pk=pk, status=S.APPROVED)
    if not app.candidate_number:
        app.issue_candidate_number()
        app.save(update_fields=["candidate_number", "updated_at"])
    resp = pdf_response([candidate_card(app)], "cr80", f"{app.candidate_number}.pdf")
    CandidateApplication.objects.filter(pk=app.pk).update(id_card_printed=True, id_card_printed_at=timezone.now())
    return resp


@portal_required
@require_POST
def cards_batch(request):
    """POST ids=<uuid>... or unprinted=1; layout=a4-10|a4-8|cr80."""
    qs = visible_applications(request.user).filter(status=S.APPROVED)
    ids = request.POST.getlist("ids")
    if ids:
        qs = qs.filter(pk__in=ids)
    elif request.POST.get("unprinted") == "1":
        qs = qs.filter(id_card_printed=False)
    apps = list(qs.order_by("electorate__province__name", "electorate__name")[:400])
    if not apps:
        messages.error(request, "No endorsed candidates match. Only endorsed candidates get cards.")
        return redirect("candidate_db:database")
    for a in apps:
        if not a.candidate_number:
            a.issue_candidate_number()
            a.save(update_fields=["candidate_number", "updated_at"])
    resp = pdf_response([candidate_card(a) for a in apps], request.POST.get("layout", "a4-10"),
                        "candidate-cards.pdf")
    CandidateApplication.objects.filter(pk__in=[a.pk for a in apps]).update(
        id_card_printed=True, id_card_printed_at=timezone.now())
    return resp


def _export_csv(qs):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="pangu-candidates-{timezone.localdate()}.csv"'
    w = csv.writer(resp)
    w.writerow(["Reference", "Candidate No.", "Name", "Gender", "Age today", "Province", "Electorate",
                "Phone", "Email", "Occupation", "Education", "Party status", "Status", "Reviews",
                "Flagged", "Submitted", "Decided"])
    today = timezone.localdate()
    for a in qs:
        w.writerow([a.reference, a.candidate_number or "", a.full_name, a.get_gender_display(),
                    a.age_on(today), a.electorate.province.name, a.electorate.name, a.phone, a.email,
                    a.occupation, a.get_education_display(), a.get_party_status_display(),
                    a.get_status_display(), getattr(a, "review_count", ""), "yes" if a.flagged else "",
                    a.created_at.strftime("%Y-%m-%d"),
                    a.decided_at.strftime("%Y-%m-%d") if a.decided_at else ""])
    return resp
