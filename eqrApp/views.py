import os
import csv
import ipaddress
import re
import unicodedata
import calendar as month_calendar
from collections import defaultdict
from datetime import datetime, time, date, timedelta
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.deletion import ProtectedError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Q, Count
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.core import signing
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import EmployeeForm, AdminAccountSupportForm, LeaveApplicationForm, AttendanceRecordForm, KioskCorrectionForm, LeaveBalanceForm, HolidayForm, DEPARTMENT_CHOICES
from .roles import get_user_role
from .models import (
    EmployeeProfile,
    AttendanceRecord,
    LeaveType,
    LeaveApplication,
    LeaveDocument,
    LeaveAction,
    AttendanceAudit,
    LeaveBalance,
    Holiday,
    LeaveDeletionAudit,
    SystemEventLog,
)
from .notifications import send_worktrack_email
from .attendance_qr import build_daily_qr_bundle, validate_daily_qr_token
from .middleware import get_request_ip


ALLOWED_DOCUMENT_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
MAX_DOCUMENT_SIZE = 5 * 1024 * 1024
MAX_DOCUMENT_COUNT = 5
DEFAULT_LATE_TIME = time(9, 0)
QR_RESCAN_INTERVAL = timedelta(seconds=10)


def log_system_event(request, event_type, message, severity='info', status_code=None, details=None):
    """Write a sanitized event for Administrator-only system oversight."""
    user = getattr(request, 'user', None)
    actor = user if getattr(user, 'is_authenticated', False) else None
    ip_address = get_request_ip(request)
    try:
        return SystemEventLog.objects.create(
            event_type=event_type,
            severity=severity,
            message=str(message)[:2000],
            request_path=getattr(request, 'path', '')[:500],
            http_method=getattr(request, 'method', '')[:12],
            status_code=status_code,
            actor=actor,
            ip_address=ip_address or None,
            details=details or {},
        )
    except Exception:
        # Keep the primary workflow available if a log write fails.
        return None


def roles_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            if get_user_role(request.user) not in allowed_roles:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator


def hr_required(view_func):
    # HR owns employee and leave administration; IT administrators are read-only overseers.
    return roles_required('hr')(view_func)


def admin_required(view_func):
    return roles_required('admin')(view_func)


def get_employee_profile(user):
    try:
        return EmployeeProfile.objects.select_related('user', 'manager', 'backup_manager').get(user=user)
    except EmployeeProfile.DoesNotExist:
        return None


def generated_employee_username(first_name, last_name, employee_id=''):
    """Generate the requested lastnamefirstname username, with collision-safe suffixes."""
    raw = f'{last_name}{first_name}'
    normalized = unicodedata.normalize('NFKD', raw).encode('ascii', 'ignore').decode('ascii')
    base = re.sub(r'[^a-zA-Z0-9]', '', normalized).lower()
    if not base:
        base = re.sub(r'[^a-zA-Z0-9]', '', str(employee_id)).lower() or 'employee'
    candidate = base[:150]
    suffix = 2
    while User.objects.filter(username__iexact=candidate).exists():
        suffix_text = str(suffix)
        candidate = f'{base[:150-len(suffix_text)]}{suffix_text}'
        suffix += 1
    return candidate


def ensure_employee_leave_balances(employee, year=None):
    """Create fixed demo entitlements for every active balance-tracked leave type."""
    year = year or timezone.localdate().year
    types = LeaveType.objects.filter(is_active=True, track_balance=True)
    for leave_type in types:
        LeaveBalance.objects.get_or_create(
            employee=employee,
            leave_type=leave_type,
            year=year,
            defaults={'entitled_days': leave_type.default_entitled_days, 'used_days': Decimal('0.00')},
        )


def can_view_leave(user, application):
    role = get_user_role(user)
    if role in ('hr', 'admin'):
        return True
    if application.employee.user_id == user.id:
        return True
    return role == 'supervisor' and user.id in (application.employee.manager_id, application.employee.backup_manager_id)


def leave_requires_supervisor_ack(application):
    """Employee-access accounts must be acknowledged before HR can decide."""
    return application.employee.role == 'employee'


def can_review_as_manager(user, application):
    awaiting_acknowledgment = (
        application.status == 'pending_manager'
        or (
            application.status == 'pending_hr'
            and application.employee.role == 'employee'
            and application.manager_reviewed_at is None
        )
    )
    return (
        get_user_role(user) == 'supervisor'
        and user.id in (application.employee.manager_id, application.employee.backup_manager_id)
        and awaiting_acknowledgment
        and application.employee.user_id != user.id
    )


def valid_uploaded_documents(files):
    """Validate extension, size, and file signature (not only the browser MIME type)."""
    errors = []
    signatures = {
        '.pdf': lambda data: data.startswith(b'%PDF-'),
        '.jpg': lambda data: data.startswith(b'\xff\xd8\xff'),
        '.jpeg': lambda data: data.startswith(b'\xff\xd8\xff'),
        '.png': lambda data: data.startswith(b'\x89PNG\r\n\x1a\n'),
    }
    if len(files) > MAX_DOCUMENT_COUNT:
        errors.append(f'You can attach up to {MAX_DOCUMENT_COUNT} files per request.')
    for uploaded_file in files:
        extension = os.path.splitext(uploaded_file.name)[1].lower()
        if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
            errors.append(f'{uploaded_file.name}: only PDF, JPG, JPEG, and PNG files are accepted.')
        if uploaded_file.size > MAX_DOCUMENT_SIZE:
            errors.append(f'{uploaded_file.name}: each file must be 5 MB or smaller.')
        if extension in signatures:
            header = uploaded_file.read(16)
            uploaded_file.seek(0)
            if not signatures[extension](header):
                errors.append(f'{uploaded_file.name}: the file content does not match its extension.')
    return errors


def request_kiosk_ip_allowed(request):
    """Apply the optional IP allowlist on top of the administrator-only role check."""
    configured_ranges = getattr(settings, 'WORKTRACK_KIOSK_IP_RANGES', [])
    if not configured_ranges:
        return True
    raw_ip = get_request_ip(request) or ''
    try:
        address = ipaddress.ip_address(raw_ip)
        return any(address in ipaddress.ip_network(value, strict=False) for value in configured_ranges)
    except ValueError:
        return False


def attendance_snapshot(record):
    return {
        'attendance_date': record.attendance_date.isoformat(),
        'check_in': record.check_in.isoformat() if record.check_in else None,
        'check_out': record.check_out.isoformat() if record.check_out else None,
        'status': record.status,
        'source': record.source,
        'remarks': record.remarks,
    }


def leave_days_in_range(start_date, end_date, is_half_day=False):
    if is_half_day:
        if start_date != end_date or start_date.weekday() >= 5:
            return Decimal('0.00')
        if Holiday.objects.filter(date=start_date, is_active=True).exists():
            return Decimal('0.00')
        return Decimal('0.50')
    holidays = set(Holiday.objects.filter(
        is_active=True, date__gte=start_date, date__lte=end_date
    ).values_list('date', flat=True))
    total = 0
    cursor = start_date
    while cursor <= end_date:
        if cursor.weekday() < 5 and cursor not in holidays:
            total += 1
        cursor += timedelta(days=1)
    return Decimal(total)


def leave_year_segments(start_date, end_date, is_half_day=False):
    if is_half_day:
        return [(start_date.year, start_date, end_date, True)]
    result = []
    first_year = start_date.year
    last_year = end_date.year
    for year in range(first_year, last_year + 1):
        segment_start = max(start_date, date(year, 1, 1))
        segment_end = min(end_date, date(year, 12, 31))
        result.append((year, segment_start, segment_end, False))
    return result


def leave_balance_errors(employee, leave_type, start_date, end_date, is_half_day=False):
    if not leave_type.track_balance:
        return []
    # Initialize the fixed catalogue balances for every calendar year covered by
    # the request, including future years requested in advance.
    for entitlement_year, _segment_start, _segment_end, _half_day in leave_year_segments(
        start_date, end_date, is_half_day
    ):
        ensure_employee_leave_balances(employee, entitlement_year)
    errors = []
    # Reserve every pending request in the same entitlement year, not only
    # requests whose dates overlap the new request being submitted.
    pending = LeaveApplication.objects.filter(
        employee=employee, leave_type=leave_type,
        status__in=['pending_manager', 'pending_hr'],
    )
    for year, segment_start, segment_end, half_day in leave_year_segments(start_date, end_date, is_half_day):
        requested = leave_days_in_range(segment_start, segment_end, half_day)
        if requested <= 0:
            continue
        balance = LeaveBalance.objects.filter(
            employee=employee, leave_type=leave_type, year=year
        ).first()
        if balance is None:
            errors.append(f'No {year} leave balance is configured for {leave_type.name}. Contact HR.')
            continue
        reserved = Decimal('0.00')
        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)
        for existing in pending:
            # Pending reservations must be summed across the full entitlement
            # year, including requests that do not overlap the new date range.
            overlap_start = max(existing.start_date, year_start)
            overlap_end = min(existing.end_date, year_end)
            if overlap_start <= overlap_end:
                existing_half_day = (
                    existing.is_half_day
                    and existing.start_date == existing.end_date
                    and year_start <= existing.start_date <= year_end
                )
                reserved += leave_days_in_range(overlap_start, overlap_end, existing_half_day)
        if balance.available_days - reserved < requested:
            errors.append(
                f'Insufficient {leave_type.name} balance for {year}. '
                f'Available after pending requests: {balance.available_days - reserved} day(s); '
                f'requested: {requested} day(s).'
            )
    return errors


def deduct_leave_balance(application):
    if not application.leave_type.track_balance:
        return
    for year, segment_start, segment_end, half_day in leave_year_segments(
        application.start_date, application.end_date, application.is_half_day
    ):
        amount = leave_days_in_range(segment_start, segment_end, half_day)
        if amount <= 0:
            continue
        balance = LeaveBalance.objects.select_for_update().filter(
            employee=application.employee, leave_type=application.leave_type, year=year
        ).first()
        if balance is None or balance.available_days < amount:
            raise ValidationError(
                f'The configured {year} {application.leave_type.name} balance is insufficient. '
                'HR must review the leave balance before approving this request.'
            )
        balance.used_days += amount
        balance.save(update_fields=['used_days', 'updated_at'])


def sync_approved_leave_attendance(application):
    """Reflect approved leave in attendance without replacing an HR correction."""
    holidays = set(Holiday.objects.filter(
        is_active=True, date__gte=application.start_date, date__lte=application.end_date
    ).values_list('date', flat=True))
    cursor = application.start_date
    while cursor <= application.end_date:
        if cursor.weekday() < 5 and cursor not in holidays:
            record, created = AttendanceRecord.objects.get_or_create(
                employee=application.employee,
                attendance_date=cursor,
                defaults={
                    'status': 'half_day' if application.is_half_day else 'on_leave',
                    'source': 'leave_sync',
                    'remarks': f'Approved {application.leave_type.name} leave.',
                    'recorded_by': application.reviewed_by,
                },
            )
            # Keep manual HR corrections authoritative. For self-service and
            # scheduled records, make the approved leave status explicit while
            # preserving check-in/out timestamps for audit context.
            if not created and record.source != 'hr':
                record.status = 'half_day' if application.is_half_day else 'on_leave'
                record.source = 'leave_sync'
                record.remarks = f'Approved {application.leave_type.name} leave.'
                record.recorded_by = application.reviewed_by
                record.save(update_fields=['status', 'source', 'remarks', 'recorded_by', 'updated_at'])
        cursor += timedelta(days=1)


@require_POST
@login_required
def custom_logout(request):
    log_system_event(request, 'logout', f'User {request.user.get_username()} signed out.', severity='info', status_code=200)
    logout(request)
    messages.success(request, 'You have been signed out.')
    return redirect('eqrApp:login')


def custom_login(request):
    if request.user.is_authenticated:
        return redirect('eqrApp:home')

    next_url = request.GET.get('next') or request.POST.get('next') or ''
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            role = get_user_role(user)
            profile = get_employee_profile(user)
            if not user.is_superuser:
                if role in ('employee', 'supervisor') and profile is None:
                    messages.error(request, 'Your employee profile is unavailable. Please contact HR.')
                    return render(request, 'login.html', {'next': next_url})
                if profile is not None and profile.employment_status != 'active':
                    messages.error(request, 'Your account is inactive. Please contact HR.')
                    return render(request, 'login.html', {'next': next_url})
            login(request, user)
            log_system_event(request, 'login_success', f'Successful sign-in for {user.get_username()}.', severity='info', status_code=200)
            if profile is not None and profile.must_change_password:
                return redirect('eqrApp:change_password')
            if next_url and url_has_allowed_host_and_scheme(
                url=next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect('eqrApp:home')
        log_system_event(request, 'login_failed', 'A sign-in attempt failed.', severity='warning', status_code=401)
        messages.error(request, 'The username or password you entered is incorrect.')

    return render(request, 'login.html', {'next': next_url})


@login_required
def home(request):
    role = get_user_role(request.user)
    destinations = {
        'employee': 'eqrApp:employee_dashboard',
        'supervisor': 'eqrApp:supervisor_dashboard',
        'hr': 'eqrApp:hr_dashboard',
        'admin': 'eqrApp:admin_dashboard',
    }
    if role in ('employee', 'supervisor'):
        profile = get_employee_profile(request.user)
        if profile is None or profile.employment_status != 'active':
            logout(request)
            messages.error(request, 'Your employee profile is unavailable or inactive. Please contact HR.')
            return redirect('eqrApp:login')
    destination = destinations.get(role)
    if not destination:
        raise PermissionDenied
    return redirect(destination)


@login_required
@roles_required('hr')
def hr_dashboard(request):
    today = timezone.localdate()
    employees = EmployeeProfile.objects.filter(
        employment_status='active', role__in=['employee', 'supervisor']
    )
    pending_applications = LeaveApplication.objects.filter(status__in=['pending_manager', 'pending_hr'])
    recent_applications = LeaveApplication.objects.select_related(
        'employee__user', 'leave_type'
    ).order_by('-submitted_at')[:7]
    context = {
        'page_title': 'HR Dashboard',
        'employees_count': employees.count(),
        'on_leave_count': LeaveApplication.objects.filter(
            status='approved', start_date__lte=today, end_date__gte=today
        ).count(),
        'pending_count': pending_applications.count(),
        'pending_hr_count': pending_applications.filter(status='pending_hr').exclude(
            Q(employee__role='employee', manager_reviewed_at__isnull=True)
        ).count(),
        'pending_supervisor_count': pending_applications.filter(
            Q(status='pending_manager')
            | Q(status='pending_hr', employee__role='employee', manager_reviewed_at__isnull=True)
        ).count(),
        'recent_applications': recent_applications,
        'today': today,
    }
    # HR is an administrative role account, not an employee attendance account.
    # It therefore receives no daily QR credential or personal attendance controls.
    return render(request, 'hr_dashboard.html', context)


def safe_system_event_summary(event):
    """Return a generic message that never exposes employee, actor, or request data."""
    summaries = {
        'http_error': 'An application request encountered an access or server error.',
        'login_failed': 'A sign-in attempt failed or was blocked.',
        'kiosk_exit_failed': 'A kiosk security verification attempt failed.',
        'kiosk_activation_failed': 'Kiosk activation verification was unsuccessful.',
        'kiosk_ip_denied': 'A request from an unapproved network address was blocked.',
        'employee_account_created': 'An account provisioning operation generated a warning.',
        'employee_profile_updated': 'An account profile operation generated a warning.',
        'admin_account_reset': 'An account-support operation generated a warning.',
        'security_event': 'A security rule detected an event requiring review.',
    }
    if event.severity in ('error', 'critical'):
        prefix = 'Application error'
    else:
        prefix = 'Security warning'
    detail = summaries.get(event.event_type, 'A system event requires administrator review.')
    # Do not disclose actor identity, employee identifiers, paths, IPs, or raw status codes.
    return f'{prefix}: {detail}'


@login_required
@roles_required('admin')
def admin_dashboard(request):
    today = timezone.localdate()
    last_30_days = timezone.now() - timedelta(days=30)
    today_records = AttendanceRecord.objects.filter(attendance_date=today)
    recent_events = list(SystemEventLog.objects.filter(severity__in=['warning', 'error', 'critical']).order_by('-created_at')[:10])
    for event in recent_events:
        event.safe_summary = safe_system_event_summary(event)
        event.safe_severity = 'Warning' if event.severity == 'warning' else 'Error'
        event.safe_severity_class = 'warning' if event.severity == 'warning' else 'error'
    context = {
        'page_title': 'System Dashboard',
        'active_account_count': User.objects.filter(is_active=True).count(),
        'today_checkins': today_records.filter(check_in__isnull=False).count(),
        'today_checkouts': today_records.filter(check_out__isnull=False).count(),
        'system_error_count': SystemEventLog.objects.filter(
            created_at__gte=last_30_days, severity__in=['error', 'critical']
        ).count(),
        'security_event_count': SystemEventLog.objects.filter(
            created_at__gte=last_30_days, severity='warning'
        ).count(),
        'recent_events': recent_events,
        'today': today,
    }
    return render(request, 'admin_dashboard.html', context)


@login_required
@roles_required('supervisor')
def supervisor_dashboard(request):
    profile = get_employee_profile(request.user)
    if profile is None or profile.employment_status != 'active':
        raise PermissionDenied

    today = timezone.localdate()
    ensure_employee_leave_balances(profile)
    team = EmployeeProfile.objects.filter(
        Q(manager=request.user) | Q(backup_manager=request.user), employment_status='active'
    ).select_related('user')
    team_attendance = AttendanceRecord.objects.filter(
        (Q(employee__manager=request.user) | Q(employee__backup_manager=request.user)), attendance_date=today
    ).select_related('employee__user')
    team_pending = LeaveApplication.objects.filter(
        Q(employee__manager=request.user) | Q(employee__backup_manager=request.user)
    ).filter(
        Q(status='pending_manager')
        | Q(status='pending_hr', employee__role='employee', manager_reviewed_at__isnull=True)
    ).exclude(employee__user=request.user).select_related('employee__user', 'leave_type').order_by('-submitted_at')
    approved_leave_today = LeaveApplication.objects.filter(
        employee=profile, status='approved', is_half_day=False, start_date__lte=today, end_date__gte=today
    ).exists()
    own_attendance = AttendanceRecord.objects.filter(employee=profile, attendance_date=today).first()

    context = {
        'page_title': 'Supervisor Dashboard',
        'employee': profile,
        'today': today,
        'team_count': team.count(),
        'team_checked_in': team_attendance.filter(check_in__isnull=False).count(),
        'team_late_count': team_attendance.filter(status='late').count(),
        'team_on_leave_count': LeaveApplication.objects.filter(
            (Q(employee__manager=request.user) | Q(employee__backup_manager=request.user)), status='approved', is_half_day=False,
            start_date__lte=today, end_date__gte=today,
        ).count(),
        'pending_count': team_pending.count(),
        'team_members': team[:7],
        'team_attendance': team_attendance[:7],
        'team_pending_applications': team_pending[:7],
        'today_attendance': own_attendance,
        'attendance_qr': build_daily_qr_bundle(profile),
        'approved_leave_today': approved_leave_today,
        'leave_balances': LeaveBalance.objects.filter(employee=profile, year=today.year).select_related('leave_type'),
        'can_check_in': not approved_leave_today and (own_attendance is None or own_attendance.check_in is None),
        'can_check_out': bool(own_attendance and own_attendance.check_in and not own_attendance.check_out),
    }
    return render(request, 'supervisor_dashboard.html', context)


@login_required
@roles_required('employee')
def employee_dashboard(request):
    profile = get_employee_profile(request.user)
    if profile is None or profile.employment_status != 'active':
        messages.error(request, 'Your employee profile is unavailable or inactive. Please contact HR.')
        return redirect('eqrApp:login')

    today = timezone.localdate()
    ensure_employee_leave_balances(profile)
    today_attendance = AttendanceRecord.objects.filter(
        employee=profile, attendance_date=today
    ).first()
    approved_leave_today = LeaveApplication.objects.filter(
        employee=profile,
        status='approved',
        is_half_day=False,
        start_date__lte=today,
        end_date__gte=today,
    ).exists()

    context = {
        'page_title': 'My Dashboard',
        'employee': profile,
        'today': today,
        'today_attendance': today_attendance,
        'attendance_qr': build_daily_qr_bundle(profile),
        'approved_leave_today': approved_leave_today,
        'attendance_history': AttendanceRecord.objects.filter(employee=profile)[:8],
        'leave_applications': LeaveApplication.objects.filter(employee=profile).select_related('leave_type')[:6],
        'pending_leave_count': LeaveApplication.objects.filter(
            employee=profile, status__in=['pending_manager', 'pending_hr']
        ).count(),
        'approved_leave_count': LeaveApplication.objects.filter(employee=profile, status='approved').count(),
        'leave_balances': LeaveBalance.objects.filter(employee=profile, year=today.year).select_related('leave_type'),
        'can_check_in': not approved_leave_today and (today_attendance is None or today_attendance.check_in is None),
        'can_check_out': bool(today_attendance and today_attendance.check_in and not today_attendance.check_out),
    }
    return render(request, 'employee_dashboard.html', context)

@login_required
def employee_list(request):
    role = get_user_role(request.user)
    if role not in ('hr', 'admin'):
        raise PermissionDenied

    included_roles = ['employee', 'supervisor'] if role == 'hr' else ['employee', 'supervisor', 'hr']
    employees = EmployeeProfile.objects.filter(
        role__in=included_roles
    ).select_related('user', 'manager', 'backup_manager')
    search = request.GET.get('q', '').strip()
    department = request.GET.get('department', '').strip()
    status = request.GET.get('status', '').strip()
    access_role = request.GET.get('role', '').strip()

    if search:
        for term in search.split():
            employees = employees.filter(
                Q(employee_id__icontains=term)
                | Q(user__first_name__icontains=term)
                | Q(user__last_name__icontains=term)
                | Q(user__username__icontains=term)
                | Q(user__email__icontains=term)
            )
    if department:
        employees = employees.filter(department__iexact=department)
    if status in {'active', 'inactive', 'terminated'}:
        employees = employees.filter(employment_status=status)
    if access_role in {'employee', 'supervisor', 'hr'} and role == 'admin':
        employees = employees.filter(role=access_role)

    departments = [value for value, _label in DEPARTMENT_CHOICES]
    return render(request, 'employee_list.html', {
        'page_title': 'Employees Overview' if role == 'hr' else 'Employee Account Support',
        'employees': employees,
        'search': search,
        'selected_department': department,
        'selected_status': status,
        'selected_access_role': access_role,
        'departments': departments,
        'is_admin': role == 'admin',
    })

@hr_required
def employee_create(request):
    allowed_roles = ['employee', 'supervisor']
    if request.method == 'POST':
        form = EmployeeForm(request.POST, allowed_roles=allowed_roles)
        if form.is_valid():
            with transaction.atomic():
                role = form.cleaned_data['role']
                username = generated_employee_username(
                    form.cleaned_data['first_name'], form.cleaned_data['last_name'],
                    form.cleaned_data['employee_id'],
                )
                temporary_password = 'employee123'
                user = User.objects.create_user(
                    username=username,
                    password=temporary_password,
                    first_name=form.cleaned_data['first_name'],
                    last_name=form.cleaned_data['last_name'],
                    email=form.cleaned_data['email'],
                    is_staff=False,
                    is_active=True,
                )
                profile = form.save(commit=False)
                profile.user = user
                profile.employment_status = 'active'
                profile.must_change_password = True
                profile.save()
                ensure_employee_leave_balances(profile)
            log_system_event(
                request, 'employee_account_created',
                f'HR created {profile.get_role_display()} profile {profile.employee_id}.',
                severity='info', details={'employee_id': profile.employee_id, 'generated_username': username},
            )
            messages.success(
                request,
                f'{profile.full_name}â€™s account was created. Username: {username}. Temporary password: employee123. '
                'The employee must change this password at first sign-in.',
            )
            return redirect('eqrApp:employee_list')
    else:
        form = EmployeeForm(allowed_roles=allowed_roles)
    return render(request, 'employee_form.html', {
        'page_title': 'Add Employee / Supervisor', 'form': form, 'is_edit': False,
        'department_positions': form.position_map,
        'department_positions_by_role': form.position_map_by_role,
        'department_system_usage': form.department_usage_map,
        'department_supervisors': form.supervisor_map,
    })

@hr_required
def employee_edit(request, pk):
    profile = get_object_or_404(
        EmployeeProfile.objects.select_related('user'),
        pk=pk, role__in=['employee', 'supervisor'],
    )
    allowed_roles = ['employee', 'supervisor']
    if request.method == 'POST':
        form = EmployeeForm(request.POST, instance=profile, instance_user=profile.user, allowed_roles=allowed_roles)
        if form.is_valid():
            with transaction.atomic():
                user = profile.user
                user.first_name = form.cleaned_data['first_name']
                user.last_name = form.cleaned_data['last_name']
                user.email = form.cleaned_data['email']
                profile = form.save()
                user.is_active = profile.employment_status == 'active'
                user.save(update_fields=['first_name', 'last_name', 'email', 'is_active'])
                ensure_employee_leave_balances(profile)
            log_system_event(request, 'employee_profile_updated', f'HR updated employee profile {profile.employee_id}.', severity='info')
            messages.success(request, f'{profile.full_name} was updated. Login credentials can be reset by an Administrator.')
            return redirect('eqrApp:employee_list')
    else:
        form = EmployeeForm(instance=profile, instance_user=profile.user, allowed_roles=allowed_roles)
    return render(request, 'employee_form.html', {
        'page_title': 'Edit Employee / Supervisor', 'form': form, 'is_edit': True, 'employee': profile,
        'department_positions': form.position_map,
        'department_positions_by_role': form.position_map_by_role,
        'department_system_usage': form.department_usage_map,
        'department_supervisors': form.supervisor_map,
    })

@admin_required
def employee_account_support_edit(request, pk):
    profile = get_object_or_404(
        EmployeeProfile.objects.select_related('user'),
        pk=pk, role__in=['employee', 'supervisor', 'hr'],
    )
    if request.method == 'POST':
        form = AdminAccountSupportForm(request.POST, user=profile.user)
        if form.is_valid():
            profile.user.first_name = form.cleaned_data['first_name'].strip()
            profile.user.last_name = form.cleaned_data['last_name'].strip()
            profile.user.username = form.cleaned_data['username'].strip()
            changed_fields = ['first_name', 'last_name', 'username']
            password = form.cleaned_data.get('new_password')
            if password:
                profile.user.set_password(password)
                changed_fields.append('password')
                profile.must_change_password = True
                profile.save(update_fields=['must_change_password', 'updated_at'])
            profile.user.save(update_fields=changed_fields)
            log_system_event(
                request, 'admin_account_support_updated',
                'Administrator performed a restricted account-support update.',
                severity='info', details={'account_support_fields': changed_fields},
            )
            messages.success(request, 'The permitted account details were updated. No employee profile, department, role, attendance, or leave records were changed.')
            return redirect('eqrApp:employee_list')
    else:
        form = AdminAccountSupportForm(user=profile.user)
    return render(request, 'admin_account_support_edit.html', {
        'page_title': 'Employee Account Support', 'form': form, 'profile': profile,
    })


@admin_required
@require_POST
def employee_account_reset(request, pk):
    profile = get_object_or_404(
        EmployeeProfile.objects.select_related('user'),
        pk=pk, role__in=['employee', 'supervisor', 'hr'],
    )
    action = request.POST.get('reset_action', '').strip()
    if action not in {'username', 'password', 'both'}:
        messages.error(request, 'Choose whether to reset the username, password, or both.')
        return redirect('eqrApp:employee_list')

    changes = []
    if action in {'username', 'both'}:
        profile.user.username = generated_employee_username(
            profile.user.first_name, profile.user.last_name, profile.employee_id
        )
        changes.append('username')
    if action in {'password', 'both'}:
        profile.user.set_password('employee123')
        profile.must_change_password = True
        profile.save(update_fields=['must_change_password', 'updated_at'])
        changes.append('password')
    profile.user.save()
    log_system_event(
        request, 'admin_account_reset',
        f'Administrator reset {", ".join(changes)} for employee account {profile.employee_id}.',
        severity='info', details={'employee_id': profile.employee_id, 'reset_fields': changes},
    )
    messages.success(
        request,
        f'Account credentials reset for {profile.full_name}. '
        + ('Username: ' + profile.user.username + '. ' if 'username' in changes else '')
        + ('Temporary password: employee123. The user must change it at next sign-in.' if 'password' in changes else ''),
    )
    return redirect('eqrApp:employee_list')

@login_required
def attendance_create(request):
    raise PermissionDenied('Attendance corrections are not available through the HR workspace.')


@hr_required
def _legacy_attendance_create_disabled(request):
    if request.method == 'POST':
        form = AttendanceRecordForm(request.POST)
        if form.is_valid():
            record = form.save(commit=False)
            record.source = 'hr'
            record.recorded_by = request.user
            try:
                with transaction.atomic():
                    record.save()
                    AttendanceAudit.objects.create(
                        employee=record.employee, attendance=record, actor=request.user,
                        action='created', new_values=attendance_snapshot(record),
                    )
            except IntegrityError:
                form.add_error(None, 'An attendance record already exists for this employee and date.')
            else:
                messages.success(request, 'Attendance record created.')
                return redirect('eqrApp:attendance_list')
    else:
        form = AttendanceRecordForm(initial={'attendance_date': timezone.localdate()})
    return render(request, 'attendance_edit.html', {
        'page_title': 'Add Attendance Record', 'form': form, 'is_create': True,
    })


@login_required
def change_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            profile = get_employee_profile(user)
            if profile and profile.must_change_password:
                profile.must_change_password = False
                profile.save(update_fields=['must_change_password', 'updated_at'])
            update_session_auth_hash(request, user)
            messages.success(request, 'Your password has been changed.')
            return redirect('eqrApp:home')
    else:
        form = PasswordChangeForm(user=request.user)
    return render(request, 'password_change.html', {
        'page_title': 'Change Password', 'form': form,
    })


@login_required
def attendance_list(request):
    today = timezone.localdate()
    role = get_user_role(request.user)
    if role == 'hr':
        raise PermissionDenied('Company attendance is not part of the HR workspace.')
    is_company_view = role == 'admin'
    is_team_view = role == 'supervisor'
    can_edit = False

    try:
        selected_date = datetime.strptime(request.GET.get('date', ''), '%Y-%m-%d').date()
        if selected_date > today:
            selected_date = today
    except (TypeError, ValueError):
        selected_date = today
    status_filter = request.GET.get('status', '').strip()
    search = request.GET.get('q', '').strip()

    if is_company_view:
        roster = EmployeeProfile.objects.filter(
            employment_status='active', role__in=['employee', 'supervisor']
        )
    elif is_team_view:
        roster = EmployeeProfile.objects.filter(
            employment_status='active'
        ).filter(
            Q(manager=request.user) | Q(backup_manager=request.user) | Q(user=request.user)
        )
    elif role == 'employee':
        profile = get_employee_profile(request.user)
        if profile is None or profile.employment_status != 'active':
            raise PermissionDenied
        roster = EmployeeProfile.objects.filter(pk=profile.pk)
    else:
        raise PermissionDenied

    roster = roster.filter(Q(hire_date__isnull=True) | Q(hire_date__lte=selected_date))
    if search:
        for term in search.split():
            roster = roster.filter(
                Q(employee_id__icontains=term)
                | Q(user__username__icontains=term)
                | Q(user__first_name__icontains=term)
                | Q(user__last_name__icontains=term)
                | Q(user__email__icontains=term)
            )

    roster = roster.select_related('user', 'manager').order_by('user__last_name', 'user__first_name', 'employee_id')
    employee_ids = list(roster.values_list('pk', flat=True))
    day_records = AttendanceRecord.objects.filter(
        employee_id__in=employee_ids, attendance_date=selected_date
    ).select_related('employee__user')
    records_by_employee = {record.employee_id: record for record in day_records}

    approved_leaves = LeaveApplication.objects.filter(
        employee_id__in=employee_ids,
        status='approved', start_date__lte=selected_date, end_date__gte=selected_date,
    ).select_related('leave_type')
    leave_by_employee = {application.employee_id: application for application in approved_leaves}

    attendance_rows = []
    for employee in roster:
        record = records_by_employee.get(employee.pk)
        leave_application = leave_by_employee.get(employee.pk)
        if (leave_application and not leave_application.is_half_day) or (record and record.status == 'on_leave'):
            # A full-day approved leave takes precedence over any stale attendance row.
            status_code, status_label = 'on_leave', 'On Leave'
        elif (record and record.status == 'half_day') or (leave_application and leave_application.is_half_day):
            status_code, status_label = 'half_day', 'Half Day'
        elif record and record.status == 'late':
            status_code, status_label = 'late', 'Late'
        elif record and (record.status == 'present' or record.check_in):
            status_code, status_label = 'present', 'Present'
        else:
            status_code, status_label = 'absent', 'Absent'
        if status_filter and status_filter != status_code:
            continue
        attendance_rows.append({
            'employee': employee,
            'check_in': record.check_in if record else None,
            'check_out': record.check_out if record else None,
            'status_code': status_code,
            'status_label': status_label,
            'remarks': record.remarks if record else '',
        })

    return render(request, 'attendance_list.html', {
        'page_title': 'Company Attendance' if role in ('hr', 'admin') else ('Team Attendance' if is_team_view else 'My Attendance'),
        'attendance_rows': attendance_rows,
        'date_filter': selected_date.isoformat(),
        'selected_date': selected_date,
        'status_filter': status_filter,
        'search': search,
        'today': today,
        'is_hr': role == 'hr',
        'is_admin': role == 'admin',
        'is_company_view': is_company_view,
        'is_team_view': is_team_view,
        'can_edit_attendance': can_edit,
        'can_create_attendance': can_edit,
        'can_export_attendance': is_company_view,
        'attendance_count': len(attendance_rows),
    })

@login_required
def attendance_qr_status(request):
    """Return only the authenticated user's own attendance scan state for today."""
    profile = get_employee_profile(request.user)
    if profile is None or get_user_role(request.user) not in ('employee', 'supervisor'):
        raise PermissionDenied
    today = timezone.localdate()
    record = AttendanceRecord.objects.filter(employee=profile, attendance_date=today).first()
    state = 'not_scanned'
    label = 'Not scanned yet'
    if record:
        if record.status == 'on_leave' and not record.check_in:
            state, label = 'on_leave', 'On approved leave'
        elif record.check_out:
            state, label = 'complete', 'Check-in and check-out recorded'
        elif record.check_in:
            state, label = 'checked_in', 'Check-in recorded'
    payload = {
        'ok': True,
        'date': today.isoformat(),
        'state': state,
        'label': label,
        'status': record.get_status_display() if record else '',
        'check_in': timezone.localtime(record.check_in).strftime('%I:%M %p') if record and record.check_in else '',
        'check_out': timezone.localtime(record.check_out).strftime('%I:%M %p') if record and record.check_out else '',
        'last_updated': timezone.localtime(record.updated_at).strftime('%I:%M %p') if record else '',
    }
    response = JsonResponse(payload)
    response['Cache-Control'] = 'no-store, private'
    return response


@admin_required
@require_POST
def check_in(request):
    messages.info(request, 'Attendance is now recorded through the administrator-operated QR kiosk.')
    return redirect('eqrApp:attendance_kiosk')


@admin_required
@require_POST
def check_out(request):
    messages.info(request, 'Attendance is now recorded through the administrator-operated QR kiosk.')
    return redirect('eqrApp:attendance_kiosk')


def kiosk_session_is_active(request):
    """Return True only for the Administrator who activated this browser kiosk session."""
    return bool(
        request.user.is_authenticated
        and get_user_role(request.user) == 'admin'
        and request.session.get('worktrack_kiosk_active') is True
        and request.session.get('worktrack_kiosk_user_id') == request.user.pk
    )


def kiosk_password_lock_remaining(request, flow):
    try:
        until = float(request.session.get(f'worktrack_kiosk_{flow}_locked_until', 0))
    except (TypeError, ValueError):
        until = 0
    return max(0, int(until - timezone.now().timestamp()))


def register_kiosk_password_failure(request, flow):
    attempts_key = f'worktrack_kiosk_{flow}_attempts'
    locked_key = f'worktrack_kiosk_{flow}_locked_until'
    attempts = int(request.session.get(attempts_key, 0)) + 1
    if attempts >= 5:
        request.session[attempts_key] = 0
        request.session[locked_key] = timezone.now().timestamp() + 300
        return 300
    request.session[attempts_key] = attempts
    return 0


def reset_kiosk_password_failures(request, flow):
    request.session.pop(f'worktrack_kiosk_{flow}_attempts', None)
    request.session.pop(f'worktrack_kiosk_{flow}_locked_until', None)


@admin_required
def attendance_kiosk(request):
    """Password-confirmed kiosk activation page, opened from the Administrator dashboard."""
    if not request_kiosk_ip_allowed(request):
        log_system_event(request, 'kiosk_access_denied', 'Administrator kiosk activation was denied by the kiosk network allowlist.', severity='warning', status_code=403)
        raise PermissionDenied

    if kiosk_session_is_active(request):
        return redirect('eqrApp:attendance_kiosk_run')

    remaining = kiosk_password_lock_remaining(request, 'activation')
    if request.method == 'POST':
        if remaining:
            messages.error(request, f'Kiosk activation is temporarily locked. Try again in {remaining} seconds.')
        elif (
            request.user.is_active
            and request.POST.get('username', '').strip().casefold() == request.user.get_username().casefold()
            and request.user.check_password(request.POST.get('password', ''))
        ):
            # Rotate the session key before placing the browser into kiosk-only navigation mode.
            request.session.cycle_key()
            reset_kiosk_password_failures(request, 'activation')
            request.session['worktrack_kiosk_active'] = True
            request.session['worktrack_kiosk_user_id'] = request.user.pk
            request.session['worktrack_kiosk_started_at'] = timezone.now().isoformat()
            log_system_event(request, 'kiosk_activated', 'Administrator reauthenticated and activated the dedicated QR attendance kiosk.', severity='info')
            return redirect('eqrApp:attendance_kiosk_run')
        else:
            locked_for = register_kiosk_password_failure(request, 'activation')
            log_system_event(request, 'kiosk_activation_failed', 'Failed password confirmation while activating the attendance kiosk.', severity='warning', status_code=403)
            if locked_for:
                messages.error(request, 'Too many incorrect password attempts. Kiosk activation is locked for five minutes.')
            else:
                messages.error(request, 'The Administrator password is incorrect. The kiosk was not activated.')

    response = render(request, 'kiosk_activate.html', {
        'page_title': 'Activate QR Attendance Kiosk',
        'kiosk_locked_seconds': kiosk_password_lock_remaining(request, 'activation'),
    })
    response['Cache-Control'] = 'no-store, private'
    response['Pragma'] = 'no-cache'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@admin_required
def attendance_kiosk_run(request):
    """Standalone scanner page. No dashboard navigation or general account controls are rendered."""
    if not kiosk_session_is_active(request):
        return redirect('eqrApp:attendance_kiosk')
    if not request_kiosk_ip_allowed(request):
        log_system_event(request, 'kiosk_access_denied', 'Active kiosk session was denied by the kiosk network allowlist.', severity='warning', status_code=403)
        raise PermissionDenied

    today = timezone.localdate()
    request.session.pop('worktrack_kiosk_settings_unlocked_until', None)
    recent_records = AttendanceRecord.objects.filter(
        attendance_date=today
    ).select_related('employee__user').order_by('-updated_at')[:12]
    response = render(request, 'attendance_kiosk.html', {
        'today': today,
        'scan_url': reverse('eqrApp:attendance_kiosk_scan'),
        'exit_url': reverse('eqrApp:attendance_kiosk_exit'),
        'settings_unlock_url': reverse('eqrApp:attendance_kiosk_settings_unlock'),
        'settings_lock_url': reverse('eqrApp:attendance_kiosk_settings_lock'),
        'correction_statuses': KioskCorrectionForm.base_fields['status'].choices,
        'admin_display_name': request.user.get_full_name() or request.user.get_username(),
        'recent_records': recent_records,
    })
    response['Cache-Control'] = 'no-store, private'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    response['Referrer-Policy'] = 'same-origin'
    return response


@admin_required
@require_POST
def attendance_kiosk_exit(request):
    """Exit kiosk only after the same Administrator confirms their password again."""
    if not kiosk_session_is_active(request):
        raise PermissionDenied
    if not request_kiosk_ip_allowed(request):
        log_system_event(request, 'kiosk_exit_denied', 'Kiosk exit was denied by the network allowlist.', severity='warning', status_code=403)
        raise PermissionDenied

    # A kiosk exit attempt closes the privileged settings window; a failed exit
    # requires fresh reauthentication before settings can be opened again.
    request.session.pop('worktrack_kiosk_settings_unlocked_until', None)
    remaining = kiosk_password_lock_remaining(request, 'exit')
    if remaining:
        messages.error(request, f'Kiosk exit is temporarily locked. Try again in {remaining} seconds.')
        return redirect('eqrApp:attendance_kiosk_run')

    if request.user.is_active and request.user.check_password(request.POST.get('password', '')):
        log_system_event(request, 'kiosk_exited', 'Administrator reauthenticated and exited the dedicated QR attendance kiosk.', severity='info')
        request.session.pop('worktrack_kiosk_active', None)
        request.session.pop('worktrack_kiosk_user_id', None)
        request.session.pop('worktrack_kiosk_started_at', None)
        request.session.pop('worktrack_kiosk_settings_unlocked_until', None)
        reset_kiosk_password_failures(request, 'exit')
        request.session.cycle_key()
        messages.success(request, 'The attendance kiosk has been securely closed.')
        return redirect('eqrApp:admin_dashboard')

    locked_for = register_kiosk_password_failure(request, 'exit')
    log_system_event(request, 'kiosk_exit_failed', 'Failed password confirmation while attempting to exit the attendance kiosk.', severity='warning', status_code=403)
    if locked_for:
        messages.error(request, 'Too many incorrect password attempts. Kiosk exit is locked for five minutes.')
    else:
        messages.error(request, 'The Administrator password is incorrect. The kiosk remains active.')
    return redirect('eqrApp:attendance_kiosk_run')


KIOSK_SETTINGS_UNLOCK_SECONDS = 600


def kiosk_settings_is_unlocked(request):
    """Hidden kiosk settings remain usable only briefly after fresh administrator reauthentication."""
    try:
        expiry = float(request.session.get('worktrack_kiosk_settings_unlocked_until', 0))
    except (TypeError, ValueError):
        expiry = 0
    return kiosk_session_is_active(request) and expiry > timezone.now().timestamp()


def kiosk_attendance_payload(record, action, message):
    employee = record.employee
    return {
        'ok': True,
        'action': action,
        'message': message,
        'record_id': record.pk,
        'employee_name': employee.full_name,
        'employee_id': employee.employee_id,
        'department': employee.department or '',
        'attendance_date': record.attendance_date.isoformat(),
        'check_in': timezone.localtime(record.check_in).strftime('%I:%M %p') if record.check_in else '',
        'check_out': timezone.localtime(record.check_out).strftime('%I:%M %p') if record.check_out else '',
        'status': record.get_status_display(),
        'status_code': record.status,
        'last_updated': timezone.localtime(record.updated_at).strftime('%I:%M %p'),
    }


def kiosk_arrival_status(now):
    local_time = timezone.localtime(now).time().replace(tzinfo=None)
    late_after = getattr(settings, 'ATTENDANCE_LATE_AFTER', '09:00')
    try:
        late_time = datetime.strptime(late_after, '%H:%M').time()
    except (TypeError, ValueError):
        late_time = DEFAULT_LATE_TIME
    return 'late' if local_time > late_time else 'present'


def record_kiosk_attendance(request, employee, forced_action=None, source='self_service'):
    """Record a kiosk scan or a verified administrator entry at the current time."""
    today = timezone.localdate()
    on_full_day_leave = LeaveApplication.objects.filter(
        employee=employee, status='approved', is_half_day=False,
        start_date__lte=today, end_date__gte=today,
    ).exists()
    if on_full_day_leave:
        return {'ok': False, 'message': f'{employee.full_name} is on approved leave today. Attendance was not changed.'}, 409

    now = timezone.now()
    arrival_status = kiosk_arrival_status(now)
    with transaction.atomic():
        # Manual entries and camera scans must also serialize before the day's first row exists.
        EmployeeProfile.objects.select_for_update().get(pk=employee.pk)
        record = AttendanceRecord.objects.select_for_update().filter(
            employee=employee, attendance_date=today
        ).first()
        if record is not None and record.status == 'on_leave':
            return {'ok': False, 'message': f'{employee.full_name} is marked as on leave today. Attendance was not changed.'}, 409

        action = forced_action or (
            'check_in' if record is None or record.check_in is None
            else ('check_out' if record.check_out is None else 'complete')
        )
        if action == 'complete':
            return {'ok': False, 'message': f'{employee.full_name} already has a complete attendance record for today.'}, 409
        if action not in {'check_in', 'check_out'}:
            return {'ok': False, 'message': 'Choose a valid attendance action.'}, 400

        if action == 'check_in':
            if record is not None and record.check_in is not None:
                return {'ok': False, 'message': f'{employee.full_name} already has a check-in for today.'}, 409
            if record is None:
                record = AttendanceRecord.objects.create(
                    employee=employee, attendance_date=today, check_in=now,
                    status=arrival_status, source=source, recorded_by=request.user,
                )
                AttendanceAudit.objects.create(
                    employee=employee, attendance=record, actor=request.user,
                    action='created', old_values={}, new_values=attendance_snapshot(record),
                )
            else:
                old_values = attendance_snapshot(record)
                preserve_half_day = record.status == 'half_day' and record.source in ('leave_sync', 'admin')
                record.check_in = now
                if not preserve_half_day:
                    record.status = arrival_status
                if not preserve_half_day or source == 'admin':
                    record.source = source
                record.recorded_by = request.user
                record.save(update_fields=['check_in', 'status', 'source', 'recorded_by', 'updated_at'])
                AttendanceAudit.objects.create(
                    employee=employee, attendance=record, actor=request.user,
                    action='updated', old_values=old_values, new_values=attendance_snapshot(record),
                )
            message = f'Check-in recorded for {employee.full_name}.'
        else:
            if record is None or record.check_in is None:
                return {'ok': False, 'message': f'{employee.full_name} has no check-in today. Record check-in first.'}, 409
            if record.check_out is not None:
                return {'ok': False, 'message': f'{employee.full_name} already has a check-out for today.'}, 409
            if now - record.check_in < QR_RESCAN_INTERVAL:
                return {'ok': False, 'message': 'Check-in is already recorded. Check-out is available at least 10 seconds after check-in.'}, 409
            old_values = attendance_snapshot(record)
            record.check_out = now
            record.recorded_by = request.user
            if source == 'admin':
                record.source = 'admin'
            record.save(update_fields=['check_out', 'recorded_by', 'source', 'updated_at'])
            AttendanceAudit.objects.create(
                employee=employee, attendance=record, actor=request.user,
                action='updated', old_values=old_values, new_values=attendance_snapshot(record),
            )
            message = f'Check-out recorded for {employee.full_name}.'

    record.refresh_from_db()
    return kiosk_attendance_payload(record, action, message), 200


@admin_required
@require_POST
def attendance_kiosk_settings_unlock(request):
    if not kiosk_session_is_active(request) or not request_kiosk_ip_allowed(request):
        return JsonResponse({'ok': False, 'message': 'Only the Administrator who activated this kiosk can open settings.'}, status=403)
    remaining = kiosk_password_lock_remaining(request, 'settings')
    if remaining:
        return JsonResponse({'ok': False, 'message': f'Settings are locked. Try again in {remaining} seconds.'}, status=429)
    password = request.POST.get('password', '')
    if request.user.is_active and request.user.check_password(password):
        request.session['worktrack_kiosk_settings_unlocked_until'] = timezone.now().timestamp() + KIOSK_SETTINGS_UNLOCK_SECONDS
        reset_kiosk_password_failures(request, 'settings')
        log_system_event(request, 'kiosk_settings_unlocked', 'Administrator reauthenticated to open hidden kiosk settings.', severity='info')
        return JsonResponse({'ok': True, 'expires_in': KIOSK_SETTINGS_UNLOCK_SECONDS})
    locked_for = register_kiosk_password_failure(request, 'settings')
    log_system_event(request, 'kiosk_settings_unlock_failed', 'Failed verification for hidden kiosk settings.', severity='warning', status_code=403)
    message = 'Too many incorrect attempts. Settings are locked for five minutes.' if locked_for else 'Administrator password was incorrect.'
    return JsonResponse({'ok': False, 'message': message}, status=403)


@admin_required
@require_POST
def attendance_kiosk_settings_lock(request):
    """Immediately revoke the short-lived settings grant when the Admin closes settings."""
    if not kiosk_session_is_active(request) or not request_kiosk_ip_allowed(request):
        return JsonResponse({'ok': False, 'message': 'An active Administrator kiosk session on an approved device is required.'}, status=403)
    request.session.pop('worktrack_kiosk_settings_unlocked_until', None)
    log_system_event(request, 'kiosk_settings_locked', 'Administrator closed the privileged kiosk settings panel.', severity='info')
    return JsonResponse({'ok': True, 'message': 'Kiosk settings locked.'})


@admin_required
@require_POST
def attendance_kiosk_manual(request):
    if not kiosk_settings_is_unlocked(request) or not request_kiosk_ip_allowed(request):
        return JsonResponse({'ok': False, 'message': 'Unlock Administrator kiosk settings first.'}, status=403)
    action = request.POST.get('action')
    if action not in ('check_in', 'check_out'):
        return JsonResponse({'ok': False, 'message': 'Select check-in or check-out.'}, status=400)
    employee = EmployeeProfile.objects.select_related('user').filter(
        employee_id=request.POST.get('employee_id', '').strip(), employment_status='active',
        user__is_active=True, role__in=('employee', 'supervisor'),
    ).first()
    if employee is None:
        return JsonResponse({'ok': False, 'message': 'No active employee or supervisor matches that ID.'}, status=404)
    payload, status = record_kiosk_attendance(request, employee, forced_action=action, source='admin')
    return JsonResponse(payload, status=status)


@admin_required
@require_POST
def attendance_kiosk_edit(request):
    if not kiosk_settings_is_unlocked(request) or not request_kiosk_ip_allowed(request):
        return JsonResponse({'ok': False, 'message': 'Unlock Administrator kiosk settings first.'}, status=403)
    action = request.POST.get('action')
    if action not in ('lookup', 'update', 'delete'):
        return JsonResponse({'ok': False, 'message': 'Choose an attendance correction action.'}, status=400)
    try:
        day = date.fromisoformat(request.POST.get('attendance_date', ''))
        if day > timezone.localdate():
            raise ValueError
    except ValueError:
        return JsonResponse({'ok': False, 'message': 'Choose today or an earlier attendance date.'}, status=400)

    with transaction.atomic():
        record = AttendanceRecord.objects.select_for_update(of=('self',)).select_related('employee__user').filter(
            employee__employee_id=request.POST.get('employee_id', '').strip(),
            employee__role__in=('employee', 'supervisor'), attendance_date=day,
        ).first()
        if record is None:
            return JsonResponse({'ok': False, 'message': 'No attendance record for that employee ID and date.'}, status=404)
        leaves = LeaveApplication.objects.filter(employee=record.employee, status='approved', start_date__lte=day, end_date__gte=day)
        if record.status == 'on_leave' or leaves.filter(is_half_day=False).exists():
            return JsonResponse({'ok': False, 'message': 'This day is managed by approved leave.'}, status=409)

        version = f'{record.pk}/{record.updated_at.isoformat()}'
        if action == 'lookup':
            data = kiosk_attendance_payload(record, action, '')
            data['version'] = version
            for field in ('check_in', 'check_out'):
                stamp = getattr(record, field)
                data[field + '_value'] = timezone.localtime(stamp).strftime('%H:%M:%S') if stamp else ''
            return JsonResponse(data)
        if request.POST.get('version') != version:
            return JsonResponse({'ok': False, 'message': 'Attendance has changed. Find the record again before saving.'}, status=409)
        reason = request.POST.get('reason', '').strip()
        if not reason or len(reason) > 300:
            return JsonResponse({'ok': False, 'message': 'Enter a correction reason of up to 300 characters.'}, status=400)
        if leaves.filter(is_half_day=True).exists() and (action == 'delete' or request.POST.get('status') != 'half_day'):
            return JsonResponse({'ok': False, 'message': 'Approved half-day leave must keep its Half Day attendance record.'}, status=409)

        old_values = attendance_snapshot(record)
        if action == 'delete':
            data = kiosk_attendance_payload(record, action, 'Attendance record deleted.')
            AttendanceAudit.objects.create(employee=record.employee, attendance=record, actor=request.user,
                action='deleted', old_values=old_values, new_values={'correction_reason': reason})
            record.delete()
            return JsonResponse(data)

        form = KioskCorrectionForm(request.POST, record)
        if not form.is_valid():
            return JsonResponse({'ok': False, 'message': ' '.join(error for errors in form.errors.values() for error in errors)}, status=400)
        for field in ('check_in', 'check_out', 'status'):
            setattr(record, field, form.cleaned_data[field])
        if attendance_snapshot(record) == old_values:
            return JsonResponse({'ok': False, 'message': 'Change a time or status before saving.'}, status=400)
        record.recorded_by = request.user
        record.source = 'admin'
        record.save(update_fields=['check_in', 'check_out', 'status', 'recorded_by', 'source', 'updated_at'])
        AttendanceAudit.objects.create(employee=record.employee, attendance=record, actor=request.user,
            action='updated', old_values=old_values, new_values={**attendance_snapshot(record), 'correction_reason': reason})
        return JsonResponse(kiosk_attendance_payload(record, action, 'Attendance correction saved.'))


@admin_required
@require_POST
def attendance_kiosk_scan(request):
    if not kiosk_session_is_active(request):
        return JsonResponse({'ok': False, 'message': 'Activate the kiosk with Administrator verification before scanning.'}, status=403)
    if not request_kiosk_ip_allowed(request):
        return JsonResponse({'ok': False, 'message': 'This kiosk is not on an approved device or network.'}, status=403)

    token = request.POST.get('token', '').strip()
    if not token:
        return JsonResponse({'ok': False, 'message': 'No QR value was detected. Please hold the employee QR steady.'}, status=400)
    today = timezone.localdate()
    try:
        qr_record = validate_daily_qr_token(token, today=today)
    except signing.BadSignature as exc:
        return JsonResponse({'ok': False, 'message': str(exc)}, status=400)

    payload, status_code = record_kiosk_attendance(
        request, qr_record.employee, forced_action=None, source='self_service'
    )
    return JsonResponse(payload, status=status_code)


@login_required
def attendance_edit(request, pk):
    raise PermissionDenied('Attendance corrections are not available through the HR workspace.')


@hr_required
def _legacy_attendance_edit_disabled(request, pk):
    record = get_object_or_404(AttendanceRecord.objects.select_related('employee__user'), pk=pk)
    if request.method == 'POST':
        form = AttendanceRecordForm(request.POST, instance=record)
        form.fields['employee'].disabled = True
        if form.is_valid():
            old_values = attendance_snapshot(record)
            updated = form.save(commit=False)
            updated.source = 'hr'
            updated.recorded_by = request.user
            with transaction.atomic():
                updated.save()
                AttendanceAudit.objects.create(
                    employee=updated.employee, attendance=updated, actor=request.user,
                    action='updated', old_values=old_values, new_values=attendance_snapshot(updated),
                )
            messages.success(request, 'Attendance record updated. The correction was added to the audit trail.')
            return redirect('eqrApp:attendance_list')
    else:
        form = AttendanceRecordForm(instance=record)
    form.fields['employee'].disabled = True
    return render(request, 'attendance_edit.html', {
        'page_title': 'Edit Attendance', 'form': form, 'record': record, 'is_create': False,
    })


@login_required
def leave_list(request):
    role = get_user_role(request.user)
    if role not in ('hr', 'supervisor', 'employee'):
        raise PermissionDenied

    year = timezone.localdate().year
    base = LeaveApplication.objects.select_related(
        'employee__user', 'employee__manager', 'employee__backup_manager', 'leave_type'
    )
    if role == 'hr':
        applications = base
        profiles = EmployeeProfile.objects.filter(role__in=['employee', 'supervisor'], employment_status='active')
    elif role == 'supervisor':
        applications = base.filter(
            Q(employee__manager=request.user) | Q(employee__backup_manager=request.user) | Q(employee__user=request.user)
        )
        profiles = EmployeeProfile.objects.filter(
            employment_status='active'
        ).filter(Q(manager=request.user) | Q(backup_manager=request.user) | Q(user=request.user))
    else:
        profile = get_employee_profile(request.user)
        if profile is None:
            raise PermissionDenied
        applications = base.filter(employee=profile)
        profiles = EmployeeProfile.objects.filter(pk=profile.pk)

    # Prepare balances for each employee profile in the user's visibility scope.
    for profile in profiles:
        ensure_employee_leave_balances(profile, year)

    valid_statuses = {'pending_manager', 'pending_hr', 'approved', 'rejected', 'cancelled'}
    valid_sorts = {
        '-submitted_at': '-submitted_at', 'submitted_at': 'submitted_at',
        'start_date': 'start_date', '-start_date': '-start_date',
        'employee': 'employee__user__last_name',
    }

    def apply_request_filters(queryset, prefix, default_sort='-submitted_at'):
        search = request.GET.get(f'{prefix}_q', '').strip()
        status = request.GET.get(f'{prefix}_status', '').strip()
        leave_type_code = request.GET.get(f'{prefix}_type', '').strip()
        sort = request.GET.get(f'{prefix}_sort', default_sort).strip()
        if search:
            for term in search.split():
                queryset = queryset.filter(
                    Q(employee__employee_id__icontains=term)
                    | Q(employee__user__first_name__icontains=term)
                    | Q(employee__user__last_name__icontains=term)
                    | Q(leave_type__name__icontains=term)
                )
        if status in valid_statuses:
            unacknowledged_legacy_employee = Q(
                status='pending_hr', employee__role='employee', manager_reviewed_at__isnull=True
            )
            if prefix == 'pending' and role in ('supervisor', 'hr') and status == 'pending_manager':
                queryset = queryset.filter(Q(status='pending_manager') | unacknowledged_legacy_employee)
            elif prefix == 'pending' and role == 'hr' and status == 'pending_hr':
                queryset = queryset.filter(status='pending_hr').exclude(unacknowledged_legacy_employee)
            else:
                queryset = queryset.filter(status=status)
        if leave_type_code:
            queryset = queryset.filter(leave_type__code=leave_type_code)
        return queryset.order_by(valid_sorts.get(sort, default_sort)), search, status, leave_type_code, sort

    pending_source = applications.filter(status__in=['pending_manager', 'pending_hr'])
    if role == 'employee':
        history_source = applications
    elif role == 'supervisor':
        # Unacknowledged legacy employee requests remain in the pending queue.
        # Only acknowledged requests move to the supervisor's history.
        history_source = applications.exclude(status='pending_manager').exclude(
            Q(status='pending_hr', employee__role='employee', manager_reviewed_at__isnull=True)
        )
    else:
        history_source = applications.exclude(status__in=['pending_manager', 'pending_hr'])
    if role == 'supervisor':
        # Supervisors acknowledge employee requests from their reports, never their own requests.
        pending_source = pending_source.filter(
            Q(status='pending_manager')
            | Q(status='pending_hr', employee__role='employee', manager_reviewed_at__isnull=True)
        ).exclude(employee__user=request.user)
    if role == 'employee':
        pending_source = pending_source.none()

    pending, pending_search, pending_status, pending_type, pending_sort = apply_request_filters(pending_source, 'pending')
    history, history_search, history_status, history_type, history_sort = apply_request_filters(history_source, 'history')

    # HR balance search is intentionally limited to employee name and employee ID.
    balance_search = request.GET.get('balance_q', '').strip()
    balance_profiles = profiles
    if role == 'hr' and balance_search:
        for term in balance_search.split():
            balance_profiles = balance_profiles.filter(
                Q(employee_id__icontains=term)
                | Q(user__first_name__icontains=term)
                | Q(user__last_name__icontains=term)
            )
    balances = LeaveBalance.objects.filter(year=year, employee__in=balance_profiles).select_related(
        'employee__user', 'leave_type'
    ).order_by('employee__user__last_name', 'employee__user__first_name', 'leave_type__name')
    grouped = {}
    for balance in balances:
        group = grouped.setdefault(balance.employee_id, {'employee': balance.employee, 'items': []})
        group['items'].append(balance)
    balance_groups = list(grouped.values())

    leave_types = LeaveType.objects.filter(is_active=True, track_balance=True).order_by('name')
    filter_keys = {
        'pending': ('pending_q', 'pending_status', 'pending_type', 'pending_sort'),
        'history': ('history_q', 'history_status', 'history_type', 'history_sort'),
        'balance': ('balance_q',),
    }
    retained_filters = {
        section: [(key, request.GET[key]) for other, keys in filter_keys.items()
                  if other != section for key in keys if request.GET.get(key)]
        for section in filter_keys
    }
    return render(request, 'leave_list.html', {
        'page_title': 'Leave Requests',
        'applications': history,
        'pending_applications': pending,
        'balance_groups': balance_groups,
        'balance_search': balance_search,
        'retained_filters': retained_filters,
        'leave_types': leave_types,
        'pending_search': pending_search,
        'pending_status': pending_status,
        'pending_type': pending_type,
        'pending_sort': pending_sort,
        'history_search': history_search,
        'history_status': history_status,
        'history_type': history_type,
        'history_sort': history_sort,
        'is_hr': role == 'hr',
        'is_team_view': role == 'supervisor',
        'is_employee_view': role == 'employee',
        'can_review': role in ('hr', 'supervisor'),
        'can_apply': role in ('employee', 'supervisor'),
        'year': year,
    })


@login_required
def leave_apply(request):
    profile = get_employee_profile(request.user)
    if (profile is None or profile.employment_status != 'active'
            or get_user_role(request.user) not in ('employee', 'supervisor')):
        raise PermissionDenied
    ensure_employee_leave_balances(profile)

    if request.method == 'POST':
        if profile.role == 'employee' and not (profile.manager_id or profile.backup_manager_id):
            messages.error(request, 'Your account must have a department supervisor assigned before you can submit a leave request.')
            return redirect('eqrApp:leave_list')
        form = LeaveApplicationForm(request.POST)
        uploaded_files = request.FILES.getlist('documents')
        form_valid = form.is_valid()
        errors = valid_uploaded_documents(uploaded_files)
        if errors:
            for error in errors:
                form.add_error(None, error)

        if form_valid and not errors:
            leave_type = form.cleaned_data['leave_type']
            application = None
            with transaction.atomic():
                EmployeeProfile.objects.select_for_update().get(pk=profile.pk)
                balance_errors = leave_balance_errors(
                    profile, leave_type, form.cleaned_data['start_date'], form.cleaned_data['end_date'],
                    form.cleaned_data.get('is_half_day', False),
                )
                for error in balance_errors:
                    form.add_error(None, error)
                requested_days = leave_days_in_range(
                    form.cleaned_data['start_date'], form.cleaned_data['end_date'],
                    form.cleaned_data.get('is_half_day', False),
                )
                if requested_days <= 0:
                    form.add_error(None, 'The selected dates contain no working days. Select a weekday that is not a configured holiday.')
                if form.errors:
                    pass
                elif leave_type.requires_document and not uploaded_files:
                    form.add_error(None, 'This leave type requires at least one supporting document.')
                else:
                    start_date = form.cleaned_data['start_date']
                    end_date = form.cleaned_data['end_date']
                    overlapping = LeaveApplication.objects.filter(
                        employee=profile,
                        start_date__lte=end_date,
                        end_date__gte=start_date,
                    ).exclude(status__in=['rejected', 'cancelled'])
                    if overlapping.exists():
                        form.add_error(None, 'The requested dates overlap with another active leave application.')
                    else:
                        application = form.save(commit=False)
                        application.employee = profile
                        application.status = 'pending_manager' if (profile.manager_id or profile.backup_manager_id) else 'pending_hr'
                        application.save()
                        LeaveAction.objects.create(
                            application=application,
                            actor=request.user,
                            action='submitted',
                            comments='Leave application submitted by employee.',
                        )
                        for uploaded_file in uploaded_files:
                            LeaveDocument.objects.create(
                                application=application,
                                file=uploaded_file,
                                original_name=os.path.basename(uploaded_file.name.replace('\\', '/')),
                                uploaded_by=request.user,
                            )
            if application is not None:
                recipients = [getattr(profile.manager, 'email', ''), getattr(profile.backup_manager, 'email', '')]
                recipients.extend(getattr(settings, 'WORKTRACK_HR_EMAILS', []))
                send_worktrack_email(
                    f'WorkTrack leave request #{application.pk} submitted',
                    f'{profile.full_name} submitted {leave_type.name} leave from {application.start_date} to {application.end_date}.',
                    recipients,
                )
                messages.success(request, 'Your leave request has been submitted.')
                return redirect('eqrApp:leave_detail', pk=application.pk)
    else:
        form = LeaveApplicationForm()

    return render(request, 'leave_form.html', {
        'page_title': 'Apply for Leave',
        'form': form,
        'max_document_size_mb': 5,
        'max_document_count': MAX_DOCUMENT_COUNT,
    })


@login_required
def leave_detail(request, pk):
    application = get_object_or_404(
        LeaveApplication.objects.select_related(
            'employee__user', 'employee__manager', 'employee__backup_manager', 'leave_type',
            'manager_reviewed_by', 'reviewed_by',
        ).prefetch_related('documents', 'actions__actor'),
        pk=pk,
    )
    if not can_view_leave(request.user, application):
        raise PermissionDenied

    role = get_user_role(request.user)
    can_manager_review = can_review_as_manager(request.user, application)
    supervisor_acknowledged = application.manager_reviewed_at is not None
    supervisor_ack_required = leave_requires_supervisor_ack(application)
    can_hr_review = role == 'hr' and application.status == 'pending_hr' and (not supervisor_ack_required or supervisor_acknowledged)
    can_hr_reject = can_hr_review
    can_cancel = (
        application.employee.user_id == request.user.id
        and application.status in ['pending_manager', 'pending_hr']
    )
    return render(request, 'leave_detail.html', {
        'page_title': f'Leave Request #{application.pk}',
        'application': application,
        'role': role,
        'can_manager_review': can_manager_review,
        'can_hr_review': can_hr_review,
        'can_hr_reject': can_hr_reject,
        'can_cancel': can_cancel,
        'can_delete_application': application.status in ('cancelled', 'rejected') and (
            application.employee.user_id == request.user.id or role == 'hr'
        ),
        'can_delete_documents': (not application.leave_type.requires_document or len(application.documents.all()) > 1) and application.status in ('pending_manager', 'pending_hr') and (
            application.employee.user_id == request.user.id or role == 'hr'
        ),
        'can_download_documents': role != 'admin',
    })


@require_POST
@login_required
def review_leave(request, pk):
    application = get_object_or_404(
        LeaveApplication.objects.select_related('employee__user', 'employee__manager', 'employee__backup_manager'), pk=pk
    )
    decision = request.POST.get('decision', '').strip()
    comments = request.POST.get('comments', '').strip()
    role = get_user_role(request.user)
    manager_acknowledge = can_review_as_manager(request.user, application)
    supervisor_ack_required = leave_requires_supervisor_ack(application)
    supervisor_acknowledged = application.manager_reviewed_at is not None
    hr_review = (
        role == 'hr' and application.status == 'pending_hr'
        and (not supervisor_ack_required or supervisor_acknowledged)
    )

    if decision == 'acknowledge':
        if not manager_acknowledge:
            raise PermissionDenied
    elif decision in ('approve', 'reject'):
        if not hr_review:
            raise PermissionDenied('Only HR may approve or decline a request after the required supervisor acknowledgment.')
    else:
        messages.error(request, 'Select a valid review action.')
        return redirect('eqrApp:leave_detail', pk=pk)

    try:
        with transaction.atomic():
            # Claim the transition before updating balances or recording a decision.
            next_status = {'acknowledge': 'pending_hr', 'approve': 'approved', 'reject': 'rejected'}[decision]
            changed = LeaveApplication.objects.filter(
                pk=pk, status=application.status, manager_reviewed_at=application.manager_reviewed_at,
            ).update(status=next_status)
            if not changed:
                messages.info(request, 'This request was already updated. Check its current status.')
                return redirect('eqrApp:leave_detail', pk=pk)
            if decision == 'acknowledge':
                application.status = 'pending_hr'
                application.manager_reviewed_by = request.user
                application.manager_reviewed_at = timezone.now()
                application.manager_comments = comments
                application.save(update_fields=['status', 'manager_reviewed_by', 'manager_reviewed_at', 'manager_comments'])
                LeaveAction.objects.create(
                    application=application, actor=request.user, action='manager_approved',
                    comments=comments or 'Supervisor acknowledged the request and forwarded it to HR for the final decision.',
                )
                messages.success(request, 'Supervisor acknowledgment recorded. The request has been forwarded to HR.')
            elif decision == 'reject':
                application.status = 'rejected'
                application.reviewed_by = request.user
                application.reviewed_at = timezone.now()
                application.reviewer_comments = comments
                application.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'reviewer_comments'])
                LeaveAction.objects.create(
                    application=application, actor=request.user, action='rejected',
                    comments=comments or 'Leave application declined by HR.',
                )
                messages.success(request, 'The leave application was declined by HR.')
            else:
                if application.leave_type.requires_document and not application.documents.exists():
                    raise ValidationError('This request requires a supporting document before HR approval.')
                deduct_leave_balance(application)
                application.status = 'approved'
                application.reviewed_by = request.user
                application.reviewed_at = timezone.now()
                application.reviewer_comments = comments
                application.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'reviewer_comments'])
                sync_approved_leave_attendance(application)
                LeaveAction.objects.create(
                    application=application, actor=request.user, action='approved',
                    comments=comments or 'Application approved by HR.',
                )
                messages.success(request, 'The leave application was approved by HR.')
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
        return redirect('eqrApp:leave_detail', pk=pk)

    application.refresh_from_db()
    send_worktrack_email(
        f'WorkTrack leave request #{application.pk} update',
        f'Your leave request for {application.leave_type.name} is now {application.get_status_display()}.',
        [application.employee.user.email],
    )
    return redirect('eqrApp:leave_detail', pk=pk)


@require_POST
@login_required
def cancel_leave(request, pk):
    application = get_object_or_404(LeaveApplication, pk=pk)
    if application.employee.user_id != request.user.id:
        raise PermissionDenied
    with transaction.atomic():
        changed = LeaveApplication.objects.filter(
            pk=pk, status__in=['pending_manager', 'pending_hr'],
        ).update(status='cancelled')
        if not changed:
            messages.error(request, 'Only pending leave applications can be cancelled.')
            return redirect('eqrApp:leave_detail', pk=pk)
        LeaveAction.objects.create(
            application=application, actor=request.user, action='cancelled',
            comments='Cancelled by employee.',
        )
    messages.success(request, 'Your leave application has been cancelled.')
    return redirect('eqrApp:leave_detail', pk=pk)



@login_required
@require_POST
def attendance_delete(request, pk):
    raise PermissionDenied('Attendance deletion is not available through the HR workspace or Administrator dashboard.')


@hr_required
def _legacy_attendance_delete_disabled(request, pk):
    record = get_object_or_404(AttendanceRecord.objects.select_related('employee'), pk=pk)
    old_values = attendance_snapshot(record)
    employee = record.employee
    with transaction.atomic():
        AttendanceAudit.objects.create(
            employee=employee, attendance=None, actor=request.user,
            action='deleted', old_values=old_values, new_values={},
        )
        record.delete()
    messages.success(request, 'Attendance record deleted. The deletion remains in the audit trail.')
    return redirect('eqrApp:attendance_list')


@login_required
def leave_type_list(request):
    if not request.user.is_authenticated:
        return redirect('eqrApp:login')
    if get_user_role(request.user) not in ('hr', 'supervisor', 'employee'):
        raise PermissionDenied
    return redirect('eqrApp:leave_list')

@hr_required
def leave_type_create(request):
    messages.error(request, 'Leave types are a fixed company-wide catalogue and cannot be created from the application.')
    return redirect('eqrApp:leave_type_list')


@hr_required
def leave_type_edit(request, pk):
    messages.error(request, 'Leave types are fixed company-wide values and cannot be edited from the application.')
    return redirect('eqrApp:leave_type_list')


@require_POST
@hr_required
def leave_type_delete(request, pk):
    messages.error(request, 'Standard leave types cannot be deleted from the application.')
    return redirect('eqrApp:leave_type_list')


@login_required
def leave_balance_list(request):
    if not request.user.is_authenticated:
        return redirect('eqrApp:login')
    if get_user_role(request.user) not in ('hr', 'supervisor', 'employee'):
        raise PermissionDenied
    return redirect('eqrApp:leave_list')

@hr_required
def leave_balance_create(request):
    if not request.user.is_authenticated:
        return redirect('eqrApp:login')
    raise PermissionDenied('Leave entitlements are fixed by the configured company catalogue.')

@hr_required
def leave_balance_edit(request, pk):
    if not request.user.is_authenticated:
        return redirect('eqrApp:login')
    raise PermissionDenied('Leave balances are automatically tracked and cannot be edited here.')

@require_POST
@hr_required
def leave_balance_delete(request, pk):
    if not request.user.is_authenticated:
        return redirect('eqrApp:login')
    raise PermissionDenied('Leave balances are retained for entitlement and audit history.')

@login_required
def holiday_list(request):
    role = get_user_role(request.user)
    if role not in ('employee', 'supervisor', 'hr'):
        raise PermissionDenied
    today = timezone.localdate()
    month_value = request.GET.get('month', '').strip()
    try:
        selected_month = datetime.strptime(month_value, '%Y-%m').date().replace(day=1) if month_value else today.replace(day=1)
    except ValueError:
        selected_month = today.replace(day=1)

    weeks = month_calendar.Calendar(firstweekday=6).monthdatescalendar(selected_month.year, selected_month.month)
    first_day, last_day = weeks[0][0], weeks[-1][-1]
    holidays = Holiday.objects.filter(date__gte=first_day, date__lte=last_day)
    if role != 'hr':
        holidays = holidays.filter(is_active=True)
    holidays = holidays.order_by('date', 'name')
    holidays_by_date = defaultdict(list)
    for holiday in holidays:
        holidays_by_date[holiday.date].append(holiday)

    leaves = LeaveApplication.objects.filter(
        status='approved', start_date__lte=last_day, end_date__gte=first_day
    ).select_related('employee__user', 'leave_type')
    if role == 'employee':
        leaves = leaves.filter(employee__user=request.user)
    elif role == 'supervisor':
        leaves = leaves.filter(
            Q(employee__user=request.user)
            | Q(employee__manager=request.user)
            | Q(employee__backup_manager=request.user)
        )
    leaves_by_date = defaultdict(list)
    for application in leaves:
        cursor = max(first_day, application.start_date)
        end = min(last_day, application.end_date)
        while cursor <= end:
            if cursor.weekday() < 5:
                leaves_by_date[cursor].append({
                    'employee_name': application.employee.full_name,
                    'leave_type': application.leave_type.name,
                    'is_own': application.employee.user_id == request.user.id,
                })
            cursor += timedelta(days=1)

    calendar_weeks = []
    for week in weeks:
        calendar_weeks.append([
            {
                'date': day,
                'is_current_month': day.month == selected_month.month,
                'is_today': day == today,
                'holidays': holidays_by_date.get(day, []),
                'leave_entries': leaves_by_date.get(day, []),
            }
            for day in week
        ])

    previous_month = (selected_month - timedelta(days=1)).replace(day=1)
    next_month = (selected_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return render(request, 'holiday_list.html', {
        'page_title': 'Company Calendar',
        'calendar_weeks': calendar_weeks,
        'current_month': selected_month,
        'previous_month': previous_month.strftime('%Y-%m'),
        'next_month': next_month.strftime('%Y-%m'),
        'month_holidays': holidays,
        'can_manage_holidays': role == 'hr',
        'is_team_view': role == 'supervisor',
        'current_role': role,
    })

@hr_required
def holiday_create(request):
    form = HolidayForm(request.POST or None, initial={'date': timezone.localdate(), 'is_active': True})
    if request.method == 'POST' and form.is_valid():
        try:
            form.save()
        except IntegrityError:
            form.add_error('date', 'A holiday is already configured for this date.')
        else:
            messages.success(request, 'Holiday added to the calendar.')
            return redirect('eqrApp:holiday_list')
    return render(request, 'holiday_form.html', {'page_title': 'Add Holiday', 'form': form})


@hr_required
def holiday_edit(request, pk):
    holiday = get_object_or_404(Holiday, pk=pk)
    form = HolidayForm(request.POST or None, instance=holiday)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Holiday updated.')
        return redirect('eqrApp:holiday_list')
    return render(request, 'holiday_form.html', {'page_title': 'Edit Holiday', 'form': form, 'holiday': holiday})


@require_POST
@hr_required
def holiday_deactivate(request, pk):
    holiday = get_object_or_404(Holiday, pk=pk)
    holiday.is_active = False
    holiday.save(update_fields=['is_active'])
    messages.success(request, 'Holiday deactivated. It will count as a working day in future leave calculations.')
    return redirect('eqrApp:holiday_list')


@require_POST
@login_required
def delete_leave_document(request, pk):
    document = get_object_or_404(LeaveDocument, pk=pk)
    with transaction.atomic():
        application = get_object_or_404(LeaveApplication.objects.select_for_update(), pk=document.application_id)
        if application.employee.user_id != request.user.id and get_user_role(request.user) != 'hr':
            raise PermissionDenied
        if application.status not in ('pending_manager', 'pending_hr'):
            raise PermissionDenied
        document = get_object_or_404(application.documents, pk=pk)
        if application.leave_type.requires_document and not application.documents.exclude(pk=pk).exists():
            messages.error(request, 'This leave type requires at least one supporting document.')
            return redirect('eqrApp:leave_detail', pk=application.pk)
        stored_file = document.file
        document.delete()
        if stored_file:
            transaction.on_commit(lambda: stored_file.storage.delete(stored_file.name))
    messages.success(request, 'Supporting document deleted.')
    return redirect('eqrApp:leave_detail', pk=application.pk)


@require_POST
@login_required
def delete_leave_application(request, pk):
    application = get_object_or_404(
        LeaveApplication.objects.prefetch_related('documents'), pk=pk
    )
    role = get_user_role(request.user)
    is_owner = application.employee.user_id == request.user.id
    if not (is_owner or role == 'hr'):
        raise PermissionDenied
    if application.status not in ('cancelled', 'rejected'):
        messages.error(request, 'Only cancelled or rejected applications may be deleted.')
        return redirect('eqrApp:leave_detail', pk=pk)
    with transaction.atomic():
        LeaveDeletionAudit.objects.create(
            application_reference=application.pk,
            employee=application.employee,
            employee_id_snapshot=application.employee.employee_id,
            employee_name_snapshot=application.employee.full_name,
            leave_type_name=application.leave_type.name,
            start_date=application.start_date,
            end_date=application.end_date,
            previous_status=application.status,
            actor=request.user,
        )
        for document in application.documents.all():
            if document.file:
                document.file.delete(save=False)
        application.delete()
    messages.success(request, 'The cancelled or rejected leave application was deleted.')
    return redirect('eqrApp:leave_list')


@admin_required
def attendance_monthly_report(request):
    month_value = request.GET.get('month', timezone.localdate().strftime('%Y-%m'))
    try:
        report_month = datetime.strptime(month_value, '%Y-%m').date()
    except ValueError:
        messages.error(request, 'Choose a valid report month.')
        return redirect('eqrApp:attendance_list')
    first_day = report_month.replace(day=1)
    last_day = report_month.replace(day=month_calendar.monthrange(report_month.year, report_month.month)[1])
    rows = AttendanceRecord.objects.filter(
        attendance_date__range=(first_day, last_day)
    ).select_related('employee__user').order_by('attendance_date', 'employee__employee_id')
    from io import StringIO
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Employee ID', 'Employee Name', 'Department', 'Date', 'Check In', 'Check Out', 'Status', 'Source', 'Remarks'])
    for record in rows.iterator():
        writer.writerow([
            record.employee.employee_id, record.employee.full_name, record.employee.department,
            record.attendance_date.isoformat(), timezone.localtime(record.check_in).isoformat() if record.check_in else '',
            timezone.localtime(record.check_out).isoformat() if record.check_out else '', record.get_status_display(),
            record.get_source_display(), record.remarks,
        ])
    content = output.getvalue().encode('utf-8-sig')
    key = f'worktrack-reports/attendance/{report_month:%Y-%m}/attendance-{report_month:%Y-%m}.csv'
    if getattr(settings, 'AWS_STORAGE_BUCKET_NAME', ''):
        saved_key = default_storage.save(key, ContentFile(content))
        return redirect(default_storage.url(saved_key))
    response = HttpResponse(content, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="attendance-{report_month:%Y-%m}.csv"'
    return response

@login_required
def approval_queue(request):
    if get_user_role(request.user) not in ('hr', 'supervisor'):
        raise PermissionDenied
    return redirect('eqrApp:leave_list')

@login_required
def download_leave_document(request, pk):
    document = get_object_or_404(
        LeaveDocument.objects.select_related('application__employee__user', 'application__employee__manager'),
        pk=pk,
    )
    if get_user_role(request.user) == 'admin' or not can_view_leave(request.user, document.application):
        raise PermissionDenied
    if not document.file or not document.file.storage.exists(document.file.name):
        raise Http404('The requested file is unavailable.')

    if getattr(settings, 'AWS_STORAGE_BUCKET_NAME', ''):
        return redirect(document.file.storage.url(document.file.name))

    try:
        file_handle = document.file.open('rb')
    except OSError:
        raise Http404('The requested file is unavailable.')
    return FileResponse(file_handle, as_attachment=True, filename=document.original_name)


@admin_required
def system_logs(request):
    # Display only warnings/errors. Never expose stored actor, employee, IP,
    # request path, or raw message fields because they may contain identifiers.
    events = SystemEventLog.objects.filter(severity__in=['warning', 'error', 'critical']).order_by('-created_at')
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    severity = request.GET.get('severity', '').strip()
    if date_from:
        try:
            events = events.filter(created_at__date__gte=datetime.strptime(date_from, '%Y-%m-%d').date())
        except ValueError:
            date_from = ''
    if date_to:
        try:
            events = events.filter(created_at__date__lte=datetime.strptime(date_to, '%Y-%m-%d').date())
        except ValueError:
            date_to = ''
    if severity == 'warning':
        events = events.filter(severity='warning')
    elif severity == 'error':
        # Critical events are grouped under Error in the UI so the page exposes
        # only the two requested severities: Warning and Error.
        events = events.filter(severity__in=['error', 'critical'])
    events = list(events[:250])
    for event in events:
        event.safe_summary = safe_system_event_summary(event)
        event.safe_severity = 'Warning' if event.severity == 'warning' else 'Error'
        event.safe_severity_class = 'warning' if event.severity == 'warning' else 'error'
    return render(request, 'system_logs.html', {
        'page_title': 'System Logs', 'events': events,
        'date_from': date_from, 'date_to': date_to, 'severity': severity,
    })

