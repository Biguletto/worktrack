"""Daily QR credential creation, signing, rendering, and validation."""
import base64
from io import BytesIO

import qrcode
from django.core import signing
from django.utils import timezone

from .models import DailyAttendanceQR, EmployeeProfile

QR_SIGNER = signing.Signer(salt='worktrack.daily-attendance-qr.v1')
QR_ELIGIBLE_ROLES = ('employee', 'supervisor')


def get_or_create_daily_qr(employee, qr_date=None):
    """Return the persistent nonce row for one employee and one local date."""
    qr_date = qr_date or timezone.localdate()
    if not employee.user.is_active or employee.employment_status != 'active' or employee.role not in QR_ELIGIBLE_ROLES:
        return None
    qr_record, _ = DailyAttendanceQR.objects.get_or_create(
        employee=employee,
        qr_date=qr_date,
    )
    return qr_record


def build_daily_qr_token(qr_record):
    """Sign employee, date, and unpredictable nonce without exposing a database ID alone."""
    payload = {
        'employee_pk': qr_record.employee_id,
        'qr_date': qr_record.qr_date.isoformat(),
        'nonce': str(qr_record.nonce),
        'version': 1,
    }
    return QR_SIGNER.sign_object(payload, compress=True)


def build_daily_qr_bundle(employee, qr_date=None):
    """Create the employee's daily QR image for display on their dashboard."""
    qr_record = get_or_create_daily_qr(employee, qr_date=qr_date)
    if qr_record is None:
        return None

    token = build_daily_qr_token(qr_record)
    # Keep the QR at a high source resolution and preserve a clear quiet zone.
    # M-level error correction avoids making this signed token unnecessarily dense.
    qr_code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=5,
    )
    qr_code.add_data(token)
    qr_code.make(fit=True)
    qr_image = qr_code.make_image(fill_color='black', back_color='white')
    image_buffer = BytesIO()
    qr_image.save(image_buffer, format='PNG')
    image_base64 = base64.b64encode(image_buffer.getvalue()).decode('ascii')
    return {
        'record': qr_record,
        'token': token,
        'image_data_uri': f'data:image/png;base64,{image_base64}',
        'qr_date': qr_record.qr_date,
    }


def validate_daily_qr_token(token, today=None):
    """Validate signature, current local date, nonce, and employee eligibility."""
    today = today or timezone.localdate()
    if not token or len(token) > 2048:
        raise signing.BadSignature('The QR code is empty or invalid.')

    try:
        payload = QR_SIGNER.unsign_object(token)
        employee_pk = int(payload['employee_pk'])
        qr_date = payload['qr_date']
        nonce = str(payload['nonce'])
        version = payload['version']
    except (signing.BadSignature, KeyError, TypeError, ValueError, AttributeError):
        raise signing.BadSignature('The QR code is invalid or has been altered.')

    if version != 1 or qr_date != today.isoformat():
        raise signing.BadSignature('This QR code has expired. Use today\'s QR code.')

    try:
        qr_record = DailyAttendanceQR.objects.select_related('employee__user').get(
            employee_id=employee_pk,
            qr_date=today,
        )
    except DailyAttendanceQR.DoesNotExist:
        raise signing.BadSignature('This QR code is not registered for today.')

    if str(qr_record.nonce) != nonce:
        raise signing.BadSignature('This QR code is no longer valid.')

    employee = qr_record.employee
    if not employee.user.is_active or employee.employment_status != 'active' or employee.role not in QR_ELIGIBLE_ROLES:
        raise signing.BadSignature('This employee account is inactive or not eligible for attendance scanning.')

    return qr_record
