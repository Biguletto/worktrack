from datetime import timedelta
import os
import re
import uuid

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class EmployeeProfile(models.Model):
    EMPLOYMENT_STATUS = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('terminated', 'Terminated'),
    ]
    ROLE_CHOICES = [
        ('employee', 'Employee'),
        ('supervisor', 'Supervisor'),
        ('hr', 'HR Personnel'),
        ('admin', 'Administrator'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='employee_profile')
    employee_id = models.CharField(max_length=30, unique=True)
    role = models.CharField(max_length=12, choices=ROLE_CHOICES, default='employee')
    department = models.CharField(max_length=100, blank=True)
    position = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=30, blank=True)
    hire_date = models.DateField(null=True, blank=True)
    manager = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='direct_reports'
    )
    backup_manager = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='backup_direct_reports'
    )
    employment_status = models.CharField(max_length=15, choices=EMPLOYMENT_STATUS, default='active')
    must_change_password = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['employee_id']

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username} ({self.employee_id})'

    @property
    def full_name(self):
        return self.user.get_full_name() or self.user.username

    def clean(self):
        super().clean()
        if self.hire_date and self.hire_date > timezone.localdate():
            raise ValidationError({'hire_date': 'Hire date cannot be later than today.'})
        if self.manager_id and self.manager_id == self.user_id:
            raise ValidationError({'manager': 'An employee cannot supervise themselves.'})
        if self.backup_manager_id and self.backup_manager_id == self.user_id:
            raise ValidationError({'backup_manager': 'An employee cannot be their own backup supervisor.'})
        for field_name in ('manager', 'backup_manager'):
            supervisor_user_id = getattr(self, f'{field_name}_id')
            if not supervisor_user_id:
                continue
            supervisor_profile = EmployeeProfile.objects.filter(user_id=supervisor_user_id).only('role', 'department').first()
            if supervisor_profile:
                if supervisor_profile.role != 'supervisor':
                    raise ValidationError({field_name: 'The selected reporting account must have Supervisor access.'})
                if supervisor_profile.department != self.department:
                    raise ValidationError({field_name: 'The assigned Supervisor must belong to the same department.'})


class Holiday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f'{self.name} ({self.date})'


class LeaveType(models.Model):
    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    requires_document = models.BooleanField(default=False)
    is_paid = models.BooleanField(default=True)
    track_balance = models.BooleanField(default=False)
    default_entitled_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class LeaveBalance(models.Model):
    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name='leave_balances')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name='balances')
    year = models.PositiveSmallIntegerField()
    entitled_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    used_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-year', 'leave_type__name']
        constraints = [
            models.UniqueConstraint(fields=['employee', 'leave_type', 'year'], name='unique_leave_balance_employee_type_year'),
            models.CheckConstraint(condition=Q(entitled_days__gte=0), name='leave_balance_entitled_nonnegative'),
            models.CheckConstraint(condition=Q(used_days__gte=0), name='leave_balance_used_nonnegative'),
            models.CheckConstraint(condition=Q(used_days__lte=models.F('entitled_days')), name='leave_balance_used_not_over_entitlement'),
        ]

    def __str__(self):
        return f'{self.employee} - {self.leave_type} ({self.year})'

    @property
    def available_days(self):
        return self.entitled_days - self.used_days


class LeaveApplication(models.Model):
    STATUS_CHOICES = [
        ('pending_manager', 'Awaiting Supervisor Acknowledgment'),
        ('pending_hr', 'Pending HR Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name='leave_applications')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name='applications')
    start_date = models.DateField()
    end_date = models.DateField()
    is_half_day = models.BooleanField(default=False)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending_hr')
    submitted_at = models.DateTimeField(auto_now_add=True)
    manager_reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='manager_reviewed_leave_applications'
    )
    manager_reviewed_at = models.DateTimeField(null=True, blank=True)
    manager_comments = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='hr_reviewed_leave_applications'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_comments = models.TextField(blank=True)
    last_reminder_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-submitted_at']
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=models.F('start_date')), name='leave_end_on_or_after_start'),
            models.CheckConstraint(condition=Q(is_half_day=False) | Q(start_date=models.F('end_date')), name='half_day_leave_single_date'),
        ]

    def __str__(self):
        return f'{self.employee} - {self.leave_type} ({self.start_date} to {self.end_date})'

    @property
    def requested_days(self):
        if not self.start_date or not self.end_date:
            return 0
        if self.is_half_day:
            if self.start_date != self.end_date or self.start_date.weekday() >= 5:
                return 0
            is_holiday = Holiday.objects.filter(date=self.start_date, is_active=True).exists()
            return 0 if is_holiday else 0.5
        holiday_dates = set(
            Holiday.objects.filter(
                is_active=True, date__gte=self.start_date, date__lte=self.end_date
            ).values_list('date', flat=True)
        )
        days = 0
        cursor = self.start_date
        while cursor <= self.end_date:
            if cursor.weekday() < 5 and cursor not in holiday_dates:
                days += 1
            cursor += timedelta(days=1)
        return days

    def clean(self):
        super().clean()
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'The end date cannot be earlier than the start date.'})
        if self.is_half_day and self.start_date != self.end_date:
            raise ValidationError({'is_half_day': 'A half-day request must use one date only.'})
        if self.is_half_day and self.start_date and self.start_date.weekday() >= 5:
            raise ValidationError({'is_half_day': 'A half-day request must be on a working day.'})
        if self.is_half_day and self.start_date and Holiday.objects.filter(date=self.start_date, is_active=True).exists():
            raise ValidationError({'is_half_day': 'A half-day request cannot be scheduled on a configured holiday.'})


def leave_document_upload_path(instance, filename):
    safe_name = os.path.basename(filename.replace('\\', '/'))
    employee_id = re.sub(r'[^A-Za-z0-9_-]', '_', instance.application.employee.employee_id)
    return f'leave-documents/{employee_id}/{timezone.localdate():%Y/%m}/{safe_name}'


class LeaveDocument(models.Model):
    application = models.ForeignKey(LeaveApplication, on_delete=models.CASCADE, related_name='documents')
    file = models.FileField(upload_to=leave_document_upload_path)
    original_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return self.original_name or self.file.name


class LeaveAction(models.Model):
    ACTION_CHOICES = [
        ('submitted', 'Submitted'),
        ('manager_approved', 'Acknowledged by Supervisor'),
        ('approved', 'Approved by HR'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
        ('deleted', 'Deleted'),
    ]

    application = models.ForeignKey(LeaveApplication, on_delete=models.CASCADE, related_name='actions')
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.get_action_display()} - {self.application_id}'


class LeaveDeletionAudit(models.Model):
    """Retain a minimal audit record after an eligible leave request is deleted."""
    application_reference = models.PositiveBigIntegerField()
    employee = models.ForeignKey(
        EmployeeProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='leave_deletion_audits',
    )
    employee_id_snapshot = models.CharField(max_length=30)
    employee_name_snapshot = models.CharField(max_length=160)
    leave_type_name = models.CharField(max_length=80)
    start_date = models.DateField()
    end_date = models.DateField()
    previous_status = models.CharField(max_length=20)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    deleted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-deleted_at']

    def __str__(self):
        return f'Leave request #{self.application_reference} deleted on {self.deleted_at:%Y-%m-%d}'


class AttendanceRecord(models.Model):
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('late', 'Late'),
        ('half_day', 'Half Day'),
        ('absent', 'Absent'),
        ('on_leave', 'On Leave'),
    ]
    SOURCE_CHOICES = [
        ('self_service', 'QR Kiosk Scan'),
        ('hr', 'HR Entry / Correction'),
        ('admin', 'Administrator Entry / Correction'),
        ('leave_sync', 'Approved Leave'),
        ('scheduled', 'Scheduled Absence Process'),
    ]

    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name='attendance_records')
    attendance_date = models.DateField(default=timezone.localdate)
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='present')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='self_service')
    remarks = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_attendance_entries'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-attendance_date', '-check_in']
        constraints = [
            models.UniqueConstraint(fields=['employee', 'attendance_date'], name='unique_employee_attendance_per_day'),
            models.CheckConstraint(
                condition=Q(check_in__isnull=True) | Q(check_out__isnull=True) | Q(check_out__gte=models.F('check_in')) ,
                name='attendance_checkout_not_before_checkin',
            ),
        ]

    def __str__(self):
        return f'{self.employee} - {self.attendance_date}'

    def clean(self):
        super().clean()
        if self.check_in and self.check_out and self.check_out < self.check_in:
            raise ValidationError({'check_out': 'Check-out cannot be earlier than check-in.'})


class DailyAttendanceQR(models.Model):
    """One signed, employee-specific attendance QR credential per local day."""
    employee = models.ForeignKey(
        EmployeeProfile, on_delete=models.CASCADE, related_name='daily_attendance_qr_codes'
    )
    qr_date = models.DateField()
    nonce = models.UUIDField(default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-qr_date', 'employee__employee_id']
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'qr_date'], name='unique_daily_attendance_qr_employee_date'
            ),
        ]

    def __str__(self):
        return f'Attendance QR for {self.employee} on {self.qr_date}'


class AttendanceAudit(models.Model):
    ACTION_CHOICES = [('created', 'Created'), ('updated', 'Updated'), ('deleted', 'Deleted')]
    employee = models.ForeignKey(EmployeeProfile, on_delete=models.PROTECT, related_name='attendance_audits')
    attendance = models.ForeignKey(
        AttendanceRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_entries'
    )
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_action_display()} attendance for {self.employee} at {self.created_at}'


class SystemEventLog(models.Model):
    """Append-only record of application errors and security-relevant HTTP events."""
    SEVERITY_CHOICES = [
        ('info', 'Information'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]

    event_type = models.CharField(max_length=40, default='application_event')
    severity = models.CharField(max_length=12, choices=SEVERITY_CHOICES, default='info')
    message = models.TextField()
    request_path = models.CharField(max_length=500, blank=True)
    http_method = models.CharField(max_length=12, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='worktrack_system_events')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['severity', '-created_at'], name='system_event_severity_date_idx'),
            models.Index(fields=['status_code', '-created_at'], name='system_event_status_date_idx'),
        ]

    def __str__(self):
        return f'{self.severity.upper()}: {self.message[:90]}'
