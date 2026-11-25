"""Production settings for WorkTrack on EC2, Amazon RDS and Amazon S3.

Required environment variables are documented in .env.example and README.md.
The application intentionally refuses to start when durable cloud services or
secret configuration are missing.
"""

import os
import json
import boto3
from django.core.exceptions import ImproperlyConfigured
from .settings import *  # noqa: F401,F403

DEBUG = False

SECRET_KEY = os.environ.get('SECRET_KEY', '').strip()
if not SECRET_KEY:
    raise ImproperlyConfigured('SECRET_KEY must be set in the EC2 environment.')

ALLOWED_HOSTS = [
    value.strip() for value in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if value.strip()
]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured('Set DJANGO_ALLOWED_HOSTS to the EC2 DNS name, Elastic IP, or domain.')

CSRF_TRUSTED_ORIGINS = [
    value.strip() for value in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if value.strip()
]
if not CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS = [f'https://{host}' for host in ALLOWED_HOSTS if not host.startswith('.')]

# Amazon RDS PostgreSQL. No credentials are stored in source control.
DB_NAME = os.environ.get('DB_NAME', 'worktrack').strip()
DB_USER = os.environ.get('DB_USER', '').strip()
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
DB_HOST = os.environ.get('DB_HOST', '').strip()
DB_PORT = os.environ.get('DB_PORT', '5432').strip()
DB_SECRET_ARN = os.environ.get('DB_SECRET_ARN', '').strip()
if DB_SECRET_ARN and (not DB_USER or not DB_PASSWORD):
    try:
        secret_response = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION')).get_secret_value(SecretId=DB_SECRET_ARN)
        secret_values = json.loads(secret_response['SecretString'])
        DB_USER = DB_USER or secret_values.get('username', '')
        DB_PASSWORD = DB_PASSWORD or secret_values.get('password', '')
    except Exception as exc:
        raise ImproperlyConfigured('Could not retrieve the RDS credentials from AWS Secrets Manager using the EC2 instance role.') from exc
if not all([DB_USER, DB_PASSWORD, DB_HOST]):
    raise ImproperlyConfigured('Set DB_USER/DB_PASSWORD or DB_SECRET_ARN, and set DB_HOST for Amazon RDS.')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': DB_NAME,
        'USER': DB_USER,
        'PASSWORD': DB_PASSWORD,
        'HOST': DB_HOST,
        'PORT': DB_PORT,
        'CONN_MAX_AGE': 60,
        'OPTIONS': {
            'sslmode': os.environ.get('DB_SSLMODE', 'require'),
            **({'sslrootcert': os.environ['DB_SSLROOTCERT']} if os.environ.get('DB_SSLROOTCERT') else {}),
        },
    }
}

# Leave documents and generated reports are private S3 objects. The storage
# backend signs object URLs only after the application has checked access.
AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', '').strip()
AWS_REGION = os.environ.get('AWS_REGION', os.environ.get('AWS_DEFAULT_REGION', '')).strip()
if not AWS_STORAGE_BUCKET_NAME or not AWS_REGION:
    raise ImproperlyConfigured('AWS_STORAGE_BUCKET_NAME and AWS_REGION are required in production.')

AWS_S3_REGION_NAME = AWS_REGION
AWS_S3_SIGNATURE_VERSION = 's3v4'
AWS_S3_ADDRESSING_STYLE = 'virtual'
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True
AWS_QUERYSTRING_EXPIRE = 300
AWS_S3_FILE_OVERWRITE = False
AWS_S3_OBJECT_PARAMETERS = {
    'ServerSideEncryption': 'AES256',
    'CacheControl': 'private, max-age=0, no-cache, no-store, must-revalidate',
}
AWS_S3_VERIFY = True

STORAGES = {
    'default': {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {
            'bucket_name': AWS_STORAGE_BUCKET_NAME,
            'region_name': AWS_REGION,
            'default_acl': None,
            'querystring_auth': True,
            'querystring_expire': 300,
            'file_overwrite': False,
            'object_parameters': AWS_S3_OBJECT_PARAMETERS,
        },
    },
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

# HTTPS must be terminated by nginx or a load balancer before enabling this.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SECURE_SSL_REDIRECT', 'true').lower() in ('1', 'true', 'yes')
SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0
SECURE_REFERRER_POLICY = 'same-origin'

# Collectstatic writes locally; uploaded files are handled by the S3 backend.
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
