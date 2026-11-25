from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import migrations
from django.utils import timezone


def _days_for_period(start_date, end_date, is_half_day, holidays):
    if is_half_day:
        if start_date == end_date and start_date.weekday() < 5 and start_date not in holidays:
            return Decimal('0.50')
        return Decimal('0.00')

    days = Decimal('0.00')
    cursor = start_date
    while cursor <= end_date:
        if cursor.weekday() < 5 and cursor not in holidays:
            days += Decimal('1.00')
        cursor += timedelta(days=1)
    return days


def reconcile_approved_leave_usage(apps, schema_editor):
    """Rebuild used days from approved requests so balances reflect historical usage."""
    db_alias = schema_editor.connection.alias
    LeaveType = apps.get_model('eqrApp', 'LeaveType')
    LeaveBalance = apps.get_model('eqrApp', 'LeaveBalance')
    LeaveApplication = apps.get_model('eqrApp', 'LeaveApplication')
    EmployeeProfile = apps.get_model('eqrApp', 'EmployeeProfile')
    Holiday = apps.get_model('eqrApp', 'Holiday')

    tracked_types = list(
        LeaveType.objects.using(db_alias).filter(is_active=True, track_balance=True)
    )
    tracked_type_ids = {item.pk for item in tracked_types}
    types_by_id = {item.pk: item for item in tracked_types}

    usage = defaultdict(lambda: Decimal('0.00'))
    approved_rows = LeaveApplication.objects.using(db_alias).filter(
        status='approved', leave_type_id__in=tracked_type_ids
    ).values(
        'employee_id', 'leave_type_id', 'start_date', 'end_date', 'is_half_day'
    ).iterator()

    for application in approved_rows:
        start_date = application['start_date']
        end_date = application['end_date']
        if not start_date or not end_date or end_date < start_date:
            continue
        holiday_dates = set(
            Holiday.objects.using(db_alias).filter(
                is_active=True, date__gte=start_date, date__lte=end_date
            ).values_list('date', flat=True)
        )
        for year in range(start_date.year, end_date.year + 1):
            year_start = date(year, 1, 1)
            year_end = date(year, 12, 31)
            segment_start = max(start_date, year_start)
            segment_end = min(end_date, year_end)
            is_half_day = bool(application['is_half_day']) and segment_start == segment_end
            used = _days_for_period(segment_start, segment_end, is_half_day, holiday_dates)
            if used:
                key = (application['employee_id'], application['leave_type_id'], year)
                usage[key] += used

    # Ensure every currently eligible profile has a current-year balance row.
    current_year = timezone.localdate().year
    eligible_profiles = EmployeeProfile.objects.using(db_alias).filter(
        role__in=['employee', 'supervisor', 'hr']
    ).values_list('pk', flat=True)
    for employee_id in eligible_profiles.iterator():
        for leave_type in tracked_types:
            LeaveBalance.objects.using(db_alias).get_or_create(
                employee_id=employee_id,
                leave_type_id=leave_type.pk,
                year=current_year,
                defaults={
                    'entitled_days': leave_type.default_entitled_days,
                    'used_days': Decimal('0.00'),
                },
            )

    # Create balances for historical/future entitlement years represented by
    # approved requests, then reconcile usage without double-counting old deductions.
    for (employee_id, leave_type_id, year), used_days in usage.items():
        leave_type = types_by_id[leave_type_id]
        balance, created = LeaveBalance.objects.using(db_alias).get_or_create(
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            year=year,
            defaults={
                'entitled_days': max(leave_type.default_entitled_days, used_days),
                'used_days': used_days,
            },
        )
        if not created:
            # Preserve any higher configured entitlement, but use approved records
            # as the authoritative amount already consumed.
            balance.used_days = used_days
            balance.entitled_days = max(
                balance.entitled_days,
                leave_type.default_entitled_days,
                used_days,
            )
            balance.save(using=db_alias, update_fields=['used_days', 'entitled_days'])

    # Existing tracked balances without approved requests should not retain
    # stale counters from an earlier inconsistent implementation.
    for balance in LeaveBalance.objects.using(db_alias).filter(
        leave_type_id__in=tracked_type_ids
    ).iterator():
        balance.used_days = usage.get(
            (balance.employee_id, balance.leave_type_id, balance.year),
            Decimal('0.00'),
        )
        leave_type = types_by_id[balance.leave_type_id]
        balance.entitled_days = max(
            balance.entitled_days,
            leave_type.default_entitled_days,
            balance.used_days,
        )
        balance.save(using=db_alias, update_fields=['used_days', 'entitled_days'])


class Migration(migrations.Migration):
    dependencies = [
        ('eqrApp', '0032_leave_entitlements_and_balances'),
    ]

    operations = [
        migrations.RunPython(
            reconcile_approved_leave_usage,
            migrations.RunPython.noop,
        ),
    ]
