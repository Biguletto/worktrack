import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('eqrApp', '0029_employeeprofile_department_blank'),
    ]

    operations = [
        migrations.CreateModel(
            name='DailyAttendanceQR',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('qr_date', models.DateField()),
                ('nonce', models.UUIDField(default=uuid.uuid4, editable=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('employee', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='daily_attendance_qr_codes',
                    to='eqrApp.employeeprofile',
                )),
            ],
            options={
                'ordering': ['-qr_date', 'employee__employee_id'],
            },
        ),
        migrations.AddConstraint(
            model_name='dailyattendanceqr',
            constraint=models.UniqueConstraint(
                fields=('employee', 'qr_date'),
                name='unique_daily_attendance_qr_employee_date',
            ),
        ),
        migrations.AlterField(
            model_name='attendancerecord',
            name='source',
            field=models.CharField(
                choices=[
                    ('self_service', 'QR Kiosk Scan'),
                    ('hr', 'HR Entry / Correction'),
                    ('admin', 'Administrator Entry / Correction'),
                    ('leave_sync', 'Approved Leave'),
                    ('scheduled', 'Scheduled Absence Process'),
                ],
                default='self_service',
                max_length=20,
            ),
        ),
    ]
