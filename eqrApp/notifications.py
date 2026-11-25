"""Optional Amazon SES notifications. No email is sent until configured."""
import logging

import boto3
from django.conf import settings

logger = logging.getLogger(__name__)


def send_worktrack_email(subject, body, recipients):
    sender = getattr(settings, 'AWS_SES_FROM_EMAIL', '').strip()
    recipients = sorted({address.strip() for address in recipients if address and address.strip()})
    if not sender or not recipients:
        return False

    try:
        client = boto3.client('ses', region_name=getattr(settings, 'AWS_REGION', None) or getattr(settings, 'AWS_DEFAULT_REGION', None))
        client.send_email(
            Source=sender,
            Destination={'ToAddresses': recipients},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {'Text': {'Data': body, 'Charset': 'UTF-8'}},
            },
        )
        return True
    except Exception:
        logger.exception('WorkTrack notification could not be sent through Amazon SES.')
        return False
