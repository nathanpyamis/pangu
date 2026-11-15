from django.contrib import admin
from django.shortcuts import redirect
from django.utils import timezone

from .models import ContactMessage, Leader, NewsPost, PartyProfile, PolicyDocument


@admin.register(PartyProfile)
class PartyProfileAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Party", {"fields": ("name", "short_name", "tagline", "founded", "logo")}),
        ("Home page", {"fields": ("rotating_lines", "intro", "header_image", "header_caption", "about")}),
        ("Election & candidate intake", {"fields": ("election_name", "election_date", "applications_open",
                                                    "applications_close")}),
        ("Endorsement letters", {"fields": ("signatory_name", "signatory_title")}),
        ("Contact & social", {"fields": ("office_address", "phone", "email",
                                         "facebook_url", "tiktok_url", "youtube_url", "x_url")}),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        PartyProfile.load()
        return redirect("admin:cms_partyprofile_change", 1)


@admin.register(Leader)
class LeaderAdmin(admin.ModelAdmin):
    list_display = ("name", "title", "order", "is_visible")
    list_editable = ("order", "is_visible")


@admin.register(NewsPost)
class NewsPostAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "is_published", "published_at")
    list_filter = ("kind", "is_published")
    search_fields = ("title", "body")
    prepopulated_fields = {"slug": ("title",)}

    def save_model(self, request, obj, form, change):
        if obj.is_published and not obj.published_at:
            obj.published_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(PolicyDocument)
class PolicyDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "pillar", "order", "is_published")
    list_editable = ("order", "is_published")
    list_filter = ("pillar",)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "phone_or_email", "subject", "received_at", "is_handled")
    list_filter = ("is_handled",)
    list_editable = ("is_handled",)
    readonly_fields = ("name", "phone_or_email", "subject", "message", "received_at")
