from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        AGENT = "AGENT", "Field Agent"
        COORDINATOR = "COORDINATOR", "Provincial Coordinator"
        EXEC = "EXEC", "National Executive"

    phone_number = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.AGENT)
    assigned_province = models.ForeignKey(
        "geo.Province", null=True, blank=True, on_delete=models.SET_NULL, related_name="staff"
    )
    assigned_electorate = models.ForeignKey(
        "geo.Electorate", null=True, blank=True, on_delete=models.SET_NULL, related_name="agents"
    )

    def clean(self):
        super().clean()
        if self.role == self.Role.AGENT and not self.assigned_electorate_id:
            raise ValidationError({"assigned_electorate":
                                   "Field agents must be assigned an electorate. Choose one, or change the role."})
        if self.role == self.Role.COORDINATOR and not self.assigned_province_id:
            raise ValidationError({"assigned_province":
                                   "Provincial coordinators must be assigned a province."})
        if self.assigned_electorate_id:
            # Keep province consistent with electorate
            self.assigned_province_id = self.assigned_electorate.province_id

    @property
    def is_exec(self):
        return self.role == self.Role.EXEC or self.is_superuser

    @property
    def is_coordinator(self):
        return self.role == self.Role.COORDINATOR

    @property
    def is_agent(self):
        return self.role == self.Role.AGENT


# ---------------------------------------------------------------------------
# Staff ID cards (field agents and provincial coordinators)
# ---------------------------------------------------------------------------

import secrets  # noqa: E402
import uuid  # noqa: E402

from django.conf import settings  # noqa: E402
from django.db import IntegrityError, transaction  # noqa: E402
from django.utils import timezone  # noqa: E402


def staff_photo_path(instance, filename):
    return f"staff/{instance.pk}.jpg"


class StaffProfile(models.Model):
    """
    The card side of a staff account. Created from Portal → Staff or the admin.
    Suspending a card makes its QR check say "not valid" at once, without
    touching the login (deactivate the user as well to stop them logging in).
    """

    class CardStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    staff_number = models.CharField(max_length=24, unique=True, null=True, blank=True)
    photo = models.ImageField(upload_to=staff_photo_path, blank=True)
    card_status = models.CharField(max_length=10, choices=CardStatus.choices,
                                   default=CardStatus.ACTIVE)
    valid_until = models.DateField(null=True, blank=True,
                                   help_text="Leave empty for no expiry (e.g. until after the 2027 return of writs).")
    id_card_printed = models.BooleanField(default=False)
    id_card_printed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__last_name", "user__first_name"]
        verbose_name = "staff ID card"

    def __str__(self):
        return f"{self.display_name} ({self.staff_number or 'no number'})"

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def area(self):
        u = self.user
        if u.assigned_electorate_id:
            return str(u.assigned_electorate.name)
        if u.assigned_province_id:
            return f"{u.assigned_province.name} Province"
        return "National"

    @property
    def province_name(self):
        return self.user.assigned_province.name if self.user.assigned_province_id else "National"

    @property
    def is_valid(self):
        if not self.user.is_active or self.card_status != self.CardStatus.ACTIVE:
            return False
        return not (self.valid_until and self.valid_until < timezone.localdate())

    def ensure_number(self):
        """Allot PANGU-STF-MOR-9Q2D once; the province code comes from the assignment."""
        if self.staff_number:
            return self.staff_number
        code = (self.user.assigned_province.code if self.user.assigned_province_id else "NAT").upper()
        prefix = getattr(settings, "PARTY_CODE", "PANGU")
        for _ in range(10):
            self.staff_number = f"{prefix}-STF-{code}-{secrets.token_hex(2).upper()}"
            try:
                with transaction.atomic():
                    self.save()
                return self.staff_number
            except IntegrityError:
                self.staff_number = None
        raise RuntimeError("Could not allocate a unique staff number")
