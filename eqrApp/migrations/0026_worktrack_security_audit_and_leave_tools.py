import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone
import eqrApp.models


class Migration(migrations.Migration):
    dependencies = [
        ('eqrApp', '0025_remove_legacy_snaptrack_models'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='employeeprofile', name='must_change_password',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='employeeprofile', name='backup_manager',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='backup_direct_reports', to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='leavetype', name='track_balance',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='leavedocument', name='file',
            field=models.FileField(upload_to=eqrApp.models.leave_document_upload_path),
        ),
        migrations.AddField(
            model_name='leaveapplication', name='is_half_day',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='attendancerecord', name='source',
            field=models.CharField(
                choices=[
                    ('self_service', 'Employee Check-in'),
                    ('hr', 'HR Entry / Correction'),
                    ('leave_sync', 'Approved Leave'),
                    ('scheduled', 'Scheduled Absence Process'),
                ], default='self_service', max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='leaveaction', name='action',
            field=models.CharField(
                choices=[
                    ('submitted', 'Submitted'),
                    ('manager_approved', 'Supervisor Approved'),
                    ('approved', 'Approved by HR'),
                    ('rejected', 'Rejected'),
                    ('cancelled', 'Cancelled'),
                    ('deleted', 'Deleted'),
                ], max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name='leaveapplication',
            constraint=models.CheckConstraint(
                condition=models.Q(('end_date__gte', models.F('start_date'))),
                name='leave_end_on_or_after_start',
            ),
        ),
        migrations.CreateModel(
            name='Holiday',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(unique=True)),
                ('name', models.CharField(max_length=120)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['date']},
        ),
        migrations.CreateModel(
            name='LeaveBalance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year', models.PositiveSmallIntegerField()),
                ('entitled_days', models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ('used_days', models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='leave_balances', to='eqrApp.employeeprofile')),
                ('leave_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='balances', to='eqrApp.leavetype')),
            ],
            options={'ordering': ['-year', 'leave_type__name']},
        ),
        migrations.AddConstraint(
            model_name='leavebalance',
            constraint=models.UniqueConstraint(fields=('employee', 'leave_type', 'year'), name='unique_leave_balance_employee_type_year'),
        ),
        migrations.AddConstraint(
            model_name='leavebalance',
            constraint=models.CheckConstraint(condition=models.Q(('entitled_days__gte', 0)), name='leave_balance_entitled_nonnegative'),
        ),
        migrations.AddConstraint(
            model_name='leavebalance',
            constraint=models.CheckConstraint(condition=models.Q(('used_days__gte', 0)), name='leave_balance_used_nonnegative'),
        ),
        migrations.CreateModel(
            name='AttendanceAudit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('created', 'Created'), ('updated', 'Updated'), ('deleted', 'Deleted')], max_length=10)),
                ('old_values', models.JSONField(blank=True, default=dict)),
                ('new_values', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('attendance', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audit_entries', to='eqrApp.attendancerecord')),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='attendance_audits', to='eqrApp.employeeprofile')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
