from decimal import Decimal

from django.db import migrations, models
from django.utils import timezone


def seed_leave_catalogue_and_balances(apps, schema_editor):
    LeaveType = apps.get_model('eqrApp', 'LeaveType')
    EmployeeProfile = apps.get_model('eqrApp', 'EmployeeProfile')
    LeaveBalance = apps.get_model('eqrApp', 'LeaveBalance')
    db_alias = schema_editor.connection.alias
    leave_manager = LeaveType.objects.using(db_alias)
    balance_manager = LeaveBalance.objects.using(db_alias)

    fixed_types = [
        ('SIL', 'Service Incentive Leave', '5 paid days per year. Demo entitlement; confirm applicable company and statutory eligibility.', True, Decimal('5.00')),
        ('MAT', 'Maternity Leave', '105 paid days for childbirth. Demo entitlement; eligibility and legal conditions must be reviewed for real use.', True, Decimal('105.00')),
        ('PAT', 'Paternity Leave', '7 paid days. Demo entitlement; eligibility and legal conditions must be reviewed for real use.', True, Decimal('7.00')),
        ('VL', 'Vacation Leave', '10 paid days per year as a configurable company-policy demo default.', True, Decimal('10.00')),
        ('SL', 'Sick Leave', '10 paid days per year as a configurable company-policy demo default.', True, Decimal('10.00')),
        ('EL', 'Emergency Leave', '3 paid days per year as a configurable company-policy demo default.', True, Decimal('3.00')),
        ('BL', 'Bereavement Leave', '3 paid days per year as a configurable company-policy demo default.', True, Decimal('3.00')),
    ]
    active_codes = []
    for code, name, description, paid, days in fixed_types:
        active_codes.append(code)
        item = leave_manager.filter(code=code).first()
        if item is None:
            item = leave_manager.create(
                code=code, name=name, description=description,
                requires_document=False, is_paid=paid,
                track_balance=True, default_entitled_days=days, is_active=True,
            )
        else:
            item.name = name
            item.description = description
            item.requires_document = False
            item.is_paid = paid
            item.track_balance = True
            item.default_entitled_days = days
            item.is_active = True
            item.save(using=db_alias)

    # Keep legacy categories for historical applications, but remove them from new forms.
    leave_manager.exclude(code__in=active_codes).update(is_active=False, track_balance=False)

    current_year = timezone.localdate().year
    eligible_profiles = EmployeeProfile.objects.using(db_alias).filter(
        role__in=['employee', 'supervisor', 'hr']
    )
    active_types = leave_manager.filter(code__in=active_codes, is_active=True)
    for profile in eligible_profiles.iterator():
        for leave_type in active_types:
            existing = balance_manager.filter(
                employee_id=profile.pk, leave_type_id=leave_type.pk, year=current_year
            ).first()
            if existing is None:
                balance_manager.create(
                    employee_id=profile.pk, leave_type_id=leave_type.pk,
                    year=current_year, entitled_days=leave_type.default_entitled_days,
                    used_days=Decimal('0.00'),
                )
            else:
                # Preserve existing usage and ensure the DB check constraint remains valid.
                existing.entitled_days = max(leave_type.default_entitled_days, existing.used_days)
                existing.save(using=db_alias, update_fields=['entitled_days'])


class Migration(migrations.Migration):
    dependencies = [
        ('eqrApp', '0031_system_event_log_and_fixed_leave_catalogue'),
    ]

    operations = [
        migrations.AddField(
            model_name='leavetype',
            name='default_entitled_days',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6),
        ),
        migrations.RunPython(seed_leave_catalogue_and_balances, migrations.RunPython.noop),
    ]
