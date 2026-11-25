from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_fixed_leave_types(apps, schema_editor):
    LeaveType = apps.get_model('eqrApp', 'LeaveType')
    fixed = [
        ('VL', 'Vacation Leave', 'General vacation or annual leave.', True, True),
        ('SL', 'Sick Leave', 'Leave requested for illness or recovery.', True, True),
        ('EL', 'Emergency Leave', 'Leave requested for urgent personal or family matters.', True, False),
        ('PL', 'Personal Leave', 'Leave requested for personal matters.', True, False),
        ('LWOP', 'Leave Without Pay', 'Unpaid leave category.', False, False),
    ]
    db_alias = schema_editor.connection.alias
    manager = LeaveType.objects.using(db_alias)
    fixed_codes = []
    for code, name, description, is_paid, track_balance in fixed:
        fixed_codes.append(code)
        item = manager.filter(code=code).first()
        if item is None:
            # A previous catalogue row may use the standard name but a different code.
            item = manager.filter(name=name).first()
        if item is None:
            manager.create(
                code=code, name=name, description=description,
                requires_document=False, is_paid=is_paid,
                track_balance=track_balance, is_active=True,
            )
        else:
            item.code = code
            item.name = name
            item.description = description
            item.requires_document = False
            item.is_paid = is_paid
            item.track_balance = track_balance
            item.is_active = True
            item.save(using=db_alias)
    manager.exclude(code__in=fixed_codes).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('eqrApp', '0030_daily_attendance_qr_and_admin_source'),
    ]

    operations = [
        migrations.CreateModel(
            name='SystemEventLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(default='application_event', max_length=40)),
                ('severity', models.CharField(choices=[('info', 'Information'), ('warning', 'Warning'), ('error', 'Error'), ('critical', 'Critical')], default='info', max_length=12)),
                ('message', models.TextField()),
                ('request_path', models.CharField(blank=True, max_length=500)),
                ('http_method', models.CharField(blank=True, max_length=12)),
                ('status_code', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('details', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='worktrack_system_events', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='systemeventlog',
            index=models.Index(fields=['severity', '-created_at'], name='system_event_severity_date_idx'),
        ),
        migrations.AddIndex(
            model_name='systemeventlog',
            index=models.Index(fields=['status_code', '-created_at'], name='system_event_status_date_idx'),
        ),
        migrations.RunPython(seed_fixed_leave_types, migrations.RunPython.noop),
    ]
