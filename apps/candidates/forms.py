import io
from pathlib import Path

from django import forms
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.utils import timezone
from PIL import Image, ImageOps

from .models import ApplicationReview, CandidateApplication

MAX_DOC_MB = 5
MAX_PHOTO_MB = 8
DOC_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}
MIN_AGE = 25   # Constitution s.103: candidates must be 25 or older. Confirm with party legal.


def reencode_photo(upload, size=(480, 600)):
    """Re-encode the portrait: strip EXIF/GPS, fix rotation, crop to 4:5."""
    img = Image.open(upload)
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, size, Image.LANCZOS, centering=(0.5, 0.35))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)
    buf.seek(0)
    return InMemoryUploadedFile(buf, "photo", "photo.jpg", "image/jpeg",
                                buf.getbuffer().nbytes, None)


def _check_doc(f, label):
    if not f:
        return f
    if Path(f.name).suffix.lower() not in DOC_EXTS:
        raise forms.ValidationError(f"{label}: upload a PDF, JPG or PNG.")
    if f.size > MAX_DOC_MB * 1024 * 1024:
        raise forms.ValidationError(f"{label}: file is larger than {MAX_DOC_MB} MB.")
    return f


class ElectorateChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name if hasattr(obj, "name") else str(obj)


class ApplicationForm(forms.ModelForm):
    # Spam honeypot — real people never see or fill this.
    website = forms.CharField(required=False, widget=forms.TextInput(
        attrs={"tabindex": "-1", "autocomplete": "off"}))

    class Meta:
        model = CandidateApplication
        fields = [
            "full_name", "preferred_name", "gender", "date_of_birth", "nid_number",
            "phone", "email", "home_province", "village", "current_address",
            "electorate", "years_resident", "born_in_electorate",
            "occupation", "employer", "education", "qualifications",
            "contested_before", "previous_contests",
            "party_status", "pangu_member_number", "other_party_name", "will_resign_other_party",
            "why_pangu", "priorities", "community_roles", "campaign_readiness",
            "referee1_name", "referee1_phone", "referee1_relationship",
            "referee2_name", "referee2_phone", "referee2_relationship",
            "photo", "cv", "nid_copy", "police_clearance",
            "declared_eligible", "consent_vetting", "declared_true", "signature_name",
        ]
        labels = {
            "born_in_electorate": "I was born in this electorate",
            "contested_before": "I have contested a national or LLG election before",
            "party_status": "Party membership",
            "pangu_member_number": "Pangu membership number (if you have one)",
            "other_party_name": "Name of your current party",
            "will_resign_other_party": "I will resign from my current party before nomination",
            "declared_eligible": ("I am a PNG citizen, will be 25 or older on polling day, and meet the "
                                  "qualifications for nomination under the Constitution and the "
                                  "Organic Law on National and Local-level Government Elections"),
            "consent_vetting": ("I consent to the party checking my background, my documents and "
                                "contacting my referees"),
            "declared_true": "The information I have given is true and complete",
            "referee1_name": "Referee 1 – name", "referee1_phone": "Phone",
            "referee1_relationship": "How they know you",
            "referee2_name": "Referee 2 – name", "referee2_phone": "Phone",
            "referee2_relationship": "How they know you",
            "photo": "Passport-style photo",
        }
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "qualifications": forms.Textarea(attrs={"rows": 2}),
            "previous_contests": forms.Textarea(attrs={"rows": 2}),
            "why_pangu": forms.Textarea(attrs={"rows": 4}),
            "priorities": forms.Textarea(attrs={"rows": 4}),
            "community_roles": forms.Textarea(attrs={"rows": 3}),
            "campaign_readiness": forms.Textarea(attrs={"rows": 3}),
            "phone": forms.TextInput(attrs={"inputmode": "tel", "placeholder": "7xxx xxxx"}),
            "photo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "cv": forms.ClearableFileInput(attrs={"accept": ".pdf,image/*"}),
            "nid_copy": forms.ClearableFileInput(attrs={"accept": ".pdf,image/*"}),
            "police_clearance": forms.ClearableFileInput(attrs={"accept": ".pdf,image/*"}),
        }

    def __init__(self, *args, election_date=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.election_date = election_date
        el = self.fields["electorate"]
        el.queryset = el.queryset.select_related("province")
        el.empty_label = "Choose the seat you want to contest"
        self.fields["home_province"].empty_label = "Choose province"
        for name in ("declared_eligible", "consent_vetting", "declared_true"):
            self.fields[name].required = True

    def electorate_groups(self):
        """[(province name, [(id, label), ...]), ...] for an <optgroup> select."""
        groups = {}
        for e in self.fields["electorate"].queryset.order_by("province__name", "electorate_type", "name"):
            label = e.name if e.electorate_type == "OPEN" else f"{e.name} (Regional)"
            groups.setdefault(e.province.name, []).append((str(e.pk), label))
        return sorted(groups.items())

    # Field checks ---------------------------------------------------------
    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Spam check failed.")
        return ""

    def clean_phone(self):
        digits = "".join(c for c in self.cleaned_data["phone"] if c.isdigit())
        if digits.startswith("675"):
            digits = digits[3:]
        if len(digits) not in (7, 8):
            raise forms.ValidationError("Enter a PNG number, e.g. 7xxx xxxx.")
        return digits

    def clean_photo(self):
        f = self.cleaned_data.get("photo")
        if f and f.size > MAX_PHOTO_MB * 1024 * 1024:
            raise forms.ValidationError(f"Photo is larger than {MAX_PHOTO_MB} MB.")
        if f and hasattr(f, "content_type"):
            try:
                return reencode_photo(f)
            except Exception:
                raise forms.ValidationError("That photo could not be read. Try a JPG.")
        return f

    def clean_cv(self):
        return _check_doc(self.cleaned_data.get("cv"), "CV")

    def clean_nid_copy(self):
        return _check_doc(self.cleaned_data.get("nid_copy"), "NID copy")

    def clean_police_clearance(self):
        return _check_doc(self.cleaned_data.get("police_clearance"), "Police clearance")

    def clean(self):
        cd = super().clean()
        dob = cd.get("date_of_birth")
        if dob:
            on = self.election_date or timezone.localdate()
            age = on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))
            if age < MIN_AGE:
                self.add_error("date_of_birth",
                               f"Candidates must be at least {MIN_AGE} on polling day.")
        status = cd.get("party_status")
        if status == CandidateApplication.PartyStatus.OTHER:
            if not cd.get("other_party_name"):
                self.add_error("other_party_name", "Name the party you belong to.")
            if not cd.get("will_resign_other_party"):
                self.add_error("will_resign_other_party",
                               "You must agree to resign from your current party.")
        if cd.get("contested_before") and not cd.get("previous_contests"):
            self.add_error("previous_contests", "List the elections you contested.")
        sig, name = cd.get("signature_name", ""), cd.get("full_name", "")
        if sig and name and sig.strip().lower() != name.strip().lower():
            self.add_error("signature_name", "Type your full name exactly as above.")
        return cd


class StatusLookupForm(forms.Form):
    reference = forms.CharField(max_length=20, widget=forms.TextInput(
        attrs={"placeholder": "PANGU-27-XXXXXX", "autocapitalize": "characters"}))
    phone = forms.CharField(max_length=20, widget=forms.TextInput(
        attrs={"inputmode": "tel", "placeholder": "Phone used on the application"}))

    def clean_reference(self):
        return self.cleaned_data["reference"].strip().upper()

    def clean_phone(self):
        digits = "".join(c for c in self.cleaned_data["phone"] if c.isdigit())
        return digits[3:] if digits.startswith("675") else digits


SCORE_CHOICES = [(i, str(i)) for i in range(1, 6)]


class ReviewForm(forms.ModelForm):
    class Meta:
        model = ApplicationReview
        fields = ["recommendation", "integrity", "community_standing", "winnability",
                  "policy_alignment", "campaign_readiness", "comments"]
        widgets = {k: forms.RadioSelect(choices=SCORE_CHOICES)
                   for k, _ in ApplicationReview.CRITERIA}
        widgets["comments"] = forms.Textarea(attrs={"rows": 3})


class DecisionForm(forms.Form):
    to_status = forms.ChoiceField(choices=CandidateApplication.Status.choices)
    applicant_message = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Optional. The applicant sees this on the status page.")
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}),
                           help_text="Internal note for the audit trail.")
    interview_at = forms.DateTimeField(required=False, widget=forms.DateTimeInput(
        attrs={"type": "datetime-local"}))
    interview_place = forms.CharField(required=False, max_length=160)

    def __init__(self, *args, application=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.application = application
        allowed = application.allowed_transitions() if application else []
        labels = dict(CandidateApplication.Status.choices)
        self.fields["to_status"].choices = [(s, labels[s]) for s in allowed]

    def clean(self):
        cd = super().clean()
        app, to = self.application, cd.get("to_status")
        S = CandidateApplication.Status
        if to == S.APPROVED:
            rival = app.endorsed_rival()
            if rival:
                raise forms.ValidationError(
                    f"{rival.full_name} ({rival.reference}) is already endorsed for "
                    f"{app.electorate}. Withdraw that endorsement first.")
        if to == S.INTERVIEW and not cd.get("interview_at"):
            self.add_error("interview_at", "Set the interview date and time.")
        if to in (S.REJECTED, S.WITHDRAWN) and not cd.get("note"):
            self.add_error("note", "Record the reason in the internal note.")
        return cd
