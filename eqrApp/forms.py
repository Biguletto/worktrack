from datetime import datetime

from django import forms
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from .models import EmployeeProfile, AttendanceRecord, LeaveApplication, LeaveType, LeaveBalance, Holiday


DEPARTMENT_POSITION_MAP = {
    'HR': [
        ('HR Manager', 'HR Manager'),
        ('HR Assistant', 'HR Assistant'),
        ('Recruitment Officer', 'Recruitment Officer'),
    ],
    'IT': [
        ('IT Manager', 'IT Manager'),
        ('Software Developer', 'Software Developer (3)'),
        ('Web Developer', 'Web Developer'),
        ('IT Support', 'IT Support'),
    ],
    'Finance': [
        ('Accounting Supervisor', 'Accounting Supervisor'),
        ('Accountant', 'Accountant'),
        ('Accounting Assistant', 'Accounting Assistant'),
    ],
    'Marketing': [
        ('Marketing Manager', 'Marketing Manager'),
        ('Sales Representative', 'Sales Representative (2)'),
    ],
    'Administration': [
        ('Administrative Officer', 'Administrative Officer'),
        ('Office Assistant', 'Office Assistant (2)'),
    ],
    'Management': [
        ('Company Manager', 'Company Manager'),
        ('Operations Manager', 'Operations Manager'),
        ('Project Manager', 'Project Manager'),
    ],
}

DEPARTMENT_CHOICES = [(name, name) for name in DEPARTMENT_POSITION_MAP]

SUPERVISOR_POSITIONS = {
    'HR Manager', 'IT Manager', 'Marketing Manager', 'Administrative Officer',
    'Company Manager', 'Operations Manager', 'Project Manager', 'Accounting Supervisor',
}

EMPLOYEE_POSITIONS = {
    value for choices in DEPARTMENT_POSITION_MAP.values() for value, _label in choices
} - SUPERVISOR_POSITIONS

DEPARTMENT_SYSTEM_USAGE = {
    'HR': 'Manages employee accounts, attendance records, and leave applications.',
    'IT': 'Maintains the WorkTrack system and handles technical issues.',
    'Finance': 'Views attendance summaries for payroll preparation.',
    'Marketing': 'Monitors employee attendance and leave.',
    'Administration': 'Monitors office personnel and daily attendance.',
    'Management': 'Views company-wide attendance and employee reports.',
}


class EmployeeForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, label='First name')
    last_name = forms.CharField(max_length=150, label='Last name')
    email = forms.EmailField(label='Email address')
    department = forms.ChoiceField(
        label='Department',
        choices=[('', 'Select department')] + DEPARTMENT_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_department'}),
    )
    position = forms.ChoiceField(
        label='Job position',
        choices=[('', 'Select a department first')],
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_position'}),
    )
    role = forms.ChoiceField(
        label='WorkTrack access role',
        choices=EmployeeProfile.ROLE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Controls dashboard permissions. A job title such as Manager does not automatically grant Supervisor or Administrator access. HR and Administrator accounts are provisioned separately.',
    )

    class Meta:
        model = EmployeeProfile
        fields = [
            'employee_id', 'department', 'position', 'role', 'phone_number',
            'hire_date', 'manager', 'backup_manager', 'employment_status',
        ]
        widgets = {
            'employee_id': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 09XXXXXXXXX'}),
            'hire_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control', 'max': timezone.localdate().isoformat()}),
            'manager': forms.Select(attrs={'class': 'form-select'}),
            'backup_manager': forms.Select(attrs={'class': 'form-select'}),
            'employment_status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        self.instance_user = kwargs.pop('instance_user', None)
        allowed_roles = kwargs.pop('allowed_roles', None)
        super().__init__(*args, **kwargs)

        role_choices = [
            choice for choice in EmployeeProfile.ROLE_CHOICES
            if allowed_roles is None or choice[0] in allowed_roles
        ]
        self.fields['role'].choices = role_choices
        selected_role = self.instance.role if self.instance.pk else (role_choices[0][0] if role_choices else '')
        if self.is_bound:
            selected_role = self.data.get(self.add_prefix('role'), selected_role)
        self.fields['role'].initial = selected_role
        self.fields['hire_date'].widget.attrs['max'] = timezone.localdate().isoformat()

        selected_department = self.instance.department if self.instance.pk else ''
        if self.is_bound:
            selected_department = self.data.get(self.add_prefix('department'), selected_department)
        department_choices = [('', 'Select department')] + DEPARTMENT_CHOICES
        # Keep legacy values visible when an existing record is being edited,
        # while all new records are limited to the six fixed company departments.
        if self.instance.pk and self.instance.department and self.instance.department not in DEPARTMENT_POSITION_MAP:
            department_choices.append((self.instance.department, f'{self.instance.department} (existing record)'))
        self.fields['department'].choices = department_choices
        self.fields['department'].initial = selected_department

        position_maps_by_role = {
            'employee': {department: [(value, label) for value, label in options if value in EMPLOYEE_POSITIONS]
                         for department, options in DEPARTMENT_POSITION_MAP.items()},
            'supervisor': {department: [(value, label) for value, label in options if value in SUPERVISOR_POSITIONS]
                           for department, options in DEPARTMENT_POSITION_MAP.items()},
        }
        # The access-role dropdown controls which job titles are valid. This is
        # deliberately separate from the title itself.
        selected_position_map = position_maps_by_role.get(selected_role, position_maps_by_role['employee'])
        position_choices = selected_position_map.get(selected_department, [])
        if self.instance.pk and selected_department == self.instance.department and self.instance.position:
            if self.instance.position not in {value for value, _label in position_choices}:
                # Legacy records remain editable without silently changing their title.
                position_choices = list(position_choices) + [(self.instance.position, f'{self.instance.position} (existing record)')]
        self.fields['position'].choices = [('', 'Select job position')] + list(position_choices)
        self.fields['position'].initial = self.instance.position if self.instance.pk else ''

        # JSON data for live Department + Access Role dependent dropdowns.
        self.position_map_by_role = position_maps_by_role
        self.position_map = selected_position_map
        self.department_usage_map = DEPARTMENT_SYSTEM_USAGE

        self.fields['department'].required = True
        self.fields['position'].required = True
        if not self.instance.pk:
            # New accounts are active by default; status is only editable later.
            self.fields.pop('employment_status', None)

        supervisor_users = User.objects.filter(
            is_active=True, employee_profile__role='supervisor',
            employee_profile__department=selected_department,
            employee_profile__employment_status='active',
        ).select_related('employee_profile').order_by('first_name', 'last_name', 'username')
        self.fields['manager'].queryset = supervisor_users
        self.fields['manager'].required = False
        self.fields['manager'].label = 'Supervisor'
        self.fields['backup_manager'].queryset = self.fields['manager'].queryset
        self.fields['backup_manager'].required = False
        self.fields['backup_manager'].label = 'Backup Supervisor'
        self.supervisor_map = {}
        supervisors_for_map = User.objects.filter(
            is_active=True, employee_profile__role='supervisor',
            employee_profile__employment_status='active',
        ).select_related('employee_profile').order_by('first_name', 'last_name', 'username')
        if self.instance_user:
            supervisors_for_map = supervisors_for_map.exclude(pk=self.instance_user.pk)
        for supervisor in supervisors_for_map:
            department = supervisor.employee_profile.department
            self.supervisor_map.setdefault(department, []).append({
                'id': supervisor.pk,
                'label': (supervisor.get_full_name() or supervisor.username) + f" ({supervisor.employee_profile.employee_id})",
            })

        if self.instance_user:
            self.fields['manager'].queryset = self.fields['manager'].queryset.exclude(pk=self.instance_user.pk)
            self.fields['backup_manager'].queryset = self.fields['backup_manager'].queryset.exclude(pk=self.instance_user.pk)
            self.fields['first_name'].initial = self.instance_user.first_name
            self.fields['last_name'].initial = self.instance_user.last_name
            self.fields['email'].initial = self.instance_user.email


    def clean_employee_id(self):
        value = self.cleaned_data['employee_id'].strip()
        duplicate = EmployeeProfile.objects.filter(employee_id__iexact=value)
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError('This employee ID is already in use.')
        return value

    def clean(self):
        cleaned_data = super().clean()
        selected_role = cleaned_data.get('role')
        department = cleaned_data.get('department')
        position = cleaned_data.get('position')
        manager = cleaned_data.get('manager')
        backup_manager = cleaned_data.get('backup_manager')

        role_position_set = SUPERVISOR_POSITIONS if selected_role == 'supervisor' else EMPLOYEE_POSITIONS
        allowed_positions = {value for value, _label in DEPARTMENT_POSITION_MAP.get(department, []) if value in role_position_set}
        # Existing records from departments that predate the fixed company list can
        # remain editable until HR migrates them. Within the six current departments,
        # however, a job title must always match the selected Employee/Supervisor role.
        legacy_department_unchanged = (
            self.instance.pk and department == self.instance.department
            and department not in DEPARTMENT_POSITION_MAP and position == self.instance.position
        )
        if department in DEPARTMENT_POSITION_MAP and position and position not in allowed_positions:
            self.add_error('position', 'The selected job position does not match the selected WorkTrack access role and department.')
        elif department not in DEPARTMENT_POSITION_MAP and not legacy_department_unchanged:
            self.add_error('department', 'Choose one of the six configured company departments.')

        hire_date = cleaned_data.get('hire_date')
        if hire_date and hire_date > timezone.localdate():
            self.add_error('hire_date', 'Hire date cannot be later than today.')

        if selected_role == 'employee' and not manager and not backup_manager:
            self.add_error('manager', 'Assign a supervisor from the same department before creating an employee account.')
        if manager and manager.employee_profile.department != department:
            self.add_error('manager', 'Choose a supervisor from the same department.')
        if backup_manager and backup_manager.employee_profile.department != department:
            self.add_error('backup_manager', 'Choose a backup supervisor from the same department.')
        if self.instance_user and manager and manager.pk == self.instance_user.pk:
            self.add_error('manager', 'An employee cannot be assigned as their own supervisor.')
        if self.instance_user and backup_manager and backup_manager.pk == self.instance_user.pk:
            self.add_error('backup_manager', 'An employee cannot be their own backup supervisor.')
        if self.instance.pk and selected_role and selected_role != 'supervisor':
            if self.instance.user.direct_reports.exists():
                self.add_error('role', 'Reassign this supervisor’s direct reports before changing their WorkTrack access role.')
        employment_status = cleaned_data.get('employment_status')
        if self.instance.pk and employment_status and employment_status != 'active':
            active_reports = EmployeeProfile.objects.filter(
                Q(manager=self.instance.user) | Q(backup_manager=self.instance.user),
                employment_status='active',
            ).exclude(pk=self.instance.pk)
            if active_reports.exists():
                self.add_error(
                    'employment_status',
                    'Reassign this supervisor’s active team members to another supervisor before '
                    'making the account inactive or terminated. Otherwise their leave requests cannot be acknowledged.',
                )
        return cleaned_data

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.role = self.cleaned_data['role']
        profile.department = self.cleaned_data['department']
        profile.position = self.cleaned_data['position']
        if commit:
            profile.save()
            self.save_m2m()
        return profile


class LeaveApplicationForm(forms.ModelForm):
    class Meta:
        model = LeaveApplication
        fields = ['leave_type', 'start_date', 'end_date', 'is_half_day', 'reason']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'reason': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Explain the reason for your leave request.'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['leave_type'].queryset = self.fields['leave_type'].queryset.filter(is_active=True, code__in=['SIL', 'MAT', 'PAT', 'VL', 'SL', 'EL', 'BL']).order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        if start_date and end_date:
            if end_date < start_date:
                self.add_error('end_date', 'The end date cannot be earlier than the start date.')
            if start_date < timezone.localdate():
                self.add_error('start_date', 'Leave requests must start today or on a future date.')
        return cleaned_data


class KioskCorrectionForm(forms.Form):
    check_in = forms.TimeField(required=False)
    check_out = forms.TimeField(required=False)
    status = forms.ChoiceField(choices=[
        choice for choice in AttendanceRecord.STATUS_CHOICES if choice[0] != 'on_leave'
    ])

    def __init__(self, data, record):
        super().__init__(data)
        self.record = record

    def clean(self):
        values = super().clean()
        now = timezone.now()
        for field in ('check_in', 'check_out'):
            if values.get(field) is None:
                continue
            entered = timezone.make_aware(datetime.combine(self.record.attendance_date, values[field]))
            original = getattr(self.record, field)
            # The kiosk displays seconds. Preserve the exact stored instant for unchanged punches.
            if original and original.replace(microsecond=0) == entered:
                entered = original
            if entered > now:
                raise forms.ValidationError('Attendance times cannot be in the future.')
            values[field] = entered
        start, end = values.get('check_in'), values.get('check_out')
        if end and not start:
            raise forms.ValidationError('Enter a check-in before recording a check-out.')
        if start and end and end < start:
            raise forms.ValidationError('Check-out cannot be earlier than check-in.')
        if values.get('status') == 'absent' and start:
            raise forms.ValidationError('Clear both times to mark this employee absent.')
        if values.get('status') in ('present', 'late') and not start:
            raise forms.ValidationError('A present or late record requires a check-in.')
        return values


class AttendanceRecordForm(forms.ModelForm):
    class Meta:
        model = AttendanceRecord
        fields = ['employee', 'attendance_date', 'check_in', 'check_out', 'status', 'remarks']
        widgets = {
            'attendance_date': forms.DateInput(attrs={'type': 'date'}),
            'check_in': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'check_out': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'remarks': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['employee'].queryset = EmployeeProfile.objects.filter(employment_status='active').select_related('user')
        self.fields['check_in'].input_formats = ['%Y-%m-%dT%H:%M']
        self.fields['check_out'].input_formats = ['%Y-%m-%dT%H:%M']

    def clean(self):
        cleaned_data = super().clean()
        check_in = cleaned_data.get('check_in')
        check_out = cleaned_data.get('check_out')
        if check_in and check_out and check_out < check_in:
            self.add_error('check_out', 'Check-out cannot be earlier than check-in.')
        return cleaned_data


class LeaveTypeForm(forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = ['name', 'code', 'description', 'requires_document', 'is_paid', 'track_balance', 'is_active']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def clean_code(self):
        return self.cleaned_data['code'].strip().upper()


class LeaveBalanceForm(forms.ModelForm):
    class Meta:
        model = LeaveBalance
        fields = ['employee', 'leave_type', 'year', 'entitled_days', 'used_days']
        widgets = {'year': forms.NumberInput(attrs={'min': '2000', 'max': '2200', 'step': '1'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['employee'].queryset = EmployeeProfile.objects.select_related('user').order_by('employee_id')
        eligible_types = LeaveType.objects.filter(track_balance=True)
        if self.instance.pk and self.instance.leave_type_id:
            eligible_types = LeaveType.objects.filter(Q(track_balance=True) | Q(pk=self.instance.leave_type_id))
        self.fields['leave_type'].queryset = eligible_types.order_by('name')

    def clean(self):
        cleaned = super().clean()
        entitled = cleaned.get('entitled_days')
        used = cleaned.get('used_days')
        if entitled is not None and used is not None and used > entitled:
            self.add_error('used_days', 'Used days cannot exceed the employee’s entitlement.')
        return cleaned


class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ['date', 'name', 'is_active']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields['date'].widget.attrs['min'] = today.isoformat()
        if not self.instance.pk and not self.initial.get('date'):
            self.initial['date'] = today

    def clean_date(self):
        selected_date = self.cleaned_data['date']
        if selected_date < timezone.localdate():
            raise forms.ValidationError('A holiday cannot be scheduled on a past date.')
        return selected_date


class AdminAccountSupportForm(forms.Form):
    """Restricted IT support form: may update username/name and optionally reset password only."""
    first_name = forms.CharField(max_length=150, label='First name')
    last_name = forms.CharField(max_length=150, label='Last name')
    username = forms.CharField(max_length=150, label='Username')
    new_password = forms.CharField(
        required=False, min_length=8, label='New temporary password',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text='Leave blank to keep the current password. If set, the account must change it at next sign-in.',
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        initial = kwargs.pop('initial', {})
        if user:
            initial = {'first_name': user.first_name, 'last_name': user.last_name, 'username': user.username, **initial}
        super().__init__(*args, initial=initial, **kwargs)

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        duplicate = User.objects.filter(username__iexact=username)
        if self.user:
            duplicate = duplicate.exclude(pk=self.user.pk)
        if duplicate.exists():
            raise forms.ValidationError('That username is already in use.')
        return username
