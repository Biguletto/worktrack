from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

app_name = 'eqrApp'

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.custom_login, name='login'),
    path('logout/', views.custom_logout, name='logout'),
    path('password/change/', views.change_password, name='change_password'),
    path('password/reset/', auth_views.PasswordResetView.as_view(
        template_name='password_reset_form.html',
        email_template_name='password_reset_email.html',
        subject_template_name='password_reset_subject.txt',
        success_url=reverse_lazy('eqrApp:password_reset_done'),
    ), name='password_reset'),
    path('password/reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='password_reset_done.html',
    ), name='password_reset_done'),
    path('password/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='password_reset_confirm.html',
        success_url=reverse_lazy('eqrApp:password_reset_complete'),
    ), name='password_reset_confirm'),
    path('password/reset/complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='password_reset_complete.html',
    ), name='password_reset_complete'),

    # HR and employee dashboards
    path('dashboard/', views.home, name='dashboard'),
    path('employee/dashboard/', views.employee_dashboard, name='employee_dashboard'),
    path('supervisor/dashboard/', views.supervisor_dashboard, name='supervisor_dashboard'),
    path('hr/dashboard/', views.hr_dashboard, name='hr_dashboard'),
    path('administrator/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('administrator/system-logs/', views.system_logs, name='system_logs'),

    # Employee profile administration
    path('employees/', views.employee_list, name='employee_list'),
    path('employees/add/', views.employee_create, name='employee_create'),
    path('employees/<int:pk>/edit/', views.employee_edit, name='employee_edit'),
    path('employees/<int:pk>/reset-account/', views.employee_account_reset, name='employee_account_reset'),
    path('employees/<int:pk>/account-support/', views.employee_account_support_edit, name='employee_account_support_edit'),

    # Daily attendance
    path('attendance/', views.attendance_list, name='attendance_list'),
    path('attendance/qr/status/', views.attendance_qr_status, name='attendance_qr_status'),
    path('attendance/add/', views.attendance_create, name='attendance_create'),
    path('attendance/check-in/', views.check_in, name='check_in'),
    path('attendance/check-out/', views.check_out, name='check_out'),
    path('attendance/kiosk/', views.attendance_kiosk, name='attendance_kiosk'),
    path('attendance/kiosk/run/', views.attendance_kiosk_run, name='attendance_kiosk_run'),
    path('attendance/kiosk/exit/', views.attendance_kiosk_exit, name='attendance_kiosk_exit'),
    path('attendance/kiosk/settings/unlock/', views.attendance_kiosk_settings_unlock, name='attendance_kiosk_settings_unlock'),
    path('attendance/kiosk/settings/lock/', views.attendance_kiosk_settings_lock, name='attendance_kiosk_settings_lock'),
    path('attendance/kiosk/settings/manual/', views.attendance_kiosk_manual, name='attendance_kiosk_manual'),
    path('attendance/kiosk/settings/edit/', views.attendance_kiosk_edit, name='attendance_kiosk_edit'),
    path('attendance/kiosk/scan/', views.attendance_kiosk_scan, name='attendance_kiosk_scan'),
    path('attendance/<int:pk>/edit/', views.attendance_edit, name='attendance_edit'),
    path('attendance/<int:pk>/delete/', views.attendance_delete, name='attendance_delete'),
    path('attendance/reports/monthly.csv', views.attendance_monthly_report, name='attendance_report'),

    # Leave applications and approval workflow
    path('leaves/', views.leave_list, name='leave_list'),
    path('leaves/apply/', views.leave_apply, name='leave_apply'),
    path('leaves/<int:pk>/', views.leave_detail, name='leave_detail'),
    path('leaves/<int:pk>/review/', views.review_leave, name='review_leave'),
    path('leaves/<int:pk>/cancel/', views.cancel_leave, name='cancel_leave'),
    path('leaves/<int:pk>/delete/', views.delete_leave_application, name='delete_leave_application'),
    path('documents/<int:pk>/delete/', views.delete_leave_document, name='delete_leave_document'),
    path('leave-types/', views.leave_type_list, name='leave_type_list'),
    path('leave-types/add/', views.leave_type_create, name='leave_type_create'),
    path('leave-types/<int:pk>/edit/', views.leave_type_edit, name='leave_type_edit'),
    path('leave-types/<int:pk>/delete/', views.leave_type_delete, name='leave_type_delete'),
    path('leave-balances/', views.leave_balance_list, name='leave_balance_list'),
    path('leave-balances/add/', views.leave_balance_create, name='leave_balance_create'),
    path('leave-balances/<int:pk>/edit/', views.leave_balance_edit, name='leave_balance_edit'),
    path('leave-balances/<int:pk>/delete/', views.leave_balance_delete, name='leave_balance_delete'),
    path('holidays/', views.holiday_list, name='holiday_list'),
    path('holidays/add/', views.holiday_create, name='holiday_create'),
    path('holidays/<int:pk>/edit/', views.holiday_edit, name='holiday_edit'),
    path('holidays/<int:pk>/deactivate/', views.holiday_deactivate, name='holiday_deactivate'),
    path('approvals/', views.approval_queue, name='approval_queue'),
    path('documents/<int:pk>/download/', views.download_leave_document, name='download_leave_document'),
]
