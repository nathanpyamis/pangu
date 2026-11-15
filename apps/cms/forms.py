from datetime import date

from django import forms

from apps.geo.models import Electorate
from apps.members.serializers import check_location
from apps.members.utils import normalize_name, normalize_nid, normalize_png_phone

from .models import ContactMessage


class HoneypotMixin(forms.Form):
    # Hidden from people by CSS; bots fill it in.
    website = forms.CharField(required=False)

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Spam detected.")
        return ""


class JoinForm(HoneypotMixin):
    full_name = forms.CharField(max_length=150)
    gender = forms.ChoiceField(choices=[("M", "Male"), ("F", "Female")])
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    nid_number = forms.CharField(max_length=30, required=False)
    phone_number = forms.CharField(max_length=20, required=False)
    electorate = forms.ModelChoiceField(queryset=Electorate.objects.select_related("province"))
    llg_ward = forms.CharField(max_length=120, required=False)
    village_or_street = forms.CharField(max_length=150, required=False)
    residential_address = forms.CharField(
        max_length=255,
        error_messages={"required": "Enter where you live: section & lot, street or landmark, suburb or village."},
    )
    # Filled by the map / "Use my location" button; optional.
    latitude = forms.DecimalField(max_digits=9, decimal_places=6, required=False)
    longitude = forms.DecimalField(max_digits=9, decimal_places=6, required=False)
    location_accuracy_m = forms.IntegerField(required=False, min_value=0)
    location_source = forms.ChoiceField(choices=[("", ""), ("GPS", "GPS"), ("MAP", "MAP")], required=False)
    photo = forms.ImageField(required=False)
    consent = forms.BooleanField(
        error_messages={"required": "Please confirm you agree to join and to have your details stored."}
    )

    def clean_full_name(self):
        v = normalize_name(self.cleaned_data["full_name"])
        if len(v) < 3:
            raise forms.ValidationError("Enter your full name.")
        return v

    def clean_nid_number(self):
        return normalize_nid(self.cleaned_data.get("nid_number"))

    def clean_phone_number(self):
        v = normalize_png_phone(self.cleaned_data.get("phone_number"))
        if v and len(v) not in (7, 8):
            raise forms.ValidationError("Enter a valid PNG phone number, e.g. 7xxx xxxx.")
        return v

    def clean_date_of_birth(self):
        v = self.cleaned_data.get("date_of_birth")
        if v:
            t = date.today()
            age = t.year - v.year - ((t.month, t.day) < (v.month, v.day))
            if age < 18:
                raise forms.ValidationError("Members must be 18 or older.")
            if age > 120:
                raise forms.ValidationError("Check the date of birth.")
        return v

    def clean_residential_address(self):
        v = " ".join(self.cleaned_data["residential_address"].split())
        if len(v) < 5:
            raise forms.ValidationError("Give a little more detail so a coordinator can find you.")
        return v

    def clean(self):
        data = super().clean()
        if not data.get("nid_number") and not data.get("phone_number"):
            raise forms.ValidationError("Enter your NID number or a phone number so we can contact you.")
        problem = check_location(data)
        if problem:
            self.add_error("residential_address", problem)
        if data.get("latitude") is None or data.get("longitude") is None:
            data["latitude"] = data["longitude"] = data["location_accuracy_m"] = None
            data["location_source"] = ""
        return data


class ContactForm(HoneypotMixin, forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ["name", "phone_or_email", "subject", "message"]
