from django.contrib import admin

from .models import ApplicationEvent, ApplicationReview, CandidateApplication


class ReviewInline(admin.TabularInline):
    model = ApplicationReview
    extra = 0
    readonly_fields = ("reviewer", "reviewer_role", "recommendation", "integrity",
                       "community_standing", "winnability", "policy_alignment",
                       "campaign_readiness", "comments", "created_at")
    can_delete = False


class EventInline(admin.TabularInline):
    model = ApplicationEvent
    extra = 0
    readonly_fields = ("at", "actor", "from_status", "to_status", "note")
    can_delete = False


@admin.register(CandidateApplication)
class CandidateApplicationAdmin(admin.ModelAdmin):
    list_display = ("reference", "full_name", "electorate", "status", "candidate_number", "flagged", "created_at")
    list_filter = ("status", "flagged", "gender", "party_status", "electorate__province")
    search_fields = ("reference", "candidate_number", "full_name", "phone", "nid_number")
    readonly_fields = ("id", "reference", "created_at", "updated_at", "submitted_ip",
                       "decided_by", "decided_at", "letter_number", "candidate_number",
                       "id_card_printed_at")
    inlines = [ReviewInline, EventInline]
    date_hierarchy = "created_at"

    def has_delete_permission(self, request, obj=None):
        # Applications are an audit record: withdraw or reject, don't delete.
        return request.user.is_superuser


@admin.register(ApplicationReview)
class ApplicationReviewAdmin(admin.ModelAdmin):
    list_display = ("application", "reviewer", "recommendation", "total", "created_at")
    list_filter = ("recommendation",)
