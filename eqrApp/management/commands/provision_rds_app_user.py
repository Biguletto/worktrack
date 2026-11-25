import json
import os

import boto3
import psycopg
from psycopg import sql
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Create/update the least-privilege PostgreSQL login used by WorkTrack.'

    def handle(self, *args, **options):
        admin_secret_arn = os.environ.get('DB_ADMIN_SECRET_ARN', '').strip()
        if not admin_secret_arn:
            self.stdout.write('DB_ADMIN_SECRET_ARN is not set; application-user provisioning skipped.')
            return

        region = getattr(settings, 'AWS_REGION', '') or os.environ.get('AWS_DEFAULT_REGION')
        if not region:
            raise CommandError('Set AWS_REGION before provisioning the RDS application user.')

        try:
            secrets = boto3.client('secretsmanager', region_name=region)
            admin_secret = json.loads(secrets.get_secret_value(SecretId=admin_secret_arn)['SecretString'])
        except Exception as exc:
            raise CommandError('Unable to retrieve the RDS master secret using the EC2 instance role.') from exc

        database = settings.DATABASES['default']
        app_username = database['USER']
        app_password = database['PASSWORD']
        if not app_username or not app_password:
            raise CommandError('The application database secret is missing its username or password.')

        options = database.get('OPTIONS', {})
        connect_args = {
            'host': settings.DB_HOST,
            'port': settings.DB_PORT,
            'dbname': settings.DB_NAME,
            'user': admin_secret.get('username', ''),
            'password': admin_secret.get('password', ''),
            'sslmode': options.get('sslmode', 'require'),
            'connect_timeout': 15,
        }
        try:
            with psycopg.connect(**connect_args) as connection:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (app_username,))
                    role_exists = cursor.fetchone() is not None
                    if role_exists:
                        statement = sql.SQL('ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(
                            sql.Identifier(app_username), sql.Literal(app_password)
                        )
                    else:
                        statement = sql.SQL('CREATE ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(
                            sql.Identifier(app_username), sql.Literal(app_password)
                        )
                    cursor.execute(statement)
                    cursor.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(
                        sql.Identifier(settings.DB_NAME), sql.Identifier(app_username)
                    ))
                    cursor.execute(sql.SQL('GRANT USAGE, CREATE ON SCHEMA public TO {}').format(
                        sql.Identifier(app_username)
                    ))
                    cursor.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public TO {}').format(
                        sql.Identifier(app_username)
                    ))
                    cursor.execute(sql.SQL('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}').format(
                        sql.Identifier(app_username)
                    ))
                    cursor.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER ON TABLES TO {}').format(
                        sql.Identifier(app_username)
                    ))
                    cursor.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {}').format(
                        sql.Identifier(app_username)
                    ))
        except Exception as exc:
            raise CommandError('RDS application-user provisioning failed. Verify the RDS endpoint, master credentials, VPC access, and database privileges.') from exc

        self.stdout.write(self.style.SUCCESS(
            f'RDS application role {app_username!r} is ready. The Django application uses this account, not the RDS master login.'
        ))
