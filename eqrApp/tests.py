from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command, CommandError
from django.core import signing
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import EmployeeForm, HolidayForm
from .models import (EmployeeProfile, AttendanceRecord, DailyAttendanceQR, LeaveType, LeaveApplication, LeaveBalance, Holiday, AttendanceAudit, LeaveDeletionAudit, SystemEventLog, LeaveDocument)
from .attendance_qr import build_daily_qr_bundle, validate_daily_qr_token
from .views import leave_balance_errors
from .middleware import get_request_ip


class WorkTrackRoleDashboardTests(TestCase):
    def setUp(self):
        self.employee_user = User.objects.create_user('employee1', password='TestingPass123!')
        self.employee = EmployeeProfile.objects.create(
            user=self.employee_user,
            employee_id='EMP-001',
            role='employee',
            department='Operations',
            position='Staff',
        )

        self.supervisor_user = User.objects.create_user('supervisor1', password='TestingPass123!')
        self.supervisor = EmployeeProfile.objects.create(
            user=self.supervisor_user,
            employee_id='SUP-001',
            role='supervisor',
            department='Operations',
            position='Team Lead',
        )

        self.team_user = User.objects.create_user('team1', password='TestingPass123!')
        self.team_member = EmployeeProfile.objects.create(
            user=self.team_user,
            employee_id='EMP-002',
            role='employee',
            department='Operations',
            position='Associate',
            manager=self.supervisor_user,
        )

        self.other_supervisor_user = User.objects.create_user('supervisor2', password='TestingPass123!')
        EmployeeProfile.objects.create(
            user=self.other_supervisor_user,
            employee_id='SUP-002',
            role='supervisor',
            department='Sales',
            position='Team Lead',
        )
        self.outsider_user = User.objects.create_user('outsider', password='TestingPass123!')
        self.outsider = EmployeeProfile.objects.create(
            user=self.outsider_user,
            employee_id='EMP-003',
            role='employee',
            department='Sales',
            position='Associate',
            manager=self.other_supervisor_user,
        )

        self.hr_user = User.objects.create_user(
            'hr1', password='TestingPass123!', is_staff=True
        )
        self.hr_profile = EmployeeProfile.objects.create(
            user=self.hr_user,
            employee_id='HR-001',
            role='hr',
            department='Human Resources',
            position='HR Officer',
        )

        self.admin_user = User.objects.create_superuser(
            'admin1', 'admin@example.com', 'TestingPass123!'
        )

        self.leave_type, _ = LeaveType.objects.get_or_create(
            code='VL', defaults={'name': 'Vacation Leave', 'is_active': True}
        )
        self.team_application = LeaveApplication.objects.create(
            employee=self.team_member,
            leave_type=self.leave_type,
            start_date=date(2026, 12, 1),
            end_date=date(2026, 12, 2),
            reason='Family trip',
            status='pending_manager',
        )
        self.outsider_application = LeaveApplication.objects.create(
            employee=self.outsider,
            leave_type=self.leave_type,
            start_date=date(2026, 12, 3),
            end_date=date(2026, 12, 4),
            reason='Personal leave',
            status='pending_manager',
        )
        today = timezone.localdate()
        AttendanceRecord.objects.create(
            employee=self.team_member,
            attendance_date=today,
            status='present',
        )
        AttendanceRecord.objects.create(
            employee=self.outsider,
            attendance_date=today,
            status='present',
        )

    def test_each_role_gets_its_own_dashboard(self):
        cases = [
            (self.employee_user, 'eqrApp:employee_dashboard'),
            (self.supervisor_user, 'eqrApp:supervisor_dashboard'),
            (self.hr_user, 'eqrApp:hr_dashboard'),
            (self.admin_user, 'eqrApp:admin_dashboard'),
        ]
        for user, route_name in cases:
            with self.subTest(role=route_name):
                self.client.force_login(user)
                response = self.client.get(reverse('eqrApp:home'))
                self.assertRedirects(response, reverse(route_name), fetch_redirect_response=False)
                dashboard = self.client.get(reverse(route_name))
                self.assertEqual(dashboard.status_code, 200)

    def test_supervisor_only_sees_direct_reports_in_team_attendance(self):
        self.client.force_login(self.supervisor_user)
        response = self.client.get(reverse('eqrApp:attendance_list'))
        self.assertEqual(response.status_code, 200)
        visible_rows = list(response.context['attendance_rows'])
        visible_employee_ids = {row['employee'].pk for row in visible_rows}
        self.assertIn(self.team_member.pk, visible_employee_ids)
        self.assertNotIn(self.outsider.pk, visible_employee_ids)

    def test_supervisor_approval_queue_only_contains_direct_reports(self):
        self.client.force_login(self.supervisor_user)
        response = self.client.get(reverse('eqrApp:leave_list'))
        self.assertEqual(response.status_code, 200)
        visible_ids = {item.pk for item in response.context['pending_applications']}
        self.assertIn(self.team_application.pk, visible_ids)
        self.assertNotIn(self.outsider_application.pk, visible_ids)

    def test_employee_cannot_access_hr_or_admin_dashboard(self):
        self.client.force_login(self.employee_user)
        self.assertEqual(self.client.get(reverse('eqrApp:hr_dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('eqrApp:admin_dashboard')).status_code, 403)

    def test_hr_cannot_access_administrator_dashboard(self):
        self.client.force_login(self.hr_user)
        self.assertEqual(self.client.get(reverse('eqrApp:admin_dashboard')).status_code, 403)

    def test_hr_employee_form_cannot_assign_hr_or_admin_position(self):
        form = EmployeeForm(
            data={
                'username': 'newhr',
                'first_name': 'New',
                'last_name': 'HR',
                'email': 'newhr@example.com',
                'password': 'TestingPass123!',
                'employee_id': 'HR-002',
                'position': 'admin',
                'department': 'Human Resources',
                'phone_number': '',
                'hire_date': '',
                'manager': '',
            },
            allowed_roles=['employee', 'supervisor'],
        )
        self.assertFalse(form.is_valid())
        self.assertIn('position', form.errors)


class WorkTrackImprovementTests(TestCase):
    def setUp(self):
        self.employee_user = User.objects.create_user('improved_employee', password='TestingPass123!')
        self.employee = EmployeeProfile.objects.create(
            user=self.employee_user, employee_id='IMP-001', role='employee',
            department='Operations', position='Staff', must_change_password=False,
        )
        self.supervisor_user = User.objects.create_user('improved_supervisor', password='TestingPass123!')
        self.supervisor = EmployeeProfile.objects.create(
            user=self.supervisor_user, employee_id='IMP-SUP', role='supervisor',
            department='Operations', position='Team Lead',
        )
        self.backup_user = User.objects.create_user('backup_supervisor', password='TestingPass123!')
        EmployeeProfile.objects.create(
            user=self.backup_user, employee_id='IMP-BACK', role='supervisor',
            department='Operations', position='Backup Lead',
        )
        self.employee.manager = self.supervisor_user
        self.employee.backup_manager = self.backup_user
        self.employee.save()
        self.hr_user = User.objects.create_user('improved_hr', password='TestingPass123!', is_staff=True)
        self.hr_profile = EmployeeProfile.objects.create(
            user=self.hr_user, employee_id='IMP-HR', role='hr',
            department='Human Resources', position='HR Officer',
        )
        self.admin_user = User.objects.create_superuser(
            'improved_admin', 'improved.admin@example.com', 'TestingPass123!'
        )
        self.leave_type, _ = LeaveType.objects.get_or_create(
            code='VL', defaults={'name': 'Vacation Leave', 'is_active': True, 'track_balance': True}
        )

    def test_company_csv_is_admin_only_and_uses_local_times(self):
        today = timezone.localdate()
        check_in = timezone.now()
        AttendanceRecord.objects.create(employee=self.employee, attendance_date=today, check_in=check_in)
        url = reverse('eqrApp:attendance_report')
        for user in (self.employee_user, self.supervisor_user, self.hr_user):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin_user)
        with patch('eqrApp.views.default_storage.save') as save_file:
            response = self.client.get(url)
        self.assertContains(response, self.employee.employee_id)
        self.assertContains(response, timezone.localtime(check_in).isoformat())
        save_file.assert_not_called()

    def test_required_document_survives_deletion_and_is_checked_at_approval(self):
        self.leave_type.requires_document = True
        self.leave_type.save(update_fields=['requires_document'])
        application = LeaveApplication.objects.create(
            employee=self.employee, leave_type=self.leave_type, start_date=timezone.localdate(),
            end_date=timezone.localdate(), reason='Appointment', status='pending_hr',
            manager_reviewed_at=timezone.now(),
        )
        self.client.force_login(self.hr_user)
        self.client.post(reverse('eqrApp:review_leave', args=[application.pk]), {'decision': 'approve'})
        application.refresh_from_db()
        self.assertEqual(application.status, 'pending_hr')
        document = LeaveDocument.objects.create(application=application, file='example.pdf', original_name='example.pdf')
        self.client.force_login(self.employee_user)
        self.client.post(reverse('eqrApp:delete_leave_document', args=[document.pk]))
        self.assertTrue(application.documents.filter(pk=document.pk).exists())
        second = LeaveDocument.objects.create(application=application, file='second.pdf', original_name='second.pdf')
        self.client.post(reverse('eqrApp:delete_leave_document', args=[second.pk]))
        self.assertFalse(application.documents.filter(pk=second.pk).exists())

    def test_absences_and_roster_respect_hire_date(self):
        target = date(2026, 12, 7)
        self.employee.hire_date = target + timedelta(days=1)
        self.employee.save(update_fields=['hire_date'])
        self.client.force_login(self.admin_user)
        with patch('django.utils.timezone.localdate', return_value=target):
            with self.assertRaises(CommandError):
                call_command('mark_daily_absences', '--date', (target + timedelta(days=1)).isoformat())
            call_command('mark_daily_absences', '--date', target.isoformat())
            roster = self.client.get(reverse('eqrApp:attendance_list'), {'date': target.isoformat()})
        self.assertFalse(AttendanceRecord.objects.filter(employee=self.employee).exists())
        self.assertTrue(AttendanceRecord.objects.filter(employee=self.supervisor, status='absent').exists())
        self.assertNotContains(roster, self.employee.employee_id)

    def test_backup_supervisor_can_see_and_review_team_request(self):
        application = LeaveApplication.objects.create(
            employee=self.employee, leave_type=self.leave_type,
            start_date=date(2026, 12, 7), end_date=date(2026, 12, 7),
            reason='Family matter', status='pending_manager',
        )
        AttendanceRecord.objects.create(
            employee=self.employee, attendance_date=date(2026, 12, 7), status='present'
        )
        self.client.force_login(self.backup_user)
        queue = self.client.get(reverse('eqrApp:leave_list'))
        self.assertEqual(queue.status_code, 200)
        self.assertIn(application.pk, [item.pk for item in queue.context['pending_applications']])
        result = self.client.post(reverse('eqrApp:review_leave', args=[application.pk]), {'decision': 'acknowledge'})
        self.assertRedirects(result, reverse('eqrApp:leave_detail', args=[application.pk]), fetch_redirect_response=False)
        application.refresh_from_db()
        self.assertEqual(application.status, 'pending_hr')
        self.assertEqual(application.manager_reviewed_by, self.backup_user)
        self.assertIsNone(application.reviewed_by)

    def test_leave_duration_excludes_weekends_and_configured_holidays(self):
        Holiday.objects.create(date=date(2026, 12, 25), name='Configured Christmas holiday')
        application = LeaveApplication.objects.create(
            employee=self.employee, leave_type=self.leave_type,
            start_date=date(2026, 12, 24), end_date=date(2026, 12, 28),
            reason='Family visit', status='pending_hr',
        )
        self.assertEqual(application.requested_days, 2)

    def test_half_day_leave_requires_a_single_date(self):
        from .forms import LeaveApplicationForm
        form = LeaveApplicationForm(data={
            'leave_type': self.leave_type.pk,
            'start_date': '2026-12-07',
            'end_date': '2026-12-08',
            'is_half_day': 'on',
            'reason': 'Appointment',
        })
        self.assertFalse(form.is_valid())
        self.assertTrue('is_half_day' in form.errors or 'end_date' in form.errors)

    def test_half_day_on_weekend_or_holiday_has_no_working_day_value(self):
        weekend_application = LeaveApplication(
            employee=self.employee, leave_type=self.leave_type,
            start_date=date(2026, 12, 6), end_date=date(2026, 12, 6),
            is_half_day=True, reason='Weekend request',
        )
        self.assertEqual(weekend_application.requested_days, 0)
        Holiday.objects.create(date=date(2026, 12, 7), name='Company holiday')
        holiday_application = LeaveApplication(
            employee=self.employee, leave_type=self.leave_type,
            start_date=date(2026, 12, 7), end_date=date(2026, 12, 7),
            is_half_day=True, reason='Holiday request',
        )
        self.assertEqual(holiday_application.requested_days, 0)

    def test_balance_validation_accounts_for_existing_pending_requests(self):
        self.leave_type.track_balance = True
        self.leave_type.save(update_fields=['track_balance'])
        LeaveBalance.objects.create(
            employee=self.employee, leave_type=self.leave_type,
            year=2026, entitled_days=3, used_days=0,
        )
        LeaveApplication.objects.create(
            employee=self.employee, leave_type=self.leave_type,
            start_date=date(2026, 12, 1), end_date=date(2026, 12, 2),
            reason='Already pending', status='pending_manager',
        )
        errors = leave_balance_errors(
            self.employee, self.leave_type,
            date(2026, 12, 7), date(2026, 12, 8), False,
        )
        self.assertTrue(errors)
        self.assertIn('Insufficient', errors[0])

    def test_hr_company_attendance_module_is_removed_and_admin_cannot_edit_records(self):
        record = AttendanceRecord.objects.create(
            employee=self.employee, attendance_date=date(2026, 12, 7),
            status='late', remarks='Correction candidate',
        )
        self.client.force_login(self.hr_user)
        self.client.raise_request_exception = False
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_create')).status_code, 403)
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_edit', args=[record.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('eqrApp:attendance_delete', args=[record.pk])).status_code, 403)

        self.client.force_login(self.admin_user)
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_edit', args=[record.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('eqrApp:attendance_delete', args=[record.pk])).status_code, 403)
        self.assertTrue(AttendanceRecord.objects.filter(pk=record.pk).exists())

    def test_deleting_rejected_leave_keeps_a_deletion_audit(self):
        application = LeaveApplication.objects.create(
            employee=self.employee, leave_type=self.leave_type,
            start_date=date(2026, 12, 7), end_date=date(2026, 12, 7),
            reason='No longer needed', status='rejected',
        )
        reference = application.pk
        self.client.force_login(self.employee_user)
        response = self.client.post(reverse('eqrApp:delete_leave_application', args=[reference]))
        self.assertRedirects(response, reverse('eqrApp:leave_list'), fetch_redirect_response=False)
        self.assertFalse(LeaveApplication.objects.filter(pk=reference).exists())
        audit = LeaveDeletionAudit.objects.get(application_reference=reference)
        self.assertEqual(audit.previous_status, 'rejected')
        self.assertEqual(audit.employee_id_snapshot, self.employee.employee_id)

    def test_new_account_is_redirected_to_password_change(self):
        self.employee.must_change_password = True
        self.employee.save(update_fields=['must_change_password', 'updated_at'])
        self.client.force_login(self.employee_user)
        response = self.client.get(reverse('eqrApp:employee_dashboard'))
        self.assertRedirects(response, reverse('eqrApp:change_password'), fetch_redirect_response=False)
        change_page = self.client.get(reverse('eqrApp:change_password'))
        self.assertEqual(change_page.status_code, 200)


    def test_kiosk_scan_preserves_half_day_leave_attendance_status(self):
        target = date(2026, 12, 8)
        application = LeaveApplication.objects.create(
            employee=self.employee, leave_type=self.leave_type,
            start_date=target, end_date=target, is_half_day=True,
            reason='Half-day appointment', status='approved',
        )
        self.assertEqual(application.requested_days, 0.5)
        record = AttendanceRecord.objects.create(
            employee=self.employee, attendance_date=target,
            status='half_day', source='leave_sync', remarks='Approved half-day leave.',
        )
        qr_bundle = build_daily_qr_bundle(self.employee, qr_date=target)
        self.client.force_login(self.admin_user)
        self.client.post(reverse('eqrApp:attendance_kiosk'), {'username': self.admin_user.username, 'password': 'TestingPass123!'})
        with patch('eqrApp.views.timezone.localdate', return_value=target):
            response = self.client.post(reverse('eqrApp:attendance_kiosk_scan'), {'token': qr_bundle['token']})
        self.assertEqual(response.status_code, 200)
        record.refresh_from_db()
        self.assertEqual(record.status, 'half_day')
        self.assertEqual(record.source, 'leave_sync')
        self.assertIsNotNone(record.check_in)

        employee_client = self.client_class()
        employee_client.force_login(self.employee_user)
        with patch('eqrApp.views.timezone.localdate', return_value=target):
            roster = employee_client.get(reverse('eqrApp:attendance_list'), {'status': 'half_day'})
        self.assertEqual([row['status_code'] for row in roster.context['attendance_rows']], ['half_day'])

    def test_daily_absence_command_skips_approved_leave(self):
        target = date(2026, 12, 7)  # Monday
        LeaveApplication.objects.create(
            employee=self.employee, leave_type=self.leave_type,
            start_date=target, end_date=target, reason='Approved leave', status='approved',
        )
        with patch('eqrApp.management.commands.mark_daily_absences.timezone.localdate', return_value=target):
            call_command('mark_daily_absences', '--date', target.isoformat(), verbosity=0)
        self.assertFalse(AttendanceRecord.objects.filter(
            employee=self.employee, attendance_date=target, status='absent'
        ).exists())

    def test_leave_type_in_use_cannot_be_deleted(self):
        LeaveApplication.objects.create(
            employee=self.employee, leave_type=self.leave_type,
            start_date=date(2026, 12, 9), end_date=date(2026, 12, 9),
            reason='Uses this leave type', status='pending_hr',
        )
        self.client.force_login(self.hr_user)
        response = self.client.post(reverse('eqrApp:leave_type_delete', args=[self.leave_type.pk]))
        self.assertRedirects(response, reverse('eqrApp:leave_type_list'), fetch_redirect_response=False)
        self.assertTrue(LeaveType.objects.filter(pk=self.leave_type.pk).exists())

    def test_hr_can_open_leave_balance_and_holiday_management(self):
        self.client.force_login(self.hr_user)
        balance_page = self.client.get(reverse('eqrApp:leave_balance_list'), follow=True)
        self.assertRedirects(balance_page, reverse('eqrApp:leave_list'))
        self.assertContains(balance_page, 'Company leave balances')
        self.assertEqual(self.client.get(reverse('eqrApp:holiday_list')).status_code, 200)

    def test_new_account_uses_fixed_job_position_and_separate_access_role(self):
        form = EmployeeForm(
            data={
                'username': 'position_employee',
                'first_name': 'Position',
                'last_name': 'Employee',
                'email': 'position.employee@example.com',
                'password': 'TestingPass123!',
                'employee_id': 'POS-001',
                'position': 'Marketing Manager',
                'role': 'supervisor',
                'department': 'Marketing',
                'phone_number': '',
                'hire_date': '',
                'manager': '',
                'backup_manager': '',
            },
            allowed_roles=['employee', 'supervisor'],
        )
        self.assertIn('role', form.fields)
        self.assertNotIn('employment_status', form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        profile = form.save(commit=False)
        self.assertEqual(profile.role, 'supervisor')
        self.assertEqual(profile.position, 'Marketing Manager')
        self.assertEqual(form.cleaned_data['role'], 'supervisor')
        self.assertEqual(profile.employment_status, 'active')

    def test_hr_and_admin_roles_are_not_assignable_through_hr_employee_form(self):
        for restricted_position in ('hr', 'admin'):
            with self.subTest(position=restricted_position):
                form = EmployeeForm(
                    data={
                        'username': f'new_{restricted_position}_personnel',
                        'first_name': 'New',
                        'last_name': 'Personnel',
                        'email': f'new.{restricted_position}@example.com',
                        'password': 'TestingPass123!',
                        'employee_id': f'NEW-{restricted_position.upper()}-1',
                        'position': 'Marketing Manager',
                        'role': restricted_position,
                        'department': 'Marketing',
                        'phone_number': '',
                        'hire_date': '',
                        'manager': '',
                        'backup_manager': '',
                    },
                    allowed_roles=['employee', 'supervisor'],
                )
                self.assertFalse(form.is_valid())
                self.assertIn('role', form.errors)

    def test_edit_account_retains_employment_status_field(self):
        form = EmployeeForm(
            instance=self.employee,
            instance_user=self.employee_user,
            allowed_roles=['employee', 'supervisor'],
        )
        self.assertIn('employment_status', form.fields)
        self.assertEqual(form.fields['position'].initial, 'Staff')
        self.assertEqual(form.fields['role'].initial, 'employee')


    def test_administrator_has_read_only_employee_account_support(self):
        self.client.force_login(self.admin_user)
        self.client.raise_request_exception = False
        self.assertEqual(self.client.get(reverse('eqrApp:employee_list')).status_code, 200)
        response = self.client.post(reverse('eqrApp:employee_create'), {
            'username': 'new_hr_user',
            'first_name': 'New',
            'last_name': 'HR',
            'email': 'new.hr.user@example.com',
            'password': 'TestingPass123!',
            'employee_id': 'NEW-HR-002',
            'position': 'HR Manager',
            'role': 'hr',
            'department': 'HR',
            'phone_number': '',
            'hire_date': '',
            'manager': '',
            'backup_manager': '',
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username='new_hr_user').exists())

    def test_hr_can_create_employee_and_supervisor_accounts(self):
        marketing_supervisor_user = User.objects.create_user('marketing_supervisor', password='TestingPass123!')
        EmployeeProfile.objects.create(
            user=marketing_supervisor_user, employee_id='MKT-SUP-01', role='supervisor',
            department='Marketing', position='Marketing Manager',
        )
        self.client.force_login(self.hr_user)
        response = self.client.post(reverse('eqrApp:employee_create'), {
            'first_name': 'New',
            'last_name': 'Employee',
            'email': 'new.employee@example.com',
            'employee_id': 'NEW-EMP-002',
            'position': 'Sales Representative',
            'role': 'employee',
            'department': 'Marketing',
            'phone_number': '',
            'hire_date': '',
            'manager': str(marketing_supervisor_user.pk),
            'backup_manager': '',
        })
        self.assertRedirects(response, reverse('eqrApp:employee_list'), fetch_redirect_response=False)
        created_user = User.objects.get(username='employeenew')
        profile = created_user.employee_profile
        self.assertEqual(profile.role, 'employee')
        self.assertEqual(profile.employment_status, 'active')
        self.assertTrue(profile.must_change_password)
        self.assertFalse(profile.user.is_staff)
        self.assertEqual(profile.department, 'Marketing')
        self.assertTrue(created_user.check_password('employee123'))

    def test_administrator_has_it_tools_but_not_hr_configuration_pages(self):
        self.client.force_login(self.admin_user)
        self.assertEqual(self.client.get(reverse('eqrApp:admin_dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('eqrApp:system_logs')).status_code, 200)
        self.client.raise_request_exception = False
        self.assertEqual(self.client.get(reverse('eqrApp:employee_list')).status_code, 200)
        restricted_urls = [
            reverse('eqrApp:employee_create'),
            reverse('eqrApp:leave_type_list'),
            reverse('eqrApp:leave_balance_list'),
            reverse('eqrApp:holiday_list'),
        ]
        for url in restricted_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_hr_can_manage_people_but_cannot_access_it_system_logs_or_self_apply_leave(self):
        self.client.force_login(self.hr_user)
        self.assertEqual(self.client.get(reverse('eqrApp:employee_list')).status_code, 200)
        self.client.raise_request_exception = False
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('eqrApp:system_logs')).status_code, 403)
        self.assertEqual(self.client.get(reverse('eqrApp:leave_apply')).status_code, 403)

    def test_administrator_leave_queue_and_detail_are_read_only(self):
        application = LeaveApplication.objects.create(
            employee=self.employee, leave_type=self.leave_type,
            start_date=timezone.localdate() + timedelta(days=5),
            end_date=timezone.localdate() + timedelta(days=5),
            reason='Read-only review test', status='pending_hr',
        )
        self.client.force_login(self.admin_user)
        queue = self.client.get(reverse('eqrApp:approval_queue'))
        self.assertEqual(queue.status_code, 403)
        detail = self.client.get(reverse('eqrApp:leave_detail', args=[application.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertFalse(detail.context['can_hr_review'])
        self.client.raise_request_exception = False
        response = self.client.post(reverse('eqrApp:review_leave', args=[application.pk]), {'decision': 'approve'})
        self.assertEqual(response.status_code, 403)
        application.refresh_from_db()
        self.assertEqual(application.status, 'pending_hr')

    def test_system_event_middleware_records_access_denial(self):
        self.client.force_login(self.employee_user)
        self.client.raise_request_exception = False
        response = self.client.get(reverse('eqrApp:system_logs'))
        self.assertEqual(response.status_code, 403)
        event = SystemEventLog.objects.filter(status_code=403, event_type='http_error').latest('created_at')
        self.assertEqual(event.actor, self.employee_user)
        self.assertEqual(event.request_path, reverse('eqrApp:system_logs'))

    def test_hr_can_terminate_an_employee_account(self):
        self.client.force_login(self.hr_user)
        response = self.client.post(reverse('eqrApp:employee_edit', args=[self.employee.pk]), {
            'first_name': 'Improved',
            'last_name': 'Employee',
            'email': 'improved.employee@example.com',
            'password': '',
            'employee_id': self.employee.employee_id,
            'position': 'Staff',
            'role': 'employee',
            'department': 'Operations',
            'phone_number': '',
            'hire_date': '',
            'manager': self.supervisor_user.pk,
            'backup_manager': self.backup_user.pk,
            'employment_status': 'terminated',
        })
        self.assertRedirects(response, reverse('eqrApp:employee_list'), fetch_redirect_response=False)
        self.employee.refresh_from_db()
        self.employee_user.refresh_from_db()
        self.assertEqual(self.employee.employment_status, 'terminated')
        self.assertFalse(self.employee_user.is_active)

    def test_fixed_leave_catalogue_is_shared_across_employee_forms(self):
        from .forms import LeaveApplicationForm
        LeaveType.objects.create(name='Custom Department Leave', code='CUSTOM', is_active=True)
        form = LeaveApplicationForm()
        available_codes = set(form.fields['leave_type'].queryset.values_list('code', flat=True))
        self.assertEqual(available_codes, {'SIL', 'MAT', 'PAT', 'VL', 'SL', 'EL', 'BL'})

    def test_client_ip_header_is_only_trusted_from_configured_proxy_peers(self):
        factory = RequestFactory()
        with override_settings(WORKTRACK_TRUSTED_PROXY_IPS=['127.0.0.1/32']):
            request = factory.get('/', HTTP_X_REAL_IP='198.51.100.44')
            request.META['REMOTE_ADDR'] = '203.0.113.7'
            self.assertEqual(get_request_ip(request), '203.0.113.7')

            proxied_request = factory.get('/', HTTP_X_REAL_IP='198.51.100.44')
            proxied_request.META['REMOTE_ADDR'] = '127.0.0.1'
            self.assertEqual(get_request_ip(proxied_request), '198.51.100.44')

    def test_django_admin_console_route_is_not_exposed(self):
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 404)

    def test_password_recovery_pages_are_available_from_login(self):
        login_page = self.client.get(reverse('eqrApp:login'))
        self.assertContains(login_page, reverse('eqrApp:password_reset'))
        reset_page = self.client.get(reverse('eqrApp:password_reset'))
        self.assertEqual(reset_page.status_code, 200)
        self.assertEqual(self.client.get(reverse('eqrApp:password_reset_done')).status_code, 200)

    def test_employee_leave_application_action_is_inside_leave_requests(self):
        self.client.force_login(self.employee_user)
        response = self.client.get(reverse('eqrApp:leave_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'New application')
        self.assertContains(response, reverse('eqrApp:leave_apply'))
        self.assertNotContains(response, 'Apply for Leave', html=False)

    @patch('eqrApp.management.commands.create_hr_user.getpass', side_effect=['TempSecurePass123!', 'TempSecurePass123!'])
    def test_initial_hr_provisioning_command_uses_fixed_hr_department_and_position(self, mocked_getpass):
        from io import StringIO
        output = StringIO()
        call_command(
            'create_hr_user', '--username', 'command_hr', '--email', 'command.hr@example.com',
            '--employee-id', 'CMD-HR-001', stdout=output,
        )
        profile = User.objects.get(username='command_hr').employee_profile
        self.assertEqual(profile.role, 'hr')
        self.assertEqual(profile.position, 'HR Manager')
        self.assertEqual(profile.department, 'HR')
        self.assertTrue(profile.must_change_password)
        self.assertIn('Created HR Personnel account', output.getvalue())
        self.assertEqual(mocked_getpass.call_count, 2)

    def test_login_lockout_uses_worktrack_error_page(self):
        response = None
        for _ in range(6):
            response = self.client.post(reverse('eqrApp:login'), {
                'username': 'lockout_test_user',
                'password': 'incorrect-password',
            })
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, 'Sign-in temporarily locked', status_code=429)

    def test_holiday_form_rejects_past_dates(self):
        past_date = timezone.localdate() - timedelta(days=1)
        form = HolidayForm(data={
            'date': past_date.isoformat(),
            'name': 'Past holiday',
            'is_active': 'on',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('date', form.errors)
        self.assertEqual(form.fields['date'].widget.attrs['min'], timezone.localdate().isoformat())

    def test_holiday_page_renders_month_calendar(self):
        self.client.force_login(self.hr_user)
        response = self.client.get(reverse('eqrApp:holiday_list'), {'month': timezone.localdate().strftime('%Y-%m')})
        self.assertEqual(response.status_code, 200)
        self.assertIn('calendar_weeks', response.context)
        self.assertEqual(len(response.context['calendar_weeks'][0]), 7)

    def test_attendance_records_are_grouped_by_employee(self):
        today = timezone.localdate()
        AttendanceRecord.objects.create(
            employee=self.employee, attendance_date=today, status='present'
        )
        AttendanceRecord.objects.create(
            employee=self.employee, attendance_date=today - timedelta(days=1), status='late'
        )
        AttendanceRecord.objects.create(
            employee=self.supervisor, attendance_date=today, status='present'
        )
        self.client.force_login(self.hr_user)
        self.client.raise_request_exception = False
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_list')).status_code, 403)
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('eqrApp:attendance_list'))
        self.assertEqual(response.status_code, 200)
        rows = response.context['attendance_rows']
        employee_row = next(row for row in rows if row['employee'].pk == self.employee.pk)
        self.assertIsNotNone(employee_row)
        self.assertEqual(employee_row['status_code'], 'present')
        self.assertEqual(response.context['selected_date'], today)

    def test_only_employee_and_supervisor_dashboards_show_daily_qr_codes(self):
        dashboard_cases = [
            (self.employee_user, 'eqrApp:employee_dashboard'),
            (self.supervisor_user, 'eqrApp:supervisor_dashboard'),
        ]
        for user, route_name in dashboard_cases:
            with self.subTest(role=route_name):
                self.client.force_login(user)
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertIsNotNone(response.context['attendance_qr'])
                self.assertTrue(response.context['attendance_qr']['image_data_uri'].startswith('data:image/png;base64,'))
        self.client.force_login(self.hr_user)
        hr_response = self.client.get(reverse('eqrApp:hr_dashboard'))
        self.assertEqual(hr_response.status_code, 200)
        self.assertNotIn('attendance_qr', hr_response.context)
        self.client.raise_request_exception = False
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_qr_status')).status_code, 403)

    def test_daily_qr_is_unique_per_employee_and_expires_after_midnight(self):
        today = timezone.localdate()
        employee_bundle = build_daily_qr_bundle(self.employee, qr_date=today)
        supervisor_bundle = build_daily_qr_bundle(self.supervisor, qr_date=today)
        self.assertNotEqual(employee_bundle['token'], supervisor_bundle['token'])
        self.assertEqual(DailyAttendanceQR.objects.filter(qr_date=today).count(), 2)
        self.assertEqual(
            validate_daily_qr_token(employee_bundle['token'], today=today).employee_id,
            self.employee.pk,
        )

        yesterday = today - timedelta(days=1)
        yesterday_bundle = build_daily_qr_bundle(self.employee, qr_date=yesterday)
        with self.assertRaises(signing.BadSignature):
            validate_daily_qr_token(yesterday_bundle['token'], today=today)

    def test_disabled_login_invalidates_its_existing_daily_qr(self):
        bundle = build_daily_qr_bundle(self.employee)
        self.employee_user.is_active = False
        self.employee_user.save(update_fields=['is_active'])
        with self.assertRaises(signing.BadSignature):
            validate_daily_qr_token(bundle['token'])

    def test_generate_daily_attendance_qr_command_initializes_active_eligible_profiles(self):
        call_command('generate_daily_attendance_qr')
        today = timezone.localdate()
        self.assertTrue(DailyAttendanceQR.objects.filter(employee=self.employee, qr_date=today).exists())
        self.assertTrue(DailyAttendanceQR.objects.filter(employee=self.supervisor, qr_date=today).exists())
        self.assertFalse(DailyAttendanceQR.objects.filter(employee=self.hr_profile, qr_date=today).exists())

    def test_attendance_kiosk_requires_admin_password_activation_and_is_standalone(self):
        kiosk_url = reverse('eqrApp:attendance_kiosk')
        run_url = reverse('eqrApp:attendance_kiosk_run')
        scan_url = reverse('eqrApp:attendance_kiosk_scan')
        for staff_user in (self.employee_user, self.supervisor_user, self.hr_user):
            with self.subTest(user=staff_user.username):
                self.client.force_login(staff_user)
                self.assertEqual(self.client.get(kiosk_url).status_code, 403)
                self.assertEqual(self.client.post(scan_url, {'token': 'invalid'}).status_code, 403)

        self.client.force_login(self.admin_user)
        activation = self.client.get(kiosk_url)
        self.assertEqual(activation.status_code, 200)
        self.assertContains(activation, 'Activate attendance kiosk')
        self.assertContains(activation, 'kiosk-activation-username')
        self.assertNotContains(activation, 'kiosk-video')
        self.assertEqual(self.client.post(scan_url, {'token': 'invalid'}).status_code, 403)

        activated = self.client.post(kiosk_url, {'username': self.admin_user.username, 'password': 'TestingPass123!'})
        self.assertRedirects(activated, run_url, fetch_redirect_response=False)
        kiosk_response = self.client.get(run_url)
        self.assertEqual(kiosk_response.status_code, 200)
        self.assertEqual(kiosk_response['Cache-Control'], 'no-store, private')
        self.assertContains(kiosk_response, 'Live QR Attendance Scanner')
        self.assertContains(kiosk_response, 'kiosk-exit-dialog')
        self.assertNotContains(kiosk_response, 'side-nav')
        self.assertNotContains(kiosk_response, 'System Overview')
        self.assertContains(kiosk_response, 'kiosk-log-body')
        self.assertNotContains(kiosk_response, 'name="token"')
        self.assertContains(kiosk_response, 'waitForZXingAndStart')
        self.assertContains(kiosk_response, 'Ctrl+0')
        self.assertTrue(SystemEventLog.objects.filter(event_type='kiosk_activated', actor=self.admin_user).exists())

    @override_settings(ATTENDANCE_LATE_AFTER='23:59')
    def test_kiosk_qr_scan_records_check_in_then_check_out_once(self):
        today = timezone.localdate()
        qr_bundle = build_daily_qr_bundle(self.employee, qr_date=today)
        self.client.force_login(self.admin_user)
        self.client.post(reverse('eqrApp:attendance_kiosk'), {'username': self.admin_user.username, 'password': 'TestingPass123!'})
        scan_url = reverse('eqrApp:attendance_kiosk_scan')

        check_in_response = self.client.post(scan_url, {'token': qr_bundle['token']})
        self.assertEqual(check_in_response.status_code, 200)
        self.assertEqual(check_in_response.json()['action'], 'check_in')
        payload = check_in_response.json()
        self.assertIn('record_id', payload)
        self.assertEqual(payload['employee_id'], self.employee.employee_id)
        self.assertEqual(payload['status_code'], 'present')
        self.assertTrue(payload['last_updated'])
        record = AttendanceRecord.objects.get(employee=self.employee, attendance_date=today)
        self.assertIsNotNone(record.check_in)
        self.assertEqual(record.recorded_by, self.admin_user)

        duplicate = self.client.post(scan_url, {'token': qr_bundle['token']})
        self.assertEqual(duplicate.status_code, 409)
        record.refresh_from_db()
        self.assertIsNone(record.check_out)
        self.assertEqual(AttendanceAudit.objects.filter(employee=self.employee).count(), 1)
        with patch('eqrApp.views.timezone.now', return_value=record.check_in + timedelta(seconds=10)):
            check_out_response = self.client.post(scan_url, {'token': qr_bundle['token']})
        self.assertEqual(check_out_response.status_code, 200)
        self.assertEqual(check_out_response.json()['action'], 'check_out')
        record.refresh_from_db()
        self.assertIsNotNone(record.check_out)

        third_scan_response = self.client.post(scan_url, {'token': qr_bundle['token']})
        self.assertEqual(third_scan_response.status_code, 409)
        self.assertEqual(AttendanceAudit.objects.filter(employee=self.employee).count(), 2)

    def test_kiosk_rejects_qr_scan_for_full_day_approved_leave(self):
        today = timezone.localdate()
        LeaveApplication.objects.create(
            employee=self.employee, leave_type=self.leave_type,
            start_date=today, end_date=today, is_half_day=False,
            reason='Approved leave', status='approved',
        )
        qr_bundle = build_daily_qr_bundle(self.employee, qr_date=today)
        self.client.force_login(self.admin_user)
        self.client.post(reverse('eqrApp:attendance_kiosk'), {'username': self.admin_user.username, 'password': 'TestingPass123!'})
        response = self.client.post(reverse('eqrApp:attendance_kiosk_scan'), {'token': qr_bundle['token']})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(AttendanceRecord.objects.filter(employee=self.employee, attendance_date=today).exists())

    def test_employee_cannot_bypass_kiosk_with_old_self_service_checkin(self):
        self.client.force_login(self.employee_user)
        response = self.client.post(reverse('eqrApp:check_in'))
        self.assertEqual(response.status_code, 403)

    def test_hr_company_attendance_is_removed_and_admin_attendance_is_read_only(self):
        record = AttendanceRecord.objects.create(
            employee=self.employee, attendance_date=timezone.localdate(), status='present'
        )
        self.client.force_login(self.hr_user)
        self.client.raise_request_exception = False
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_edit', args=[record.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_create')).status_code, 403)
        self.client.force_login(self.admin_user)
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_edit', args=[record.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('eqrApp:attendance_create')).status_code, 403)
        self.assertEqual(self.client.post(reverse('eqrApp:attendance_delete', args=[record.pk])).status_code, 403)
        self.assertTrue(AttendanceRecord.objects.filter(pk=record.pk).exists())



class LatestRevisionFeatureTests(TestCase):
    def setUp(self):
        self.hr_user = User.objects.create_user('revision_hr', password='TestingPass123!', is_staff=True)
        self.hr_profile = EmployeeProfile.objects.create(
            user=self.hr_user, employee_id='REV-HR-01', role='hr', department='HR', position='HR Assistant'
        )
        self.admin_user = User.objects.create_superuser('revision_admin', 'admin2@example.com', 'TestingPass123!')
        self.employee_user = User.objects.create_user(
            'maya.santos', password='TestingPass123!', first_name='Maya', last_name='Santos'
        )
        self.marketing_supervisor_user = User.objects.create_user('marketing_manager', password='TestingPass123!')
        self.marketing_supervisor = EmployeeProfile.objects.create(
            user=self.marketing_supervisor_user, employee_id='MKT-SUP-01', role='supervisor',
            department='Marketing', position='Marketing Manager'
        )
        self.employee = EmployeeProfile.objects.create(
            user=self.employee_user, employee_id='MKT-023', role='employee',
            department='Marketing', position='Sales Representative', manager=self.marketing_supervisor_user
        )

    def test_department_and_job_position_choices_are_fixed_and_dependent(self):
        form = EmployeeForm(allowed_roles=['employee', 'supervisor'])
        self.assertEqual([value for value, _label in form.fields['department'].choices if value],
                         ['HR', 'IT', 'Finance', 'Marketing', 'Administration', 'Management'])
        from .forms import DEPARTMENT_POSITION_MAP
        expected_positions = {
            'HR': ['HR Manager', 'HR Assistant', 'Recruitment Officer'],
            'IT': ['IT Manager', 'Software Developer', 'Web Developer', 'IT Support'],
            'Finance': ['Accounting Supervisor', 'Accountant', 'Accounting Assistant'],
            'Marketing': ['Marketing Manager', 'Sales Representative'],
            'Administration': ['Administrative Officer', 'Office Assistant'],
            'Management': ['Company Manager', 'Operations Manager', 'Project Manager'],
        }
        self.assertEqual(
            {department: [value for value, _label in choices]
             for department, choices in DEPARTMENT_POSITION_MAP.items()},
            expected_positions,
        )
        form = EmployeeForm(data={
            'username': 'newmarketing', 'first_name': 'New', 'last_name': 'Marketing',
            'email': 'newmarketing@example.com', 'password': 'TestingPass123!',
            'employee_id': 'MKT-024', 'department': 'Marketing',
            'position': 'Sales Representative', 'role': 'employee',
            'phone_number': '', 'hire_date': '', 'manager': str(self.marketing_supervisor_user.pk), 'backup_manager': '',
        }, allowed_roles=['employee', 'supervisor'])
        self.assertTrue(form.is_valid(), form.errors)
        profile = form.save(commit=False)
        self.assertEqual(profile.department, 'Marketing')
        self.assertEqual(profile.position, 'Sales Representative')
        self.assertEqual(profile.role, 'employee')

    def test_supervisor_titles_are_reserved_for_supervisor_access(self):
        from .forms import SUPERVISOR_POSITIONS, EMPLOYEE_POSITIONS
        self.assertEqual(SUPERVISOR_POSITIONS, {
            'HR Manager', 'IT Manager', 'Marketing Manager', 'Administrative Officer',
            'Company Manager', 'Operations Manager', 'Project Manager', 'Accounting Supervisor',
        })
        self.assertNotIn('Marketing Manager', EMPLOYEE_POSITIONS)
        self.assertIn('Sales Representative', EMPLOYEE_POSITIONS)
        supervisor_form = EmployeeForm(data={
            'first_name': 'New', 'last_name': 'Manager', 'email': 'manager@example.com',
            'employee_id': 'MKT-SUP-02', 'department': 'Marketing',
            'position': 'Marketing Manager', 'role': 'supervisor', 'phone_number': '',
            'hire_date': '', 'manager': '', 'backup_manager': '',
        }, allowed_roles=['employee', 'supervisor'])
        self.assertTrue(supervisor_form.is_valid(), supervisor_form.errors)
        employee_with_supervisor_title = EmployeeForm(data={
            'first_name': 'Wrong', 'last_name': 'Role', 'email': 'wrongrole@example.com',
            'employee_id': 'MKT-026', 'department': 'Marketing',
            'position': 'Marketing Manager', 'role': 'employee', 'phone_number': '',
            'hire_date': '', 'manager': str(self.marketing_supervisor_user.pk), 'backup_manager': '',
        }, allowed_roles=['employee', 'supervisor'])
        self.assertFalse(employee_with_supervisor_title.is_valid())
        self.assertIn('position', employee_with_supervisor_title.errors)

    def test_future_hire_date_is_rejected(self):
        form = EmployeeForm(data={
            'first_name': 'Future', 'last_name': 'Hire', 'email': 'future.hire@example.com',
            'employee_id': 'MKT-FUTURE', 'department': 'Marketing',
            'position': 'Sales Representative', 'role': 'employee', 'phone_number': '',
            'hire_date': (timezone.localdate() + timedelta(days=1)).isoformat(),
            'manager': str(self.marketing_supervisor_user.pk), 'backup_manager': '',
        }, allowed_roles=['employee', 'supervisor'])
        self.assertFalse(form.is_valid())
        self.assertIn('hire_date', form.errors)

    def test_employee_supervisor_choices_are_limited_to_the_selected_department(self):
        finance_supervisor_user = User.objects.create_user('finance_supervisor', password='TestingPass123!')
        EmployeeProfile.objects.create(
            user=finance_supervisor_user, employee_id='FIN-SUP-01', role='supervisor',
            department='Finance', position='Accounting Supervisor'
        )
        form = EmployeeForm(data={
            'first_name': 'New', 'last_name': 'Marketing', 'email': 'new.marketing@example.com',
            'employee_id': 'MKT-027', 'department': 'Marketing',
            'position': 'Sales Representative', 'role': 'employee', 'phone_number': '',
            'hire_date': '', 'manager': str(finance_supervisor_user.pk), 'backup_manager': '',
        }, allowed_roles=['employee', 'supervisor'])
        self.assertFalse(form.is_valid())
        self.assertIn('manager', form.errors)
        self.assertNotIn(finance_supervisor_user, form.fields['manager'].queryset)

    def test_department_usage_guidance_matches_company_reference(self):
        expected = {
            'HR': 'Manages employee accounts, attendance records, and leave applications.',
            'IT': 'Maintains the WorkTrack system and handles technical issues.',
            'Finance': 'Views attendance summaries for payroll preparation.',
            'Marketing': 'Monitors employee attendance and leave.',
            'Administration': 'Monitors office personnel and daily attendance.',
            'Management': 'Views company-wide attendance and employee reports.',
        }
        from .forms import DEPARTMENT_SYSTEM_USAGE
        self.assertEqual(DEPARTMENT_SYSTEM_USAGE, expected)
        form = EmployeeForm(allowed_roles=['employee', 'supervisor'])
        self.assertEqual(form.fields['department'].initial, '')
        self.assertEqual(form.fields['position'].initial, '')

    def test_job_position_must_belong_to_selected_department(self):
        form = EmployeeForm(data={
            'username': 'wrongdepartment', 'first_name': 'Wrong', 'last_name': 'Department',
            'email': 'wrong@example.com', 'password': 'TestingPass123!',
            'employee_id': 'MKT-025', 'department': 'Marketing',
            'position': 'Accountant', 'role': 'employee',
            'phone_number': '', 'hire_date': '', 'manager': '', 'backup_manager': '',
        }, allowed_roles=['employee', 'supervisor'])
        self.assertFalse(form.is_valid())
        self.assertIn('position', form.errors)

    def test_company_attendance_search_matches_username_name_and_employee_id(self):
        AttendanceRecord.objects.create(
            employee=self.employee, attendance_date=timezone.localdate(), status='present'
        )
        self.client.force_login(self.admin_user)
        for query in ('maya.santos', 'Maya Santos', 'MKT-023'):
            with self.subTest(query=query):
                response = self.client.get(reverse('eqrApp:attendance_list'), {'q': query})
                self.assertEqual(response.status_code, 200)
                ids = [row['employee'].employee_id for row in response.context['attendance_rows']]
                self.assertIn('MKT-023', ids)

    def test_hr_cannot_decide_employee_leave_until_supervisor_acknowledges(self):
        leave_type, _ = LeaveType.objects.get_or_create(
            code='VL', defaults={'name': 'Vacation Leave', 'is_active': True, 'track_balance': True}
        )
        application = LeaveApplication.objects.create(
            employee=self.employee, leave_type=leave_type,
            start_date=timezone.localdate() + timedelta(days=3),
            end_date=timezone.localdate() + timedelta(days=3),
            reason='Supervisor acknowledgment required', status='pending_manager',
        )
        self.client.force_login(self.hr_user)
        self.client.raise_request_exception = False
        self.assertEqual(self.client.post(reverse('eqrApp:review_leave', args=[application.pk]), {'decision': 'approve'}).status_code, 403)
        self.assertEqual(self.client.post(reverse('eqrApp:review_leave', args=[application.pk]), {'decision': 'reject'}).status_code, 403)
        application.refresh_from_db()
        self.assertEqual(application.status, 'pending_manager')

        self.client.force_login(self.marketing_supervisor_user)
        self.assertEqual(self.client.post(reverse('eqrApp:review_leave', args=[application.pk]), {'decision': 'approve'}).status_code, 403)
        acknowledged = self.client.post(reverse('eqrApp:review_leave', args=[application.pk]), {'decision': 'acknowledge'})
        self.assertEqual(acknowledged.status_code, 302)
        application.refresh_from_db()
        self.assertEqual(application.status, 'pending_hr')
        self.assertEqual(application.manager_reviewed_by, self.marketing_supervisor_user)
        self.assertIsNone(application.reviewed_by)

        self.client.force_login(self.hr_user)
        approved = self.client.post(reverse('eqrApp:review_leave', args=[application.pk]), {'decision': 'approve'})
        self.assertEqual(approved.status_code, 302)
        application.refresh_from_db()
        self.assertEqual(application.status, 'approved')
        self.assertEqual(application.reviewed_by, self.hr_user)

    def test_legacy_employee_request_waits_for_supervisor_ack_even_if_status_is_pending_hr(self):
        leave_type, _ = LeaveType.objects.get_or_create(
            code='VL', defaults={'name': 'Vacation Leave', 'is_active': True, 'track_balance': True}
        )
        legacy_employee_user = User.objects.create_user(
            'legacy_employee', password='TestingPass123!', first_name='Legacy', last_name='Employee'
        )
        legacy_employee = EmployeeProfile.objects.create(
            user=legacy_employee_user, employee_id='MKT-LEGACY', role='employee',
            department='Marketing', position='Sales Representative'
        )
        application = LeaveApplication.objects.create(
            employee=legacy_employee, leave_type=leave_type,
            start_date=timezone.localdate() + timedelta(days=5),
            end_date=timezone.localdate() + timedelta(days=5),
            reason='Legacy request awaiting acknowledgment', status='pending_hr'
        )

        self.client.force_login(self.hr_user)
        self.client.raise_request_exception = False
        response = self.client.post(
            reverse('eqrApp:review_leave', args=[application.pk]), {'decision': 'approve'}
        )
        self.assertEqual(response.status_code, 403)
        application.refresh_from_db()
        self.assertEqual(application.status, 'pending_hr')
        self.assertIsNone(application.manager_reviewed_at)

        legacy_employee.manager = self.marketing_supervisor_user
        legacy_employee.save(update_fields=['manager'])
        self.client.force_login(self.marketing_supervisor_user)
        queue_response = self.client.get(reverse('eqrApp:leave_list'))
        self.assertEqual(queue_response.status_code, 200)
        self.assertIn(application, queue_response.context['pending_applications'])
        self.assertContains(queue_response, reverse('eqrApp:leave_detail', args=[application.pk]))
        history_ids = [item.pk for item in queue_response.context['applications']]
        self.assertNotIn(application.pk, history_ids)

        acknowledged = self.client.post(
            reverse('eqrApp:review_leave', args=[application.pk]), {'decision': 'acknowledge'}
        )
        self.assertEqual(acknowledged.status_code, 302)
        application.refresh_from_db()
        self.assertIsNotNone(application.manager_reviewed_at)
        self.assertEqual(application.status, 'pending_hr')

        self.client.force_login(self.hr_user)
        approved = self.client.post(
            reverse('eqrApp:review_leave', args=[application.pk]), {'decision': 'approve'}
        )
        self.assertEqual(approved.status_code, 302)
        application.refresh_from_db()
        self.assertEqual(application.status, 'approved')

    def test_hr_pending_queue_and_history_use_independent_filter_parameters(self):
        leave_type, _ = LeaveType.objects.get_or_create(
            code='VL', defaults={'name': 'Vacation Leave', 'is_active': True, 'track_balance': True}
        )
        pending_application = LeaveApplication.objects.create(
            employee=self.employee, leave_type=leave_type,
            start_date=timezone.localdate() + timedelta(days=4),
            end_date=timezone.localdate() + timedelta(days=4),
            reason='Pending acknowledgment', status='pending_manager',
        )
        completed_application = LeaveApplication.objects.create(
            employee=self.employee, leave_type=leave_type,
            start_date=timezone.localdate() + timedelta(days=8),
            end_date=timezone.localdate() + timedelta(days=8),
            reason='Completed', status='approved',
        )
        self.client.force_login(self.hr_user)
        response = self.client.get(reverse('eqrApp:leave_list'), {
            'pending_q': self.employee.employee_id,
            'pending_status': 'pending_manager',
            'history_q': 'Maya Santos',
            'history_status': 'approved',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item.pk for item in response.context['pending_applications']], [pending_application.pk])
        self.assertEqual([item.pk for item in response.context['applications']], [completed_application.pk])
        self.assertEqual(response.context['pending_search'], self.employee.employee_id)
        self.assertEqual(response.context['history_search'], 'Maya Santos')

    def test_admin_system_logs_show_only_sanitized_warning_and_error_events(self):
        success_event = SystemEventLog.objects.create(
            event_type='employee_profile_updated', severity='info', status_code=200,
            message='Successful update for Maya Santos', actor=self.hr_user,
        )
        warning_event = SystemEventLog.objects.create(
            event_type='security_event', severity='warning', status_code=403,
            message='Employee MKT-023 attempted a blocked action', actor=self.employee_user,
        )
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('eqrApp:system_logs'), {'severity': 'warning'})
        self.assertEqual(response.status_code, 200)
        rendered_ids = [event.pk for event in response.context['events']]
        self.assertIn(warning_event.pk, rendered_ids)
        self.assertNotIn(success_event.pk, rendered_ids)
        self.assertNotContains(response, 'Maya Santos')
        self.assertNotContains(response, 'MKT-023')
        self.assertNotContains(response, self.employee_user.username)

    def test_admin_account_support_only_changes_name_username_and_password(self):
        self.client.force_login(self.admin_user)
        edit_url = reverse('eqrApp:employee_account_support_edit', args=[self.employee.pk])
        response = self.client.post(edit_url, {
            'first_name': 'Maya', 'last_name': 'Revised', 'username': 'maya.revised',
            'new_password': 'NewSupportPass123!',
        })
        self.assertEqual(response.status_code, 302)
        self.employee_user.refresh_from_db()
        self.employee.refresh_from_db()
        self.assertEqual(self.employee_user.first_name, 'Maya')
        self.assertEqual(self.employee_user.last_name, 'Revised')
        self.assertEqual(self.employee_user.username, 'maya.revised')
        self.assertTrue(self.employee_user.check_password('NewSupportPass123!'))
        self.assertEqual(self.employee.department, 'Marketing')
        self.assertEqual(self.employee.position, 'Sales Representative')
        self.assertEqual(self.employee.role, 'employee')

    def test_qr_status_endpoint_reports_check_in_and_checkout_for_current_user_only(self):
        self.client.force_login(self.employee_user)
        status_url = reverse('eqrApp:attendance_qr_status')
        response = self.client.get(status_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['state'], 'not_scanned')
        now = timezone.now()
        record = AttendanceRecord.objects.create(
            employee=self.employee, attendance_date=timezone.localdate(),
            check_in=now, status='present'
        )
        response = self.client.get(status_url)
        self.assertEqual(response.json()['state'], 'checked_in')
        record.check_out = now + timedelta(minutes=10)
        record.save()
        response = self.client.get(status_url)
        self.assertEqual(response.json()['state'], 'complete')
        self.assertEqual(response['Cache-Control'], 'no-store, private')


    def test_password_visibility_script_is_loaded_on_signin_and_account_forms(self):
        login_response = self.client.get(reverse('eqrApp:login'))
        self.assertContains(login_response, 'js/password-toggle.js')
        self.client.force_login(self.hr_user)
        employee_form_response = self.client.get(reverse('eqrApp:employee_create'))
        self.assertContains(employee_form_response, 'js/password-toggle.js')
        self.assertNotContains(employee_form_response, 'id="id_password"')


    def test_employee_leave_history_includes_pending_requests_and_shared_filters(self):
        leave_type = LeaveType.objects.get(code='VL')
        application = LeaveApplication.objects.create(
            employee=self.employee, leave_type=leave_type,
            start_date=date(2026, 12, 7), end_date=date(2026, 12, 7),
            reason='Pending demo request', status='pending_manager',
        )
        self.client.force_login(self.employee_user)
        response = self.client.get(reverse('eqrApp:leave_list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(application.pk, [item.pk for item in response.context['applications']])
        self.assertContains(response, 'All request statuses')
        self.assertContains(response, 'pending_manager')

    def test_fixed_leave_entitlements_initialize_and_track_used_days(self):
        expected = {
            'SIL': Decimal('5.00'),
            'MAT': Decimal('105.00'),
            'PAT': Decimal('7.00'),
            'VL': Decimal('10.00'),
            'SL': Decimal('10.00'),
            'EL': Decimal('3.00'),
            'BL': Decimal('3.00'),
        }
        from .views import ensure_employee_leave_balances, deduct_leave_balance
        for code, entitlement in expected.items():
            leave_type = LeaveType.objects.get(code=code)
            self.assertEqual(leave_type.default_entitled_days, entitlement)
            ensure_employee_leave_balances(self.employee, 2026)
            balance = LeaveBalance.objects.get(
                employee=self.employee, leave_type=leave_type, year=2026
            )
            self.assertEqual(balance.entitled_days, entitlement)
        vacation = LeaveType.objects.get(code='VL')
        application = LeaveApplication(
            employee=self.employee, leave_type=vacation,
            start_date=date(2026, 12, 7), end_date=date(2026, 12, 7),
            reason='Approved leave balance test', status='approved',
        )
        deduct_leave_balance(application)
        balance = LeaveBalance.objects.get(employee=self.employee, leave_type=vacation, year=2026)
        self.assertEqual(balance.used_days, Decimal('1.00'))
        self.assertEqual(balance.available_days, Decimal('9.00'))

    def test_kiosk_session_locks_navigation_until_admin_reauthenticates_to_exit(self):
        activate_url = reverse('eqrApp:attendance_kiosk')
        run_url = reverse('eqrApp:attendance_kiosk_run')
        exit_url = reverse('eqrApp:attendance_kiosk_exit')
        self.client.force_login(self.hr_user)
        self.assertEqual(self.client.get(activate_url).status_code, 403)
        self.assertEqual(self.client.post(exit_url, {'password': 'TestingPass123!'}).status_code, 403)

        self.client.force_login(self.employee_user)
        self.assertEqual(self.client.get(activate_url).status_code, 403)
        self.assertEqual(self.client.post(exit_url, {'password': 'TestingPass123!'}).status_code, 403)

        self.client.force_login(self.admin_user)
        wrong_activation = self.client.post(activate_url, {'username': self.admin_user.username, 'password': 'wrong-password'})
        self.assertEqual(wrong_activation.status_code, 200)
        self.assertFalse(self.client.session.get('worktrack_kiosk_active', False))

        activated = self.client.post(activate_url, {'username': self.admin_user.username, 'password': 'TestingPass123!'})
        self.assertRedirects(activated, run_url, fetch_redirect_response=False)
        self.assertTrue(self.client.session.get('worktrack_kiosk_active'))

        # Dashboard and logout requests are returned to the scanner while kiosk mode is active.
        blocked_dashboard = self.client.get(reverse('eqrApp:admin_dashboard'))
        self.assertRedirects(blocked_dashboard, run_url, fetch_redirect_response=False)
        blocked_logout = self.client.post(reverse('eqrApp:logout'))
        self.assertRedirects(blocked_logout, run_url, fetch_redirect_response=False)
        self.assertTrue(self.client.session.get('_auth_user_id'))

        # An incorrect exit password leaves the kiosk locked.
        failed_exit = self.client.post(exit_url, {'password': 'wrong-password'})
        self.assertRedirects(failed_exit, run_url, fetch_redirect_response=False)
        self.assertTrue(self.client.session.get('worktrack_kiosk_active'))

        # The original Administrator can exit only after confirming their password again.
        successful_exit = self.client.post(exit_url, {'password': 'TestingPass123!'})
        self.assertRedirects(successful_exit, reverse('eqrApp:admin_dashboard'), fetch_redirect_response=False)
        self.assertFalse(self.client.session.get('worktrack_kiosk_active', False))
        self.assertEqual(self.client.get(reverse('eqrApp:admin_dashboard')).status_code, 200)
        self.assertTrue(SystemEventLog.objects.filter(event_type='kiosk_activated', actor=self.admin_user).exists())
        self.assertTrue(SystemEventLog.objects.filter(event_type='kiosk_exited', actor=self.admin_user).exists())

    def test_kiosk_exit_is_locked_after_five_failed_password_confirmations(self):
        self.client.force_login(self.admin_user)
        activate_url = reverse('eqrApp:attendance_kiosk')
        run_url = reverse('eqrApp:attendance_kiosk_run')
        exit_url = reverse('eqrApp:attendance_kiosk_exit')
        self.client.post(activate_url, {'username': self.admin_user.username, 'password': 'TestingPass123!'})

        for _ in range(5):
            response = self.client.post(exit_url, {'password': 'incorrect-password'})
            self.assertRedirects(response, run_url, fetch_redirect_response=False)

        self.assertGreater(self.client.session.get('worktrack_kiosk_exit_locked_until', 0), 0)
        # Even the correct password is rejected while the five-minute lock is active.
        blocked_exit = self.client.post(exit_url, {'password': 'TestingPass123!'})
        self.assertRedirects(blocked_exit, run_url, fetch_redirect_response=False)
        self.assertTrue(self.client.session.get('worktrack_kiosk_active'))

    def test_kiosk_scanning_requires_activated_admin_kiosk_session(self):
        self.client.force_login(self.admin_user)
        scan_url = reverse('eqrApp:attendance_kiosk_scan')
        response = self.client.post(scan_url, {'token': 'not-a-token'})
        self.assertEqual(response.status_code, 403)
        self.assertIn('Activate the kiosk', response.json()['message'])

    def test_kiosk_manual_entry_requires_unlocked_settings_and_preserves_attendance_history(self):
        self.client.force_login(self.admin_user)
        activate_url = reverse('eqrApp:attendance_kiosk')
        self.client.post(activate_url, {'username': self.admin_user.username, 'password': 'TestingPass123!'})

        run_url = reverse('eqrApp:attendance_kiosk_run')
        kiosk_page = self.client.get(run_url)
        self.assertEqual(kiosk_page.status_code, 200)
        self.assertContains(kiosk_page, 'kiosk-camera-select')
        self.assertContains(kiosk_page, 'kiosk-manual-form')
        self.assertNotContains(kiosk_page, 'kiosk-edit-form')

        unlock_url = reverse('eqrApp:attendance_kiosk_settings_unlock')
        unlocked = self.client.post(unlock_url, {'password': 'TestingPass123!'})
        self.assertEqual(unlocked.status_code, 200)
        self.assertTrue(unlocked.json()['ok'])

        manual_url = reverse('eqrApp:attendance_kiosk_manual')
        edit_url = reverse('eqrApp:attendance_kiosk_edit')
        before_count = AttendanceRecord.objects.count()
        before_audits = AttendanceAudit.objects.count()

        def submit(action):
            return self.client.post(manual_url, {'employee_id': self.employee.employee_id, 'action': action})

        self.assertEqual(submit('check_out').status_code, 409)
        self.assertEqual(submit('check_in').status_code, 200)
        self.assertEqual(submit('check_in').status_code, 409)
        record = AttendanceRecord.objects.get(employee=self.employee, attendance_date=timezone.localdate())
        self.assertEqual(record.recorded_by, self.admin_user)
        self.assertEqual(record.source, 'admin')
        with patch('eqrApp.views.timezone.now', return_value=record.check_in + timedelta(seconds=15)):
            self.assertEqual(submit('check_out').status_code, 200)
            self.assertEqual(submit('check_out').status_code, 409)
        self.assertEqual(self.client.post(manual_url, {'employee_id': self.hr_user.employee_profile.employee_id, 'action': 'check_in'}).status_code, 404)

        corrected = self.client.post(edit_url, {
            'employee_id': self.employee.employee_id,
            'attendance_date': timezone.localdate().isoformat(),
            'check_in': '',
            'check_out': '',
            'status': 'present',
            'remarks': 'Attempted attendance correction.',
        })
        self.assertEqual(corrected.status_code, 403)
        self.assertIn('not permitted', corrected.json()['message'].lower())
        self.assertEqual(AttendanceRecord.objects.count(), before_count + 1)
        self.assertEqual(AttendanceAudit.objects.count(), before_audits + 2)

        locked = self.client.post(reverse('eqrApp:attendance_kiosk_settings_lock'))
        self.assertEqual(locked.status_code, 200)
        self.assertEqual(self.client.post(manual_url, {'employee_id': self.employee.employee_id, 'action': 'check_out'}).status_code, 403)

        self.client.force_login(self.employee_user)
        self.assertEqual(self.client.post(unlock_url, {'password': 'TestingPass123!'}).status_code, 403)


@override_settings(DEBUG=True)
class DemoDataSeederTests(TestCase):
    def test_demo_seed_command_creates_repeatable_fictional_records(self):
        call_command('seed_worktrack_demo', password='DemoPass123!', verbosity=0)
        call_command('seed_worktrack_demo', password='DemoPass123!', verbosity=0)

        self.assertEqual(User.objects.filter(username__startswith='demo.').count(), 5)
        self.assertEqual(EmployeeProfile.objects.filter(employee_id__startswith='DEMO-').count(), 5)
        self.assertEqual(Holiday.objects.filter(name__startswith='Demo ').count(), 2)
        self.assertEqual(LeaveApplication.objects.filter(reason__startswith='Fictional demo').count(), 2)
        self.assertEqual(AttendanceRecord.objects.filter(remarks__contains='seed_worktrack_demo').count(), 3)
        eligible_ids = DailyAttendanceQR.objects.filter(employee__employee_id__startswith='DEMO-').values_list(
            'employee__employee_id', flat=True
        )
        self.assertCountEqual(eligible_ids, ['DEMO-SUP', 'DEMO-EMP-001', 'DEMO-EMP-002'])

        # Seeded fictional accounts follow the fixed marketing-company structure.
        self.assertEqual(EmployeeProfile.objects.get(employee_id='DEMO-HR').department, 'HR')
        self.assertEqual(EmployeeProfile.objects.get(employee_id='DEMO-SUP').position, 'Marketing Manager')
        self.assertEqual(EmployeeProfile.objects.get(employee_id='DEMO-EMP-001').position, 'Sales Representative')
        self.assertEqual(EmployeeProfile.objects.get(employee_id='DEMO-EMP-002').department, 'Marketing')

        demo_admin = User.objects.get(username='demo.admin')
        self.assertTrue(demo_admin.is_superuser)
        self.assertTrue(demo_admin.check_password('DemoPass123!'))
