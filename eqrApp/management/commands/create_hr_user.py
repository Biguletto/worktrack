from getpass import getpass

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from eqrApp.models import EmployeeProfile, LeaveType, LeaveBalance
from django.utils import timezone


class Command(BaseCommand):
    help = 'Create the initial HR Personnel account for a new WorkTrack installation.'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True)
        parser.add_argument('--email', required=True)
        parser.add_argument('--employee-id', required=True)
        parser.add_argument('--first-name', default='')
        parser.add_argument('--last-name', default='')

    def handle(self, *args, **options):
        username = options['username'].strip()
        email = options['email'].strip()
        employee_id = options['employee_id'].strip()
        if not username or not email or not employee_id:
            raise CommandError('Username, email, and employee ID are required.')
        if User.objects.filter(username=username).exists():
            raise CommandError(f'Username {username!r} already exists.')
        if EmployeeProfile.objects.filter(employee_id=employee_id).exists():
            raise CommandError(f'Employee ID {employee_id!r} already exists.')
        password = getpass('Temporary password: ')
        confirmation = getpass('Confirm temporary password: ')
        if password != confirmation:
            raise CommandError('The entered passwords do not match.')
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(' '.join(exc.messages)) from exc
        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=options['first_name'],
                last_name=options['last_name'],
                is_staff=True,
                is_active=True,
            )
            profile = EmployeeProfile.objects.create(
                user=user,
                employee_id=employee_id,
                role='hr',
                department='HR',
                position='HR Manager',
                employment_status='active',
                must_change_password=True,
            )
            for leave_type in LeaveType.objects.filter(is_active=True, track_balance=True):
                LeaveBalance.objects.get_or_create(
                    employee=profile, leave_type=leave_type, year=timezone.localdate().year,
                    defaults={'entitled_days': leave_type.default_entitled_days, 'used_days': 0},
                )
        self.stdout.write(self.style.SUCCESS(
            f'Created HR Personnel account {username!r}. The user must change the temporary password at first sign-in.'
        ))
