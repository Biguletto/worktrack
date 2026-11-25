from django.db import migrations, models


def assign_legacy_roles(apps, schema_editor):
    EmployeeProfile = apps.get_model('eqrApp', 'EmployeeProfile')
    for profile in EmployeeProfile.objects.select_related('user').iterator():
        if profile.user.is_superuser:
            profile.role = 'admin'
        elif profile.user.direct_reports.exists():
            # Preserve the original application's manager-based supervisor model.
            profile.role = 'supervisor'
        elif profile.user.is_staff:
            profile.role = 'hr'
        else:
            profile.role = 'employee'
        profile.save(update_fields=['role'])


class Migration(migrations.Migration):
    dependencies = [
        ('eqrApp', '0023_employee_leave_attendance'),
    ]

    operations = [
        migrations.AddField(
            model_name='employeeprofile',
            name='role',
            field=models.CharField(
                choices=[
                    ('employee', 'Employee'),
                    ('supervisor', 'Supervisor'),
                    ('hr', 'HR Personnel'),
                    ('admin', 'Administrator'),
                ],
                default='employee',
                max_length=12,
            ),
        ),
        migrations.RunPython(assign_legacy_roles, migrations.RunPython.noop),
    ]
