import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def create_default_leave_types(apps, schema_editor):
    LeaveType = apps.get_model('eqrApp', 'LeaveType')
    defaults = [
        ('Vacation Leave', 'VL', 'Planned personal time off.', True, False),
        ('Sick Leave', 'SL', 'Leave for illness or medical needs.', True, False),
        ('Emergency Leave', 'EL', 'Urgent personal or family matters.', True, False),
        ('Unpaid Leave', 'UL', 'Unpaid time away from work.', False, False),
    ]
    for name, code, description, is_paid, requires_document in defaults:
        LeaveType.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'description': description,
                'is_paid': is_paid,
                'requires_document': requires_document,
                'is_active': True,
            },
        )


def remove_default_leave_types(apps, schema_editor):
    LeaveType = apps.get_model('eqrApp', 'LeaveType')
    LeaveType.objects.filter(code__in=['VL', 'SL', 'EL', 'UL']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('eqrApp', '0022_alter_member_temp_password'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployeeProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('employee_id', models.CharField(max_length=30, unique=True)),
                ('department', models.CharField(max_length=100)),
                ('position', models.CharField(max_length=100)),
                ('phone_number', models.CharField(blank=True, max_length=30)),
                ('hire_date', models.DateField(blank=True, null=True)),
                ('employment_status', models.CharField(choices=[('active', 'Active'), ('inactive', 'Inactive'), ('terminated', 'Terminated')], default='active', max_length=15)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('manager', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='direct_reports', to=settings.AUTH_USER_MODEL)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='employee_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['employee_id']},
        ),
        migrations.CreateModel(
            name='LeaveType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, unique=True)),
                ('code', models.CharField(max_length=20, unique=True)),
                ('description', models.TextField(blank=True)),
                ('requires_document', models.BooleanField(default=False)),
                ('is_paid', models.BooleanField(default=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='AttendanceRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('attendance_date', models.DateField(default=django.utils.timezone.localdate)),
                ('check_in', models.DateTimeField(blank=True, null=True)),
                ('check_out', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('present', 'Present'), ('late', 'Late'), ('half_day', 'Half Day'), ('absent', 'Absent'), ('on_leave', 'On Leave')], default='present', max_length=12)),
                ('source', models.CharField(choices=[('self_service', 'Employee Check-in'), ('hr', 'HR Entry / Correction')], default='self_service', max_length=20)),
                ('remarks', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attendance_records', to='eqrApp.employeeprofile')),
                ('recorded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='recorded_attendance_entries', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-attendance_date', '-check_in']},
        ),
        migrations.CreateModel(
            name='LeaveApplication',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('reason', models.TextField()),
                ('status', models.CharField(choices=[('pending_manager', 'Pending Supervisor Approval'), ('pending_hr', 'Pending HR Approval'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('cancelled', 'Cancelled')], default='pending_hr', max_length=20)),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('manager_reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('manager_comments', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('reviewer_comments', models.TextField(blank=True)),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='leave_applications', to='eqrApp.employeeprofile')),
                ('leave_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='applications', to='eqrApp.leavetype')),
                ('manager_reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='manager_reviewed_leave_applications', to=settings.AUTH_USER_MODEL)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='hr_reviewed_leave_applications', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-submitted_at']},
        ),
        migrations.CreateModel(
            name='LeaveDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='private_leave_documents/%Y/%m/')),
                ('original_name', models.CharField(max_length=255)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('application', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documents', to='eqrApp.leaveapplication')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['uploaded_at']},
        ),
        migrations.CreateModel(
            name='LeaveAction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('submitted', 'Submitted'), ('manager_approved', 'Supervisor Approved'), ('approved', 'Approved by HR'), ('rejected', 'Rejected'), ('cancelled', 'Cancelled')], max_length=20)),
                ('comments', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('application', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='actions', to='eqrApp.leaveapplication')),
            ],
            options={'ordering': ['created_at']},
        ),
        migrations.AddConstraint(
            model_name='attendancerecord',
            constraint=models.UniqueConstraint(fields=('employee', 'attendance_date'), name='unique_employee_attendance_per_day'),
        ),
        migrations.RunPython(create_default_leave_types, remove_default_leave_types),
    ]
