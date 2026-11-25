import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('eqrApp', '0026_worktrack_security_audit_and_leave_tools'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='leaveapplication',
            name='last_reminder_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='LeaveDeletionAudit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('application_reference', models.PositiveBigIntegerField()),
                ('employee_id_snapshot', models.CharField(max_length=30)),
                ('employee_name_snapshot', models.CharField(max_length=160)),
                ('leave_type_name', models.CharField(max_length=80)),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('previous_status', models.CharField(max_length=20)),
                ('deleted_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('employee', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='leave_deletion_audits', to='eqrApp.employeeprofile')),
            ],
            options={'ordering': ['-deleted_at']},
        ),
    ]
