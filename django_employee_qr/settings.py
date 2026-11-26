"""Settings for WorkTrack HRMS."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Load developer-local settings from .env when present. EC2/systemd environment
# variables take precedence and production deployments do not need a .env file.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env', override=False)
except ImportError:
    pass

SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'dev-only-change-this-secret-key-before-deployment',
)
DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('1', 'true', 'yes')
ALLOWED_HOSTS = ['*'] if DEBUG else [
    host.strip() for host in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if host.strip()
]

ROOT_URLCONF = 'django_employee_qr.urls'
WSGI_APPLICATION = 'django_employee_qr.wsgi.application'
ASGI_APPLICATION = 'django_employee_qr.asgi.application'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'axes',
    'django.contrib.humanize',
    'eqrApp.apps.eqrAppConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'eqrApp.middleware.KioskSessionLockMiddleware',
    'axes.middleware.AxesMiddleware',
    'eqrApp.middleware.EnforceInitialPasswordChangeMiddleware',
    'eqrApp.middleware.SystemEventLoggingMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'eqrApp.context_processors.worktrack_access',
            ],
        },
    },
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        # Serialize local writers before a scan reads and updates the daily record.
        'OPTIONS': {'transaction_mode': 'IMMEDIATE'},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 8},
    },
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/private-media/'
MEDIA_ROOT = BASE_DIR / 'media'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'eqrApp:login'
LOGIN_REDIRECT_URL = 'eqrApp:home'
LOGOUT_REDIRECT_URL = 'eqrApp:login'

# Local-time cutoff used to classify an employee check-in as late.
ATTENDANCE_LATE_AFTER = os.environ.get('ATTENDANCE_LATE_AFTER', '09:00')

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1
AXES_RESET_ON_SUCCESS = True
# Employees share office and kiosk IPs. Keep the lockout attached to the account.
AXES_LOCKOUT_PARAMETERS = ['username']
# Axes recommends an IP lockout (W006), which would block unrelated users here.
SILENCED_SYSTEM_CHECKS = ['axes.W006']
# Render an application-branded lockout page instead of Axes' plain-text default.
AXES_LOCKOUT_TEMPLATE = 'account_locked.html'
AXES_HTTP_RESPONSE_CODE = 429

# Optional network allowlist for the administrator-operated attendance kiosk.
WORKTRACK_KIOSK_IP_RANGES = [
    item.strip() for item in os.environ.get('WORKTRACK_KIOSK_IP_RANGES', '').split(',') if item.strip()
]

# Trust X-Real-IP only when the immediate peer is one of these reverse proxies.
WORKTRACK_TRUSTED_PROXY_IPS = [
    item.strip() for item in os.environ.get('WORKTRACK_TRUSTED_PROXY_IPS', '127.0.0.1/32,::1/128').split(',') if item.strip()
]

# Optional SES notifications. Leave blank to disable outbound email.
AWS_SES_FROM_EMAIL = os.environ.get('AWS_SES_FROM_EMAIL', '')
WORKTRACK_HR_EMAILS = [
    item.strip() for item in os.environ.get('WORKTRACK_HR_EMAILS', '').split(',') if item.strip()
]
LEAVE_REMINDER_DAYS = int(os.environ.get('LEAVE_REMINDER_DAYS', '3'))

# Upload limits are also checked by the leave application view.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 30 * 1024 * 1024

# Password-reset email. Use SMTP in production (Amazon SES SMTP credentials can be used).
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend',
)
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', os.environ.get('AWS_SES_FROM_EMAIL', 'no-reply@worktrack.local'))
PASSWORD_RESET_TIMEOUT = 60 * 60  # One-hour reset link validity.
