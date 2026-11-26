import ipaddress

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


def get_request_ip(request):
    """Return the peer IP, trusting X-Real-IP only from configured proxy peers."""
    remote_addr = request.META.get("REMOTE_ADDR", "")
    try:
        peer_ip = ipaddress.ip_address(remote_addr)
    except ValueError:
        return None

    trusted_ranges = getattr(settings, "WORKTRACK_TRUSTED_PROXY_IPS", ["127.0.0.1/32", "::1/128"])
    trusted_peer = False
    for value in trusted_ranges:
        try:
            if peer_ip in ipaddress.ip_network(value, strict=False):
                trusted_peer = True
                break
        except ValueError:
            continue

    if trusted_peer:
        forwarded_ip = request.META.get("HTTP_X_REAL_IP", "").strip()
        try:
            return str(ipaddress.ip_address(forwarded_ip)) if forwarded_ip else str(peer_ip)
        except ValueError:
            pass
    return str(peer_ip)


class EnforceInitialPasswordChangeMiddleware:
    """Require provisioned users to replace their temporary password once."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            try:
                must_change = user.employee_profile.must_change_password
            except Exception:
                must_change = False
            allowed_paths = (reverse('eqrApp:change_password'), reverse('eqrApp:logout'))
            if must_change and request.path not in allowed_paths and not request.path.startswith('/static/'):
                return redirect('eqrApp:change_password')
        return self.get_response(request)


class SystemEventLoggingMiddleware:
    """Record application HTTP errors for the Administrator's system log."""

    TRACKED_STATUSES = {400, 403, 404, 429, 500, 502, 503, 504}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code in self.TRACKED_STATUSES and not request.path.startswith(('/static/', '/media/')):
            try:
                from .models import SystemEventLog

                user = getattr(request, 'user', None)
                actor = user if getattr(user, 'is_authenticated', False) else None
                severity = 'error' if response.status_code >= 500 else ('warning' if response.status_code in (400, 403, 429) else 'info')
                descriptions = {
                    400: 'Bad request', 403: 'Access denied', 404: 'Page not found',
                    429: 'Rate limit or login lockout triggered', 500: 'Internal server error',
                    502: 'Bad gateway', 503: 'Service unavailable', 504: 'Gateway timeout',
                }
                ip_address = get_request_ip(request)
                SystemEventLog.objects.create(
                    event_type='http_error',
                    severity=severity,
                    message=f"{descriptions.get(response.status_code, 'HTTP error')} ({response.status_code})",
                    request_path=request.path[:500],
                    http_method=request.method[:12],
                    status_code=response.status_code,
                    actor=actor,
                    ip_address=ip_address or None,
                )
            except Exception:
                # Logging must never convert an otherwise valid response into an error.
                pass
        return response


class KioskSessionLockMiddleware:
    """Keep an activated kiosk session inside the scanner until an admin reauthenticates to exit.

    This is a server-side navigation lock: requests to dashboards, account pages, logout, and
    other application routes are redirected to the kiosk. It does not replace OS/browser kiosk
    mode, which is needed to restrict browser chrome, tab closing, or desktop access.
    """

    KIOSK_ALLOWED_PATHS = {
        "/accounts/attendance/kiosk/",
        "/accounts/attendance/kiosk/run/",
        "/accounts/attendance/kiosk/scan/",
        "/accounts/attendance/kiosk/exit/",
        "/accounts/attendance/kiosk/settings/unlock/",
        "/accounts/attendance/kiosk/settings/lock/",
        "/accounts/attendance/kiosk/settings/manual/",
        "/accounts/attendance/kiosk/settings/edit/",
        "/accounts/attendance/kiosk/settings/history/",
        "/favicon.ico",
    }
    SESSION_ACTIVE_KEY = "worktrack_kiosk_active"
    SESSION_USER_KEY = "worktrack_kiosk_user_id"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        session = getattr(request, "session", None)
        user = getattr(request, "user", None)
        if session is not None and session.get(self.SESSION_ACTIVE_KEY):
            from .roles import get_user_role

            expected_user_id = session.get(self.SESSION_USER_KEY)
            valid_kiosk_owner = (
                user is not None
                and user.is_authenticated
                and user.pk == expected_user_id
                and get_user_role(user) == "admin"
            )
            if not valid_kiosk_owner:
                session.pop(self.SESSION_ACTIVE_KEY, None)
                session.pop(self.SESSION_USER_KEY, None)
                session.pop("worktrack_kiosk_started_at", None)
            else:
                path = request.path_info or request.path
                static_url = getattr(settings, "STATIC_URL", "/static/")
                is_static = path.startswith(static_url) or path.startswith("/static/")
                if path not in self.KIOSK_ALLOWED_PATHS and not is_static:
                    response = redirect("eqrApp:attendance_kiosk_run")
                    response["Cache-Control"] = "no-store, private"
                    response["Pragma"] = "no-cache"
                    return response

        response = self.get_response(request)
        if session is not None and session.get(self.SESSION_ACTIVE_KEY):
            response["Cache-Control"] = "no-store, private"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        return response
