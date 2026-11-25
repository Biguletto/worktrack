from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [('eqrApp', '0027_leave_deletion_audit_and_reminders')]

    operations = [
        migrations.AddConstraint(
            model_name='leaveapplication',
            constraint=models.CheckConstraint(
                condition=Q(('is_half_day', False), ('start_date', models.F('end_date')), _connector='OR'),
                name='half_day_leave_single_date',
            ),
        ),
        migrations.AddConstraint(
            model_name='leavebalance',
            constraint=models.CheckConstraint(
                condition=Q(('used_days__lte', models.F('entitled_days'))),
                name='leave_balance_used_not_over_entitlement',
            ),
        ),
        migrations.AddConstraint(
            model_name='attendancerecord',
            constraint=models.CheckConstraint(
                condition=Q(('check_in__isnull', True), ('check_out__isnull', True), ('check_out__gte', models.F('check_in')), _connector='OR'),
                name='attendance_checkout_not_before_checkin',
            ),
        ),
    ]
