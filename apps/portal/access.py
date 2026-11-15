"""
Who may see what in the staff portal. One place, used by every portal view.

    Executive (EXEC or superuser)  everything, nationwide; makes decisions
    Provincial Coordinator         own province only; reviews and verifies
    Field Agent                    no portal: sent to the agent app (/agent/)
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

AGENT_APP_URL = "/agent/"


def is_exec(user):
    return bool(user and user.is_authenticated and user.is_exec)


def is_coordinator(user):
    return bool(user and user.is_authenticated and not user.is_exec and user.is_coordinator)


def is_portal_user(user):
    return is_exec(user) or is_coordinator(user)


def landing_url(user):
    if is_portal_user(user):
        return "/portal/"
    if user.is_authenticated and user.is_agent:
        return AGENT_APP_URL
    return "/"


def portal_required(view):
    """Executives and coordinators. Field agents are sent to their app."""
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_portal_user(request.user):
            if request.user.is_agent:
                return redirect(AGENT_APP_URL)
            raise PermissionDenied("Executives and provincial coordinators only.")
        return view(request, *args, **kwargs)
    return wrapped


def exec_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_exec(request.user):
            raise PermissionDenied("National Executive only.")
        return view(request, *args, **kwargs)
    return wrapped


def scope_province(qs, user, province_field):
    """Executives: everything. Coordinators: rows in their province. Others: none."""
    if is_exec(user):
        return qs
    if is_coordinator(user) and user.assigned_province_id:
        return qs.filter(**{province_field: user.assigned_province_id})
    return qs.none()
