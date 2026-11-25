"""Create fictional, repeatable records for the WorkTrack class demonstration."""
from datetime import datetime, time, timedelta
from getpass import getpass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from eqrApp.attendance_qr import get_or_create_daily_qr
from eqrApp.models import (
    AttendanceRecord,
    EmployeeProfile,
    Holiday,
    LeaveAction,
    LeaveApplication,
    LeaveBalance,
    LeaveType,
)


User = get_user_model()


class Command(BaseCommand):
    help = (
        "Create fictional WorkTrack demo users, holidays, leave requests, attendance "
        "and daily QR rows. Use only in a demonstration database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            dest="password",
            help="Initial password for newly created demo accounts (interactive prompt if omitted).",
        )
        parser.add_argument(
            "--allow-production",
            action="store_true",
            help="Allow seeding when DEBUG=False. Use only with a disposable/demo database.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["allow_production"]:
            raise CommandError(
                "Refusing to seed while DEBUG=False. For a fictional class-demo database only, "
                "rerun with --allow-production."
            )

        if not settings.DEBUG and options["allow_production"]:
            self.stdout.write(self.style.WARNING(
                "You are about to add fictional demo users and records to a DEBUG=False database."
            ))
            confirmation = input("Type SEED DEMO DATA to continue: ").strip()
            if confirmation != "SEED DEMO DATA":
                raise CommandError("Demo data seeding cancelled.")

        password = options.get("password")
        if not password:
            password = getpass("Initial password for newly created demo accounts (minimum 8 characters): ")
            confirmation = getpass("Confirm demo password: ")
            if password != confirmation:
                raise CommandError("The passwords did not match.")
        if len(password) < 8:
            raise CommandError("The demo password must contain at least 8 characters.")

        with transaction.atomic():
            admin_user, admin_created = self._user(
                "demo.admin", "demo.admin@example.invalid", "Demo", "Administrator", password,
                is_staff=True, is_superuser=True,
            )
            hr_user, hr_created = self._user(
                "demo.hr", "demo.hr@example.invalid", "Demo", "HR", password,
                is_staff=True, is_superuser=False,
            )
            supervisor_user, supervisor_created = self._user(
                "demo.supervisor", "demo.supervisor@example.invalid", "Demo", "Supervisor", password,
                is_staff=False, is_superuser=False,
            )
            employee_one_user, employee_one_created = self._user(
                "demo.employee001", "demo.employee001@example.invalid", "Alex", "Santos", password,
                is_staff=False, is_superuser=False,
            )
            employee_two_user, employee_two_created = self._user(
                "demo.employee002", "demo.employee002@example.invalid", "Jamie", "Reyes", password,
                is_staff=False, is_superuser=False,
            )

            admin_profile = self._profile(
                admin_user, "DEMO-ADM", "admin", "IT", "IT Manager", None,
            )
            hr_profile = self._profile(
                hr_user, "DEMO-HR", "hr", "HR", "HR Manager", None,
            )
            supervisor_profile = self._profile(
                supervisor_user, "DEMO-SUP", "supervisor", "Marketing", "Marketing Manager", None,
            )
            employee_one = self._profile(
                employee_one_user, "DEMO-EMP-001", "employee", "Marketing", "Sales Representative",
                supervisor_user,
            )
            employee_two = self._profile(
                employee_two_user, "DEMO-EMP-002", "employee", "Marketing", "Sales Representative",
                supervisor_user,
            )

            today = timezone.localdate()
            future_holiday_one = self._next_weekday(today + timedelta(days=21))
            future_holiday_two = self._next_weekday(today + timedelta(days=42))
            Holiday.objects.get_or_create(
                date=future_holiday_one,
                defaults={"name": "Demo Company Foundation Day", "is_active": True},
            )
            Holiday.objects.get_or_create(
                date=future_holiday_two,
                defaults={"name": "Demo Wellness Day", "is_active": True},
            )

            try:
                vacation = LeaveType.objects.get(code="VL", is_active=True)
                sick = LeaveType.objects.get(code="SL", is_active=True)
            except LeaveType.DoesNotExist as exc:
                raise CommandError(
                    "The fixed leave catalogue is missing. Run `python manage.py migrate` first."
                ) from exc

            # Initialize every fixed leave entitlement for each demo staff profile.
            for profile in (supervisor_profile, employee_one, employee_two):
                for leave_type in LeaveType.objects.filter(is_active=True, track_balance=True):
                    LeaveBalance.objects.get_or_create(
                        employee=profile,
                        leave_type=leave_type,
                        year=today.year,
                        defaults={
                            "entitled_days": leave_type.default_entitled_days,
                            "used_days": 0,
                        },
                    )

            leave_one_start = self._next_weekday(today + timedelta(days=10))
            leave_one_end = self._next_weekday(leave_one_start + timedelta(days=1))
            leave_one, leave_one_created = LeaveApplication.objects.get_or_create(
                employee=employee_one,
                leave_type=vacation,
                start_date=leave_one_start,
                end_date=leave_one_end,
                defaults={
                    "reason": "Fictional demo request for a family event.",
                    "status": "pending_manager",
                },
            )
            self._action(leave_one, "submitted", employee_one_user, "Fictional demo leave request submitted.")

            leave_two_start = self._next_weekday(today + timedelta(days=18))
            leave_two, leave_two_created = LeaveApplication.objects.get_or_create(
                employee=employee_two,
                leave_type=sick,
                start_date=leave_two_start,
                end_date=leave_two_start,
                defaults={
                    "reason": "Fictional demo medical appointment.",
                    "status": "pending_hr",
                    "manager_reviewed_by": supervisor_user,
                    "manager_reviewed_at": timezone.now(),
                    "manager_comments": "Reviewed in the class demonstration.",
                },
            )
            self._action(leave_two, "submitted", employee_two_user, "Fictional demo leave request submitted.")
            self._action(leave_two, "manager_approved", supervisor_user, "Acknowledged by the demo supervisor.")

            demo_attendance = [
                (supervisor_profile, "08:35", "present"),
                (employee_one, "08:52", "present"),
                (employee_two, "09:18", "late"),
            ]
            for profile, check_in_time, status in demo_attendance:
                check_in = self._local_datetime(today, check_in_time)
                AttendanceRecord.objects.update_or_create(
                    employee=profile,
                    attendance_date=today,
                    defaults={
                        "check_in": check_in,
                        "check_out": None,
                        "status": status,
                        "source": "admin",
                        "remarks": "Fictional record created by seed_worktrack_demo.",
                        "recorded_by": admin_user,
                    },
                )

            # Only employees and supervisors use the attendance kiosk.
            for profile in (supervisor_profile, employee_one, employee_two):
                get_or_create_daily_qr(profile, qr_date=today)

        created_count = sum((admin_created, hr_created, supervisor_created, employee_one_created, employee_two_created))
        self.stdout.write(self.style.SUCCESS("WorkTrack demo data is ready."))
        self.stdout.write(f"New accounts created: {created_count}; existing demo accounts were retained.")
        self.stdout.write("Demo usernames:")
        for username in (
            "demo.admin", "demo.hr", "demo.supervisor", "demo.employee001", "demo.employee002"
        ):
            self.stdout.write(f"  - {username}")
        self.stdout.write("The password you entered applies only to accounts created by this command.")
        self.stdout.write("Fictional sample records are repeatable when the command is run again on the same local demo date; a new attendance date naturally receives a new daily attendance row.")

    def _user(self, username, email, first_name, last_name, password, *, is_staff, is_superuser):
        user = User.objects.filter(username=username).first()
        created = user is None
        if created:
            user = User(username=username, email=email, first_name=first_name, last_name=last_name)
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.is_active = True
            user.set_password(password)
            user.save()
        else:
            if is_superuser and not user.is_superuser:
                raise CommandError(
                    f"Existing account {username!r} is not a superuser. Resolve that account manually before seeding."
                )
            user.first_name = first_name
            user.last_name = last_name
            user.email = email
            user.is_active = True
            if is_staff and not user.is_staff:
                user.is_staff = True
            user.save(update_fields=["first_name", "last_name", "email", "is_active", "is_staff"])
        return user, created

    def _profile(self, user, employee_id, role, department, position, manager):
        profile, _ = EmployeeProfile.objects.update_or_create(
            user=user,
            defaults={
                "employee_id": employee_id,
                "role": role,
                "department": department,
                "position": position,
                "manager": manager,
                "employment_status": "active",
            },
        )
        return profile

    def _action(self, application, action, actor, comments):
        LeaveAction.objects.get_or_create(
            application=application,
            action=action,
            actor=actor,
            defaults={"comments": comments},
        )

    @staticmethod
    def _next_weekday(day):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        return day

    @staticmethod
    def _local_datetime(day, hhmm):
        parsed = datetime.combine(day, time.fromisoformat(hhmm))
        return timezone.make_aware(parsed, timezone.get_current_timezone())
