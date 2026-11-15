from django import forms

from apps.accounts.models import StaffProfile
from apps.members.utils import PhotoError, clean_member_photo


class StaffCardForm(forms.ModelForm):
    class Meta:
        model = StaffProfile
        fields = ["photo", "card_status", "valid_until"]
        widgets = {
            "valid_until": forms.DateInput(attrs={"type": "date"}),
            "photo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }

    def clean_photo(self):
        f = self.cleaned_data.get("photo")
        if f and hasattr(f, "content_type"):   # a new upload, not the stored file
            try:
                return clean_member_photo(f, max_bytes=8 * 1024 * 1024, size_px=400)
            except PhotoError as e:
                raise forms.ValidationError(str(e))
        return f
