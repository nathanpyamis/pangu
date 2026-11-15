from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from .models import StaffProfile, User

ROLE_HELP = ("Field Agent: needs an electorate. Provincial Coordinator: needs a province. "
             "National Executive: no area needed (sees everything).")


class _PartyFieldsMixin:
    """Readable electorate list ("Morobe – Lae Open") and role help on both user forms."""

    def _tidy_party_fields(self):
        if "role" in self.fields:
            self.fields["role"].help_text = ROLE_HELP
        if "assigned_electorate" in self.fields:
            f = self.fields["assigned_electorate"]
            f.queryset = f.queryset.select_related("province").order_by("province__name", "electorate_type", "name")
            f.label_from_instance = lambda e: f"{e.province.name} – {e.name}"
            f.help_text = "Field agents only. The province is filled in from the electorate."
        if "assigned_province" in self.fields:
            self.fields["assigned_province"].help_text = "Provincial coordinators. Leave empty for executives."


class PartyUserCreationForm(_PartyFieldsMixin, AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "phone_number",
                  "role", "assigned_province", "assigned_electorate")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tidy_party_fields()


class PartyUserChangeForm(_PartyFieldsMixin, UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tidy_party_fields()


class StaffProfileInline(admin.StackedInline):
    model = StaffProfile
    can_delete = False
    extra = 0
    fields = ("staff_number", "photo", "card_status", "valid_until", "id_card_printed", "id_card_printed_at")
    readonly_fields = ("staff_number", "id_card_printed_at")


@admin.register(User)
class PartyUserAdmin(UserAdmin):
    form = PartyUserChangeForm
    add_form = PartyUserCreationForm
    list_display = ("username", "get_full_name", "role", "assigned_province", "assigned_electorate", "is_active")
    list_filter = ("role", "assigned_province", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("Party role", {"fields": ("phone_number", "role", "assigned_province", "assigned_electorate")}),
    )
    # The Add page asks for the role and area up front, so a new field agent
    # can be saved in one step (before, the role check rejected the form).
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Name and party role", {
            "classes": ("wide",),
            "fields": ("first_name", "last_name", "phone_number",
                       "role", "assigned_province", "assigned_electorate"),
        }),
    )
    inlines = [StaffProfileInline]
    search_fields = ("username", "first_name", "last_name", "email")

    def get_inlines(self, request, obj):
        # The staff ID card is filled in after the account exists.
        return self.inlines if obj else []

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Field agents and coordinators get a staff card record (and number) straight away.
        if obj.role in (User.Role.AGENT, User.Role.COORDINATOR):
            profile, _ = StaffProfile.objects.get_or_create(user=obj)
            profile.ensure_number()


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "staff_number", "role", "area", "card_status", "id_card_printed")
    list_filter = ("card_status", "id_card_printed", "user__role", "user__assigned_province")
    search_fields = ("staff_number", "user__username", "user__first_name", "user__last_name")
    readonly_fields = ("id", "staff_number", "created_at", "updated_at", "id_card_printed_at")
    autocomplete_fields = ("user",)

    @admin.display(description="Role")
    def role(self, obj):
        return obj.user.get_role_display()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.ensure_number()
