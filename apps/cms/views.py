from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.geo.models import Electorate
from apps.members.models import Member
from apps.members.utils import PhotoError, clean_member_photo
from apps.members.views import find_duplicate

from .forms import ContactForm, JoinForm
from .models import Leader, NewsPost, PartyProfile, PolicyDocument

# Online joiners upload straight from phone cameras; the browser shrinks the
# photo first when JS is on, but accept a full-size photo as fallback.
WEB_PHOTO_MAX_BYTES = 8 * 1024 * 1024


def electorate_groups(first_province=None):
    """Electorates grouped by province (optionally one province first)."""
    groups = {}
    for e in Electorate.objects.select_related("province").order_by("province__name", "electorate_type", "name"):
        label = e.name if e.electorate_type == Electorate.Type.OPEN else f"{e.name} (Regional)"
        groups.setdefault(e.province.name, []).append({"id": str(e.pk), "label": label})
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] != first_province, kv[0]))
    return [{"province": p, "electorates": es} for p, es in ordered]


def form_state(form):
    """Plain dicts for templates: values, per-field errors, form-level errors."""
    if form is None:
        return {"val": {}, "errors": {}, "non_field": []}
    values = {}
    if form.is_bound:
        for name in form.fields:
            v = form.data.get(name, "")
            values[name] = "" if name == "photo" else str(v)
    return {
        "val": values,
        "errors": {k: list(v) for k, v in form.errors.items() if k != "__all__"},
        "non_field": list(form.non_field_errors()),
    }


def _stats():
    """Headline numbers for the home page. Never breaks the page."""
    try:
        from apps.candidates.models import CandidateApplication
        from apps.geo.models import Province
        return {
            "members": Member.objects.filter(is_verified=True).count(),
            "provinces": Province.objects.count() or 22,
            "endorsed": CandidateApplication.objects.filter(
                status=CandidateApplication.Status.APPROVED).count(),
        }
    except Exception:  # before migrations
        return {"members": 0, "provinces": 22, "endorsed": 0}


def _page_context(request, **extra):
    ctx = {
        "policies": list(PolicyDocument.objects.filter(is_published=True)),
        "news": list(NewsPost.objects.filter(is_published=True)[:6]),
        "leaders": list(Leader.objects.filter(is_visible=True)),
        "electorate_groups": electorate_groups(),
        "stats": _stats(),
        "open_panel": "",
    }
    ctx["jf"] = form_state(extra.pop("join_form", None))
    ctx["cf"] = form_state(extra.pop("contact_form", None))
    ctx.update(extra)
    return ctx


def home(request):
    return render(request, "cms/home.html", _page_context(request))


def join(request):
    if request.method != "POST":
        return redirect("/#join")
    form = JoinForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "cms/home.html",
                      _page_context(request, join_form=form, open_panel="join"), status=400)

    d = form.cleaned_data
    photo = None
    if d.get("photo"):
        try:
            photo = clean_member_photo(d["photo"], max_bytes=WEB_PHOTO_MAX_BYTES, size_px=300)
        except PhotoError as e:
            form.add_error("photo", str(e))
            return render(request, "cms/home.html",
                          _page_context(request, join_form=form, open_panel="join"), status=400)

    flag, dup = find_duplicate(d)
    member = Member(
        full_name=d["full_name"], gender=d["gender"], date_of_birth=d["date_of_birth"],
        nid_number=d["nid_number"], phone_number=d["phone_number"], electorate=d["electorate"],
        llg_ward=d["llg_ward"], village_or_street=d["village_or_street"],
        residential_address=d["residential_address"],
        latitude=d["latitude"], longitude=d["longitude"],
        location_accuracy_m=d["location_accuracy_m"], location_source=d["location_source"],
        source=Member.Source.ONLINE, client_created_at=timezone.now(), review_flag=flag,
        duplicate_of=dup if flag in (Member.ReviewFlag.DUPLICATE_NID,
                                     Member.ReviewFlag.DUPLICATE_NAME_PHONE) else None,
    )
    try:
        with transaction.atomic():
            member.save(force_insert=True)
            if photo:
                member.photo.save(photo.name, photo, save=True)
    except IntegrityError:
        form.add_error(None, "We could not save your registration. Please try again.")
        return render(request, "cms/home.html",
                      _page_context(request, join_form=form, open_panel="join"), status=400)

    # Same message whether or not it was flagged: never reveal whether an
    # NID or phone number is already on the party register.
    return render(request, "cms/home.html", _page_context(
        request, open_panel="join", join_done=True, joined_name=member.full_name.split(" ")[0]))


def contact(request):
    if request.method != "POST":
        return redirect("/#contact")
    form = ContactForm(request.POST)
    if not form.is_valid():
        return render(request, "cms/home.html",
                      _page_context(request, contact_form=form, open_panel="contact"), status=400)
    form.save()
    return render(request, "cms/home.html",
                  _page_context(request, open_panel="contact", contact_done=True))


def news_detail(request, slug):
    post = get_object_or_404(NewsPost, slug=slug, is_published=True)
    return render(request, "cms/news_detail.html", {"post": post})
