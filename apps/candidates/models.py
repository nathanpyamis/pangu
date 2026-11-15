import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Private file storage
# ---------------------------------------------------------------------------
# Candidate documents (NID copy, police clearance, CV, photo) are personal
# data. They are kept OUTSIDE MEDIA_ROOT so the public /media/ URL can never
# serve them; reviewers download them through a login-protected view.
# On Render, point PRIVATE_MEDIA_ROOT at a persistent disk (or swap this for a
# private S3 bucket via django-storages).

def private_storage():
    location = getattr(
        settings, "PRIVATE_MEDIA_ROOT", Path(settings.BASE_DIR) / "private_media"
    )
    return FileSystemStorage(location=str(location), base_url=None)


def _doc_path(instance, filename):
    ext = Path(filename).suffix.lower()[:6] or ".bin"
    return f"candidates/{instance.id}/{secrets.token_hex(8)}{ext}"


def make_reference():
    # Application reference, e.g. PANGU-27-7F3K9Q (no 0/O/1/I: easy to read over the phone)
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "PANGU-27-" + "".join(secrets.choice(alphabet) for _ in range(6))


# ---------------------------------------------------------------------------
# Candidate application
# ---------------------------------------------------------------------------

class CandidateApplication(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        UNDER_REVIEW = "UNDER_REVIEW", "Under review"
        SHORTLISTED = "SHORTLISTED", "Shortlisted"
        INTERVIEW = "INTERVIEW", "Interview scheduled"
        APPROVED = "APPROVED", "Endorsed"
        REJECTED = "REJECTED", "Not endorsed"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    OPEN_STATUSES = (Status.SUBMITTED, Status.UNDER_REVIEW,
                     Status.SHORTLISTED, Status.INTERVIEW)
    FINAL_STATUSES = (Status.APPROVED, Status.REJECTED, Status.WITHDRAWN)

    # Allowed status moves. Executives only.
    TRANSITIONS = {
        Status.SUBMITTED: [Status.UNDER_REVIEW, Status.REJECTED, Status.WITHDRAWN],
        Status.UNDER_REVIEW: [Status.SHORTLISTED, Status.REJECTED, Status.WITHDRAWN],
        Status.SHORTLISTED: [Status.INTERVIEW, Status.APPROVED, Status.REJECTED, Status.WITHDRAWN],
        Status.INTERVIEW: [Status.APPROVED, Status.REJECTED, Status.WITHDRAWN],
        Status.APPROVED: [Status.WITHDRAWN],
        Status.REJECTED: [Status.UNDER_REVIEW],   # re-open on appeal
        Status.WITHDRAWN: [],
    }

    class Gender(models.TextChoices):
        FEMALE = "F", "Female"
        MALE = "M", "Male"

    class Education(models.TextChoices):
        GRADE10 = "G10", "Grade 10"
        GRADE12 = "G12", "Grade 12"
        CERT = "CERT", "Certificate"
        DIPLOMA = "DIP", "Diploma"
        BACHELOR = "BACH", "Bachelor's degree"
        POSTGRAD = "PG", "Postgraduate"
        OTHER = "OTH", "Other"

    class PartyStatus(models.TextChoices):
        PANGU = "PANGU", "Already a Pangu member"
        NONE = "NONE", "Not a member of any party"
        OTHER = "OTHER", "Member of another party"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=20, unique=True, default=make_reference, editable=False)

    # --- Personal -----------------------------------------------------------
    full_name = models.CharField(max_length=120)
    preferred_name = models.CharField(max_length=60, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices)
    date_of_birth = models.DateField()
    nid_number = models.CharField("NID number", max_length=30, blank=True,
                                  help_text="National ID number, if you have one.")
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    home_province = models.ForeignKey("geo.Province", on_delete=models.PROTECT,
                                      related_name="+")
    village = models.CharField("Home village / ward", max_length=120)
    current_address = models.CharField(max_length=200, blank=True)

    # --- Seat sought -------------------------------------------------------
    electorate = models.ForeignKey("geo.Electorate", on_delete=models.PROTECT,
                                   related_name="candidate_applications")
    years_resident = models.PositiveSmallIntegerField(
        "Years lived in this electorate", validators=[MaxValueValidator(100)])
    born_in_electorate = models.BooleanField(default=False)

    # --- Background --------------------------------------------------------
    occupation = models.CharField(max_length=120)
    employer = models.CharField(max_length=120, blank=True)
    education = models.CharField(max_length=4, choices=Education.choices)
    qualifications = models.TextField(blank=True)
    contested_before = models.BooleanField(default=False)
    previous_contests = models.TextField(blank=True,
                                         help_text="Year, seat, party and result for each.")
    party_status = models.CharField(max_length=5, choices=PartyStatus.choices)
    pangu_member_number = models.CharField(max_length=40, blank=True)
    other_party_name = models.CharField(max_length=120, blank=True)
    will_resign_other_party = models.BooleanField(default=False)

    # --- Statement ---------------------------------------------------------
    why_pangu = models.TextField("Why do you want to stand for Pangu?")
    priorities = models.TextField("Your top priorities for the electorate")
    community_roles = models.TextField("Community, church and leadership roles", blank=True)
    campaign_readiness = models.TextField("Campaign team and resources", blank=True)

    # --- Referees ----------------------------------------------------------
    referee1_name = models.CharField(max_length=120)
    referee1_phone = models.CharField(max_length=20)
    referee1_relationship = models.CharField(max_length=80)
    referee2_name = models.CharField(max_length=120)
    referee2_phone = models.CharField(max_length=20)
    referee2_relationship = models.CharField(max_length=80)

    # --- Documents (private storage) --------------------------------------
    photo = models.ImageField(upload_to=_doc_path, storage=private_storage)
    cv = models.FileField("CV / résumé", upload_to=_doc_path, storage=private_storage)
    nid_copy = models.FileField("Copy of NID or birth certificate", upload_to=_doc_path,
                                storage=private_storage, blank=True)
    police_clearance = models.FileField(upload_to=_doc_path, storage=private_storage, blank=True)

    # --- Declaration -------------------------------------------------------
    declared_eligible = models.BooleanField(default=False)
    consent_vetting = models.BooleanField(default=False)
    declared_true = models.BooleanField(default=False)
    signature_name = models.CharField("Type your full name as signature", max_length=120)

    # --- Workflow ----------------------------------------------------------
    status = models.CharField(max_length=14, choices=Status.choices,
                              default=Status.SUBMITTED, db_index=True)
    applicant_message = models.TextField(
        blank=True, help_text="Shown to the applicant on the status page. Keep it short.")
    decision_note = models.TextField(blank=True, help_text="Internal. Not shown to the applicant.")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    letter_number = models.CharField(max_length=30, blank=True)
    candidate_number = models.CharField(max_length=24, unique=True, null=True, blank=True,
                                        help_text="Issued on endorsement; printed on the candidate ID card.")
    id_card_printed = models.BooleanField(default=False)
    id_card_printed_at = models.DateTimeField(null=True, blank=True)
    interview_at = models.DateTimeField(null=True, blank=True)
    interview_place = models.CharField(max_length=160, blank=True)

    # Duplicates are flagged, never deleted (same rule as members).
    flagged = models.BooleanField(default=False)
    flag_reason = models.CharField(max_length=200, blank=True)
    duplicate_of = models.ForeignKey("self", null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")

    submitted_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["electorate", "status"])]

    def __str__(self):
        return f"{self.full_name} – {self.electorate} ({self.reference})"

    # Helpers ---------------------------------------------------------------
    @property
    def province(self):
        return getattr(self.electorate, "province", None)

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    def age_on(self, day):
        dob = self.date_of_birth
        return day.year - dob.year - ((day.month, day.day) < (dob.month, dob.day))

    def allowed_transitions(self):
        return self.TRANSITIONS.get(self.status, [])

    def rivals(self):
        """Other live applications for the same seat."""
        return (CandidateApplication.objects
                .filter(electorate_id=self.electorate_id)
                .exclude(pk=self.pk)
                .exclude(status__in=[self.Status.REJECTED, self.Status.WITHDRAWN]))

    @property
    def card_is_valid(self):
        return self.status == self.Status.APPROVED and bool(self.candidate_number)

    def issue_candidate_number(self):
        """PANGU-CAN-MOR-4F7K, allotted once, on endorsement."""
        if self.candidate_number:
            return self.candidate_number
        prefix = getattr(settings, "PARTY_CODE", "PANGU")
        code = self.electorate.province.code.upper()
        alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
        for _ in range(10):
            number = f"{prefix}-CAN-{code}-" + "".join(secrets.choice(alphabet) for _ in range(4))
            if not CandidateApplication.objects.filter(candidate_number=number).exists():
                self.candidate_number = number
                return number
        raise RuntimeError("Could not allocate a unique candidate number")

    def endorsed_rival(self):
        return self.rivals().filter(status=self.Status.APPROVED).first()

    def average_scores(self):
        reviews = list(self.reviews.all())
        if not reviews:
            return None
        keys = [k for k, _ in ApplicationReview.CRITERIA]
        out = {k: round(sum(getattr(r, k) for r in reviews) / len(reviews), 1) for k in keys}
        out["overall"] = round(sum(out[k] for k in keys) / len(keys), 1)
        return out

    def detect_duplicates(self):
        """Flag (not block) a likely duplicate: same NID, or same name + phone."""
        qs = CandidateApplication.objects.exclude(pk=self.pk)
        match = None
        if self.nid_number:
            match = qs.filter(nid_number__iexact=self.nid_number).first()
            if match:
                self.flag_reason = "Same NID as " + match.reference
        if not match:
            match = qs.filter(full_name__iexact=self.full_name, phone=self.phone).first()
            if match:
                self.flag_reason = "Same name and phone as " + match.reference
        if match:
            self.flagged = True
            self.duplicate_of = match
        return match


class ApplicationReview(models.Model):
    """A scored recommendation. Coordinators and executives can both add one."""

    class Recommendation(models.TextChoices):
        ENDORSE = "ENDORSE", "Endorse"
        CONDITIONAL = "CONDITIONAL", "Endorse with conditions"
        DECLINE = "DECLINE", "Do not endorse"
        ABSTAIN = "ABSTAIN", "Abstain / conflict of interest"

    CRITERIA = [
        ("integrity", "Integrity and character"),
        ("community_standing", "Standing in the community"),
        ("winnability", "Ability to win the seat"),
        ("policy_alignment", "Alignment with party policy"),
        ("campaign_readiness", "Campaign readiness"),
    ]

    application = models.ForeignKey(CandidateApplication, on_delete=models.CASCADE,
                                    related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                 related_name="candidate_reviews")
    reviewer_role = models.CharField(max_length=10, blank=True)
    recommendation = models.CharField(max_length=12, choices=Recommendation.choices)
    integrity = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    community_standing = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    winnability = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    policy_alignment = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    campaign_readiness = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["application", "reviewer"],
                                    name="one_review_per_reviewer"),
        ]

    def __str__(self):
        return f"{self.reviewer} → {self.application.reference}: {self.get_recommendation_display()}"

    @property
    def total(self):
        return sum(getattr(self, k) for k, _ in self.CRITERIA)


class ApplicationEvent(models.Model):
    """Audit trail: every status change and note, who did it and when."""
    application = models.ForeignKey(CandidateApplication, on_delete=models.CASCADE,
                                    related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    from_status = models.CharField(max_length=14, blank=True)
    to_status = models.CharField(max_length=14, blank=True)
    note = models.TextField(blank=True)
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return f"{self.application.reference}: {self.from_status}→{self.to_status}"
