from django.core.management.base import BaseCommand
from django.utils import timezone

from eqrApp.attendance_qr import get_or_create_daily_qr, QR_ELIGIBLE_ROLES
from eqrApp.models import EmployeeProfile


class Command(BaseCommand):
    help = 'Generate or initialize today\'s attendance QR credential for every active employee and supervisor profile.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        profiles = EmployeeProfile.objects.filter(
            employment_status='active', role__in=QR_ELIGIBLE_ROLES
        ).order_by('employee_id')
        created_or_existing = 0
        for profile in profiles.iterator():
            if get_or_create_daily_qr(profile, qr_date=today):
                created_or_existing += 1
        self.stdout.write(self.style.SUCCESS(
            f'Initialized {created_or_existing} daily attendance QR credential(s) for {today}.'
        ))
