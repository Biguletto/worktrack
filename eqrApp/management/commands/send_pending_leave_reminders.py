from datetime import timedelta
from django.db.models import Q

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from eqrApp.models import LeaveApplication
from eqrApp.notifications import send_worktrack_email


class Command(BaseCommand):
    help = 'Send optional SES reminders for leave requests waiting for review.'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=getattr(settings, 'LEAVE_REMINDER_DAYS', 3))
        reminder_due = timezone.now() - timedelta(days=1)
        pending = LeaveApplication.objects.filter(
            status__in=['pending_manager', 'pending_hr'], submitted_at__lte=cutoff
        ).filter(Q(last_reminder_at__isnull=True) | Q(last_reminder_at__lte=reminder_due)).select_related('employee__user', 'employee__manager', 'employee__backup_manager', 'leave_type')
        sent = 0
        for application in pending.iterator():
            if application.status == 'pending_manager':
                recipients = [
                    getattr(application.employee.manager, 'email', ''),
                    getattr(application.employee.backup_manager, 'email', ''),
                ]
                stage = 'supervisor review'
            else:
                recipients = getattr(settings, 'WORKTRACK_HR_EMAILS', [])
                stage = 'HR review'
            was_sent = send_worktrack_email(
                f'WorkTrack reminder: leave request #{application.pk}',
                f'Leave request #{application.pk} for {application.employee.full_name} ({application.leave_type.name}) is awaiting {stage}.',
                recipients,
            )
            if was_sent:
                application.last_reminder_at = timezone.now()
                application.save(update_fields=['last_reminder_at'])
                sent += 1
        self.stdout.write(self.style.SUCCESS(f'Sent {sent} reminder email(s).'))
