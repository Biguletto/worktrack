from django.contrib import admin
from .models import (
    EmployeeProfile,
    AttendanceRecord,
    LeaveType,
    LeaveApplication,
    LeaveDocument,
    LeaveAction,
    AttendanceAudit,
    Holiday,
    LeaveBalance,
    LeaveDeletionAudit,
    SystemEventLog,
)


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = ('employee_id', 'user', 'role', 'department', 'position', 'manager', 'employment_status')
    search_fields = ('employee_id', 'user__first_name', 'user__last_name', 'user__email')
    list_filter = ('role', 'department', 'employment_status')


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('employee', 'attendance_date', 'check_in', 'check_out', 'status', 'source')
    search_fields = ('employee__employee_id', 'employee__user__first_name', 'employee__user__last_name')
    list_filter = ('attendance_date', 'status', 'source')
    date_hierarchy = 'attendance_date'


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_paid', 'requires_document', 'is_active')
    list_filter = ('is_paid', 'requires_document', 'is_active')
    search_fields = ('name', 'code')


class LeaveDocumentInline(admin.TabularInline):
    model = LeaveDocument
    extra = 0
    readonly_fields = ('uploaded_at', 'uploaded_by')


class LeaveActionInline(admin.TabularInline):
    model = LeaveAction
    extra = 0
    readonly_fields = ('actor', 'action', 'comments', 'created_at')
    can_delete = False


@admin.register(LeaveApplication)
class LeaveApplicationAdmin(admin.ModelAdmin):
    list_display = ('id', 'employee', 'leave_type', 'start_date', 'end_date', 'status', 'submitted_at')
    list_filter = ('status', 'leave_type', 'submitted_at')
    search_fields = ('employee__employee_id', 'employee__user__first_name', 'employee__user__last_name')
    inlines = [LeaveDocumentInline, LeaveActionInline]
    readonly_fields = ('submitted_at', 'manager_reviewed_at', 'reviewed_at')


@admin.register(AttendanceAudit)
class AttendanceAuditAdmin(admin.ModelAdmin):
    list_display = ('employee', 'action', 'actor', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('employee__employee_id', 'employee__user__username')
    readonly_fields = ('employee', 'attendance', 'actor', 'action', 'old_values', 'new_values', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ('date', 'name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'leave_type', 'year', 'entitled_days', 'used_days')
    list_filter = ('year', 'leave_type')
    search_fields = ('employee__employee_id', 'employee__user__first_name', 'employee__user__last_name')


@admin.register(LeaveDeletionAudit)
class LeaveDeletionAuditAdmin(admin.ModelAdmin):
    list_display = ('application_reference', 'employee_id_snapshot', 'employee_name_snapshot', 'leave_type_name', 'previous_status', 'actor', 'deleted_at')
    list_filter = ('previous_status', 'deleted_at')
    search_fields = ('employee_id_snapshot', 'employee_name_snapshot', 'leave_type_name')
    readonly_fields = ('application_reference', 'employee', 'employee_id_snapshot', 'employee_name_snapshot', 'leave_type_name', 'start_date', 'end_date', 'previous_status', 'actor', 'deleted_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SystemEventLog)
class SystemEventLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'severity', 'event_type', 'status_code', 'actor', 'request_path')
    list_filter = ('severity', 'event_type', 'status_code', 'created_at')
    search_fields = ('message', 'request_path', 'actor__username')
    readonly_fields = ('event_type', 'severity', 'message', 'request_path', 'http_method', 'status_code', 'actor', 'ip_address', 'details', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
