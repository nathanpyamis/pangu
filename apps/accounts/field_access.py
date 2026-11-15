"""
Who may use the field agent app (/agent/) to register members.

Accounts are only ever created by an administrator in /admin/ (there is no
sign-up page). On top of that, every login, every token refresh and every
sync checks field_access_problem(), so access stops as soon as an admin:

    - disables the login (Admin -> Users -> untick "Active"), or
    - suspends the officer's ID card or lets it pass its "valid until" date
      (Portal -> Field officers, or Admin -> Staff ID cards), or
    - removes the officer's assigned electorate / province.

Records already saved on the officer's phone are kept there, never lost; they
sync once access is restored, or a coordinator can take over the device.
"""
from django.utils import timezone
from rest_framework import exceptions, serializers
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import StaffProfile, User

STOPPED = "Your access to member registration has been stopped. Contact your provincial coordinator."


def field_access_problem(user):
    """None if this user may register members, otherwise the reason in plain words."""
    if user is None or not user.is_active:
        return STOPPED
    if user.is_exec:
        return None
    if user.role == User.Role.AGENT and not user.assigned_electorate_id:
        return "Your account has no electorate assigned yet. Contact your provincial coordinator."
    if user.role == User.Role.COORDINATOR and not user.assigned_province_id:
        return "Your account has no province assigned yet. Contact the party secretariat."
    if user.role not in (User.Role.AGENT, User.Role.COORDINATOR):
        return STOPPED
    profile = StaffProfile.objects.filter(user=user).first()
    if profile:
        if profile.card_status == StaffProfile.CardStatus.SUSPENDED:
            return STOPPED
        if profile.valid_until and profile.valid_until < timezone.localdate():
            return "Your field officer card has expired. Contact your provincial coordinator."
    return None


class FieldLoginSerializer(TokenObtainPairSerializer):
    """Username + password, then the field access check, before any token is issued."""

    def validate(self, attrs):
        data = super().validate(attrs)          # wrong password -> 401 as before
        problem = field_access_problem(self.user)
        if problem:
            raise exceptions.PermissionDenied(problem)
        data["role"] = "EXEC" if self.user.is_exec else self.user.role
        return data


class FieldRefreshSerializer(TokenRefreshSerializer):
    """A saved 30-day token stops working the moment access is withdrawn."""

    def validate(self, attrs):
        try:
            refresh = RefreshToken(attrs["refresh"])
        except Exception:
            raise InvalidToken("Session expired. Log in again.")
        user = User.objects.filter(pk=refresh.payload.get(jwt_settings.USER_ID_CLAIM)).first()
        if field_access_problem(user):
            raise InvalidToken(STOPPED)
        return super().validate(attrs)


class LoginRateThrottle(AnonRateThrottle):
    """
    Slows password guessing: 10 attempts a minute for one username from one
    network address. Keyed on the username too, because PNG mobile networks
    put many phones behind one address, and a training day can have a whole
    room of agents logging in on the same wifi.
    """
    scope = "login"

    def get_cache_key(self, request, view):
        username = str(request.data.get("username", "")).strip().lower()[:150]
        return self.cache_format % {"scope": self.scope,
                                    "ident": f"{self.get_ident(request)}:{username}"}


class FieldLoginView(TokenObtainPairView):
    serializer_class = FieldLoginSerializer
    throttle_classes = [LoginRateThrottle]


class FieldRefreshView(TokenRefreshView):
    serializer_class = FieldRefreshSerializer
