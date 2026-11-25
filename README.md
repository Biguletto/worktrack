# WorkTrack - Employee Leave and Attendance Management System

WorkTrack is a role-based web information system for managing employee accounts, daily attendance, leave applications, supporting documents, and a Supervisor acknowledgement followed by HR final decision. It is designed as a cloud application: Django runs on Amazon EC2, relational records are stored in Amazon RDS for PostgreSQL, and private attachments and exported reports are stored in Amazon S3.

> **Deployment status:** This repository contains the revised application code and AWS deployment templates. It does not prove that an AWS stack has already been created. A group member must deploy the CloudFormation template in the group's AWS account, configure the domain/TLS and application environment, run migrations, create the first administrator, and complete the live integration tests before describing the system as deployed.

## 1. Project objectives

- Centralize employee profile, attendance, and leave records.
- Give employees, supervisors, HR personnel, and administrators access to the appropriate functions for their role.
- Support employee-specific daily QR check-in/check-out through an administrator-operated kiosk, role-based attendance monitoring, and monthly attendance export.
- Provide a two-stage leave approval process with supervisor delegation and HR's final decision.
- Store supporting documents in a private S3 bucket and application data in an RDS SQL database.
- Keep an audit trail for QR scans and security events, and retain a deletion audit for cancelled/rejected leave requests.
- Deploy the application through an EC2-hosted Django/Gunicorn/Nginx stack and control access using VPC, security groups, and IAM.

## 2. User roles and system functions

| Role | Main permissions |
|---|---|
| Employee | View their personal dashboard and daily QR code, review their own per-day attendance and leave balances, submit leave applications from Leave Requests, upload supporting documents, track decisions, and cancel pending requests. |
| Supervisor | Employee self-service functions and their own daily QR code, plus read-only monitoring of assigned-team attendance, team leave requests, and acknowledgement of requests from assigned employees; supervisors cannot approve or decline requests. Supervisors submit their own requests from Team Leave Requests. |
| HR Personnel | Create, update, and deactivate/terminate Employee and Supervisor accounts; view the employee overview; process final leave approvals after Supervisor acknowledgement; manage leave balances and holidays; and view the fixed company-wide leave catalogue. |
| Administrator (IT Personnel) | View system overview and sanitized warning/error logs; provide employee account support limited to username, name, and password resets; and operate the protected QR kiosk. Attendance and leave records are read-only; the Administrator cannot create, update, approve, reject, or delete them. |

There is no public self-registration page. The first IT Administrator is provisioned with Django's `createsuperuser` command. The initial HR Personnel account is provisioned from the command line with `python manage.py create_hr_user`; this avoids giving the IT Administrator access to HR account-management functions. The provisioning command assigns the initial HR account to the fixed HR department with the HR Manager job title; its WorkTrack access remains HR Personnel. HR then creates Employee and Supervisor accounts through WorkTrack. Newly created accounts receive a temporary password and must change it at first sign-in. The application's `/admin/` Django administration route is intentionally not exposed as a second business-data console. For the shared kiosk laptop, create a separate Administrator superuser used only for kiosk operation rather than leaving a personal Administrator account signed in.

## 3. Main workflows

### Attendance

Only Employee and Supervisor profiles receive an employee-specific QR code on their dashboard. HR is a role account, not an employee attendance profile, and does not receive a QR code. The code is valid for one local calendar day (Asia/Manila) and is rotated at midnight. At the administrator-operated laptop kiosk, the first scan records check-in and the second scan records check-out. The kiosk page and scan endpoint both require an authenticated Administrator role; an optional kiosk IP CIDR allow-list can further restrict the device/network. HR Company Attendance has been removed. Supervisors can monitor their assigned team and their own records; employees can monitor their own records. The kiosk accepts validated employee QR scans and current-time manual entries by employee ID from unlocked Administrator settings. Both are recorded in `AttendanceAudit` with the kiosk operator, timestamp, and before/after values. The `mark_daily_absences` management command creates an absence record for an active employee who has no attendance record, while skipping weekends, configured holidays, and approved leave.

### Leave application and approval

1. An employee selects a leave type and date range, enters a reason, and attaches any required supporting documents.
2. The form rejects past dates, overlapping active requests, invalid half-day ranges, dates with no working days, invalid file extensions/signatures, files larger than 5 MB, or more than five attachments.
3. A request is sent to the employee's assigned supervisor or backup supervisor. The Supervisor must acknowledge it and forward it to HR. If a request has no assigned Supervisor, it can enter the HR queue directly according to the configured workflow.
4. The assigned Supervisor acknowledges the request and forwards it to HR. The Supervisor cannot approve or decline it. HR alone provides the final approval or rejection, and HR cannot decide until Supervisor acknowledgement is recorded.
5. Final HR approval deducts the configured balance (where balance tracking is enabled) and creates/updates attendance rows with `half_day` or `on_leave` status. Supervisors only acknowledge and forward; HR alone makes the final approval or rejection.
6. The application action history records each workflow action. If a rejected/cancelled request is deleted, a separate `LeaveDeletionAudit` row preserves a minimal reference, employee snapshot, leave type, dates, prior status, actor, and deletion time.

Leave duration is counted as working days (Monday to Friday), excluding active dates in the Holiday Calendar. Half-day applications must cover one date and count as 0.5 day. HR must configure balances for each balance-tracked leave type and employee/year before employees can submit that category. A request is blocked when the available balance after pending requests is insufficient.

### IT oversight and password recovery

The Administrator dashboard is an IT overview rather than an HR management console. It shows operational counters and recent warning/error events. The System Logs / Errors page is Administrator-only and shows warning and error events only, with date and severity filters. The log presentation suppresses employee identity and actor information and omits passwords, form bodies, and signed QR tokens. Password recovery is available through the login page; reset links expire after one hour. For the class demo, use Django's console email backend so reset links and notifications are written to the service output and can be inspected with `journalctl -u worktrack`; this mode does not deliver real email. SES remains disabled for the demo.

### Documents and reports

Leave documents are private. The download view checks the user's permission before returning the file or redirecting to a short-lived signed S3 URL (five-minute expiry in production). Attendance reports are generated as CSV and saved to the configured default storage; in production this is the private S3 bucket and the response redirects to a signed URL. The local-development storage backend saves to the local media folder only for development.

The class-demo environment uses the console email backend and leaves SES disabled. A separate production setup may configure SMTP/SES for submissions, approval decisions, password resets, and reminders; SES sender verification and sandbox recipient restrictions still apply. Reminder state is stored so that successful reminders are not sent more than once every 24 hours for the same request.

## 4. Technology stack

- Python 3.10+ and Django 5.2
- Django templates, HTML, CSS, Bootstrap 5.3 and Font Awesome (CDN-based frontend assets)
- Amazon EC2 Ubuntu, Gunicorn, and Nginx for hosting
- Amazon RDS for PostgreSQL (production) and SQLite (local development only)
- Amazon S3 with `django-storages` and `boto3` for private documents and reports
- Amazon VPC, public/private subnets, route tables, Internet Gateway, S3 Gateway VPC Endpoint, and security groups
- AWS IAM EC2 instance profile, AWS Secrets Manager for the RDS password, and optional Amazon SES
- Git and GitHub for source control


## Daily QR attendance and secured kiosk

The Employee and Supervisor dashboards display a unique QR code for the signed-in employee profile. HR and Administrator are role accounts and do not receive employee QR credentials. Each QR credential is tied to the employee profile, local date, and a random nonce, and is signed with Django's application secret key. Scanning validates the signature, active account, employee/day record, and current Asia/Manila date. A QR code from the previous date is rejected after midnight. The dashboard lazily initializes today's QR row, while the scheduled command pre-creates QR rows for active Employee and Supervisor profiles:

```bash
python manage.py generate_daily_attendance_qr
```

Schedule this command daily at 12:00 AM Asia/Manila. The deployment crontab example is `deploy/aws/worktrack-daily-jobs.example`. On Windows development machines, create a Task Scheduler task with a daily 12:00 AM trigger and this action: Program = `<project>\venv\Scripts\python.exe`, Arguments = `manage.py generate_daily_attendance_qr`, Start in = the folder containing `manage.py`. Dashboard access also initializes the current day's credential if the task has not run.

The first scan at the laptop kiosk records check-in; the next scan of that same daily QR records check-out. The kiosk uses the pinned `@zxing/browser` 0.2.1 library with the laptop camera. It first decodes the original camera frame, then retries an enhanced center crop, and finally a thresholded image. This improves tolerance for mild blur, low contrast, and screen glare, but cannot reconstruct QR details that are fully out of focus, clipped by overexposure, or too small. Camera selection is available only inside the password-protected Administrator settings. After a scan, the kiosk accepts a different employee QR and updates its attendance log without a page refresh. It suppresses repeated frames of the same visible token to prevent accidental double scans. Employee and Supervisor accounts receive larger daily QR codes; HR and Administrator role accounts do not receive employee QR credentials. Only an authenticated Administrator may activate and operate the scanner. HR Company Attendance is removed; Supervisors see assigned-team attendance and Employees see their own records. Administrators can record current attendance by employee ID through the password-protected kiosk settings.

For a dedicated production kiosk, set `WORKTRACK_KIOSK_IP_RANGES` in the server environment to the kiosk laptop's trusted IP or subnet in CIDR notation (for example, `10.0.4.25/32`). Leave it blank only for local development or where network filtering is enforced by an upstream firewall. The kiosk session should remain signed in only on the managed laptop, and the browser should not be used as a general-purpose workstation.

For a remote EC2 class demonstration without a public HTTPS certificate, use the SSH port-forward in `docs/demo-deployment-guide.md` and open the kiosk at `http://localhost:8000/accounts/attendance/kiosk/`. The service binds Gunicorn to loopback port 8000, so do not open port 8000 in the EC2 security group. Remove public HTTP/HTTPS ingress while using the tunnel-only configuration. For a camera fallback, enter the employee ID in unlocked Administrator kiosk settings.

## 5. Local development setup

Requirements: Python 3.10 or newer and Git.

```bash
# Windows PowerShell
python -m venv venv
venv\Scripts\Activate.ps1

# macOS/Linux (use this instead of the Windows activation command)
# python3 -m venv venv
# source venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env  # Windows; on macOS/Linux use: cp .env.example .env
```

The example `.env` file uses `django_employee_qr.settings` with SQLite and local uploads. Set a strong local `SECRET_KEY`. Then run:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Sign in with the superuser. From the WorkTrack account pages, create HR, supervisor, and employee accounts. Newly provisioned accounts must change their temporary password on first login.

The local SQLite database is for development and tests only. Do not copy `db.sqlite3`, local media, or any real user information into a public GitHub repository. **Before applying migrations 0025 onward to a database that contains earlier SnapTrack records, take a database backup. Migration 0025 drops the obsolete SnapTrack `Member`, `Event`, `Attendance`, and `QRCode` tables; those legacy QR/event records are not converted into WorkTrack employee attendance.**

For fictional class records, run `python manage.py seed_worktrack_demo` after migrations. The command prompts for an initial password and creates dedicated `demo.*` role accounts, sample holidays, leave requests, balances, attendance rows, and daily QR rows. It can be re-run without duplicating the same-date sample attendance/QR rows and does not overwrite passwords for existing demo users; each new date naturally receives new daily attendance/QR records. It refuses to run with `DEBUG=False` unless `--allow-production` is added and the operator confirms; use that override only on a disposable database with fictional data. See `docs/demo-deployment-guide.md`.

## 6. Environment variables

### Local development

`DJANGO_SETTINGS_MODULE=django_employee_qr.settings`  
`DJANGO_DEBUG=True`  
`SECRET_KEY=<random-development-secret>`  
`ATTENDANCE_LATE_AFTER=09:00`

### Production on EC2

Create `/etc/worktrack/worktrack.env` on EC2 with restrictive file permissions (`root:www-data`, mode `0640`). Do not commit this file. Example keys:

```dotenv
DJANGO_SETTINGS_MODULE=django_employee_qr.production_settings
DJANGO_DEBUG=False
SECRET_KEY=<long-random-secret-generated-for-this-deployment>
# For tunnel-only kiosk demonstration (remove public HTTP/HTTPS ingress first):
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost,http://127.0.0.1
DJANGO_SECURE_SSL_REDIRECT=false
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
# For a public HTTPS deployment, replace the three values above with your real DNS/HTTPS origin
# and set DJANGO_SECURE_SSL_REDIRECT=true. Do not use the tunnel-only settings publicly.
SECURE_HSTS_SECONDS=0
DB_NAME=worktrack
DB_HOST=<RDS-endpoint>
DB_PORT=5432
DB_SECRET_ARN=<CloudFormation-ApplicationDatabaseSecretArn-output>
DB_ADMIN_SECRET_ARN=<CloudFormation-DatabaseSecretArn-output>  # temporary; remove after provisioning
DB_SSLMODE=require
AWS_REGION=<AWS-region>
AWS_STORAGE_BUCKET_NAME=<CloudFormation-S3BucketName-output>
ATTENDANCE_LATE_AFTER=09:00
WORKTRACK_TRUSTED_PROXY_IPS=127.0.0.1/32,::1/128
WORKTRACK_KIOSK_IP_RANGES=
AWS_SES_FROM_EMAIL=
WORKTRACK_HR_EMAILS=
LEAVE_REMINDER_DAYS=3
```

The tunnel-only example sets `ALLOWED_HOSTS` and CSRF trusted origins to localhost and disables HTTPS redirection because the browser reaches the app through an SSH port-forward to Gunicorn on loopback. Remove public HTTP/HTTPS ingress from the EC2 security group while using this mode; do not expose the application over public HTTP. For a public deployment, configure a domain and TLS certificate (for example, Certbot with Nginx), use the real HTTPS origin in `DJANGO_CSRF_TRUSTED_ORIGINS`, set the actual hostnames in `DJANGO_ALLOWED_HOSTS`, and then set `DJANGO_SECURE_SSL_REDIRECT=true`. Do not transmit employee passwords or sensitive attachments over public HTTP. The S3 bucket remains private and uses short-lived signed URLs.

Production settings require a non-empty secret key, explicit allowed hosts, RDS connection details, an AWS Region, and an S3 bucket. The application database password is fetched from the application-user secret in AWS Secrets Manager using the EC2 instance role (`DB_SECRET_ARN`). The RDS master secret is separate and is used only by the one-time `provision_rds_app_user` command (`DB_ADMIN_SECRET_ARN`). No permanent AWS access key or database password belongs in the source code.

## 7. AWS deployment assets

### CloudFormation baseline

`infra/cloudformation/worktrack-aws-stack.yaml` provisions:

- A custom VPC with one public EC2 subnet and two private RDS subnets in separate Availability Zones.
- An Internet Gateway and public route table; private subnet route tables have no default Internet route.
- An S3 Gateway VPC Endpoint.
- An EC2 security group with HTTP/HTTPS from the internet and SSH only from the administrator CIDR supplied at stack creation.
- A PostgreSQL RDS security group allowing port 5432 only from the EC2 security group.
- A private encrypted/versioned S3 bucket with S3 Public Access Block and a deny-insecure-transport bucket policy.
- A private RDS PostgreSQL database with encrypted storage and a Secrets Manager-generated password.
- By default, an EC2 IAM role/instance profile scoped to the WorkTrack S3 bucket and database secret, plus Systems Manager access. For restricted Learner Labs, a parameter lets the stack use an existing instance profile instead of creating IAM resources; verify its permissions before deployment.
- An Ubuntu EC2 instance and Elastic IP.

Review the template and expected AWS charges before deployment. Resource availability, instance sizes, quotas, service permissions, and AWS Academy/Learner Lab restrictions depend on the group's AWS account and Region. Some student labs do not allow students to create IAM roles or arbitrary CloudFormation resources; in that case, use the lab's provided instance profile and document the exact permissions it grants rather than claiming the template's IAM role was created.

Example deployment for a personal AWS account (replace the sample values; `UseManagedIamRole` defaults to `true`):

```bash
aws cloudformation validate-template   --template-body file://infra/cloudformation/worktrack-aws-stack.yaml

aws cloudformation deploy   --template-file infra/cloudformation/worktrack-aws-stack.yaml   --stack-name worktrack-final-project   --capabilities CAPABILITY_NAMED_IAM   --parameter-overrides     AmiId=<Ubuntu-24.04-AMI-ID-for-your-region>     AdminCidr=<your-public-ip>/32     ProjectPrefix=worktrack \
    UseManagedIamRole=true EnableDatabaseProvisioning=true EnableSesNotifications=false
```

For a restricted Learner Lab that supplies an instance profile, pass `UseManagedIamRole=false ExistingInstanceProfileName=<lab-instance-profile-name-or-arn>`. The existing profile must already have the S3 and Secrets Manager permissions required by WorkTrack (and SSM permissions if Session Manager is used). In this mode, CloudFormation omits its IAM role, IAM policies, and instance profile. If the lab profile cannot be granted the required permissions, follow the lab's approved manual infrastructure/permission process and document the actual setup; do not claim WorkTrack's IAM role was created.

Read the stack outputs. Place the RDS endpoint, DB name, application database secret ARN, temporary master secret ARN, S3 bucket name, public DNS, and Elastic IP into the private EC2 environment file. The template creates separate `worktrack_admin` (master) and `worktrack_app` (application) credentials. The template does not create a GitHub repository or upload your application automatically.

### EC2 application deployment

1. Push the revised project to the group's GitHub repository. Use meaningful commits from all group members. Keep `.env`, credentials, private keys, SQLite DBs, virtual environments, and real uploaded files out of Git.
2. On EC2, create `/etc/worktrack/worktrack.env` from the demo or production example above. The deployment script sets owner `root`, group `www-data`, mode `0640`; this allows the `www-data` service/deploy process to read the file without making secrets world-readable.
3. Set `REPOSITORY_URL` to the actual GitHub clone URL and run the deployment script as an administrator, for example: `sudo env REPOSITORY_URL="https://github.com/<group>/<repository>.git" BRANCH=main bash deploy/aws/deploy_ec2.sh`. For a private repository, configure a deploy key or another approved Git credential method; do not put a personal access token in the command or repository. On the first run, while `DB_ADMIN_SECRET_ARN` is present and the EC2 instance profile can read it, the script provisions/updates the restricted `worktrack_app` login using the master secret, then applies migrations as the application user. It installs Python, Gunicorn, Nginx and the database client; installs dependencies; collects static files; sets the host timezone to `Asia/Manila`; and enables the systemd service. Gunicorn binds to `127.0.0.1:8000` with two workers; Nginx proxies to that loopback TCP address.
4. Create the IT Administrator account with Django's `createsuperuser` command. Create the initial HR account using `python manage.py create_hr_user --username hr.personnel --email hr@example.com --employee-id WT-HR-0001`. The command prompts for a temporary password and marks the account to change it on first sign-in. HR then creates employee and supervisor accounts in the application. Administrator cannot create or edit employee profiles. Create a separate superuser such as `worktrack-kiosk` for the shared kiosk laptop so a personal Administrator account is not left signed in.
5. After the first successful deployment, redeploy/update the CloudFormation stack with `EnableDatabaseProvisioning=false` to remove the EC2 role permission to retrieve the master secret, then remove `DB_ADMIN_SECRET_ARN` from `/etc/worktrack/worktrack.env`. The application continues using only `worktrack_app`. Configure HTTPS before enabling secure redirect and secure cookies. Verify `ALLOWED_HOSTS`, CSRF trusted origins, firewall rules, S3 access, and the RDS connection.

The deployment script expects the code to be pushed to a real Git repository and the EC2 environment file to exist. It does not supply the group's GitHub URL, domain, TLS certificate, or AWS account permissions.

For the follow-up CloudFormation update, retain the original values for other parameters and set `EnableDatabaseProvisioning=false`. This removes the temporary master-secret read permission from EC2. Keep the master secret in Secrets Manager for controlled administration and remove its ARN from the application's environment file.

### TLS setup

Before enabling HTTPS redirection, create an A record for the chosen domain pointing to the stack's Elastic IP, change `server_name _;` in `/etc/nginx/sites-available/worktrack` to the domain, install Certbot (`sudo apt-get install certbot python3-certbot-nginx`), and run `sudo certbot --nginx -d <your-domain>`. Verify HTTPS works, then set `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-domain>`, `DJANGO_SECURE_SSL_REDIRECT=true`, and restart `worktrack` and Nginx. Consider enabling HSTS only after confirming all application routes use HTTPS.

### SSH-tunnel camera demo

For the class kiosk without public HTTPS, use the documented port forward: `ssh -i <key.pem> -N -L 8000:127.0.0.1:8000 ubuntu@<EC2_PUBLIC_IP>`, then open `http://localhost:8000/accounts/attendance/kiosk/` on the kiosk laptop. For Session Manager, use the port-forwarding document described in `docs/demo-deployment-guide.md`. Keep SSH ingress limited to the administrator IP `/32`; update the security-group rule if that IP changes. The template already includes Systems Manager permissions when it creates the managed instance profile.

### Scheduled tasks and demo email

The deploy script sets the EC2 timezone to Manila, so the cron example runs on server-local Asia/Manila time and does not rely on `CRON_TZ`. For the demo, set `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`; inspect reset/notification messages with `sudo journalctl -u worktrack -f`. This is not real email delivery. Keep `EnableSesNotifications=false`.

## 8. Optional scheduled tasks and email

Use a scheduled job (for example, cron or a systemd timer) to run these commands in the virtual environment with the production environment loaded:

```bash
python manage.py generate_daily_attendance_qr
python manage.py mark_daily_absences
python manage.py send_pending_leave_reminders
```

Run `mark_daily_absences` after the workday ends or at the organization's chosen cutoff. It skips weekends, active holiday dates, and approved leave dates. Run reminder processing daily; successful reminders are rate-limited to once every 24 hours per application.

For this class demo, do not configure SES. Keep `EnableSesNotifications=false` and use the console email backend. This prints reset links and reminder messages to the service output but sends nothing externally. SES requires a verified sender identity and may remain in a sandbox that restricts recipients; enable it only for a separately approved setup.

## 9. Database and SQL deliverable

`sql/schema.sql` is a reviewable WorkTrack schema reference; its single leave catalogue exactly matches migration `0031` (VL, SL, EL, PL, LWOP) and is fixed in the UI. `sql/demo_data.sql` contains optional sample SQL after the `seed_worktrack_demo` command creates the fictional `DEMO-EMP-*` profiles. The ZIP does not include a pg_dump from a live RDS database because no deployed RDS connection or credentials were supplied. Run Django migrations as the authoritative schema-creation method. After deploying and seeding the group's own demo RDS database, export the actual schema and sanitized fictional app data:

```bash
# Schema export (include auth_user because WorkTrack profiles reference it)
pg_dump --schema-only --no-owner --no-privileges \
  --host "$DB_HOST" --username "$DB_USER" --dbname "$DB_NAME" \
  --table=auth_user --table='eqrApp_*' \
  > sql/rds_schema_actual.sql

# Data export only after using fictional demo accounts/records; review and sanitize it before committing.
pg_dump --data-only --no-owner --no-privileges \
  --host "$DB_HOST" --username "$DB_USER" --dbname "$DB_NAME" \
  --table=auth_user --table='eqrApp_*' \
  > sql/rds_demo_data_actual.sql
```

Do not put a production password on the command line or in shell history. Use a secure `.pgpass`, AWS Secrets Manager retrieval, or another approved credential mechanism. Add only sanitized sample data to the submitted SQL deliverable. Django's built-in `auth_*`, `django_*`, and `axes_*` tables are created by migrations and are not reproduced in the WorkTrack schema reference.

## 10. Tests and verification

Automated Django tests are in `eqrApp/tests.py`. For a clean local verification run, use `deploy/aws/verify_local.ps1` on Windows or `deploy/aws/verify_local.sh` on Linux/macOS. Each script creates a fresh `.venv`, installs `requirements.txt`, runs `python manage.py check`, `python manage.py makemigrations --check --dry-run`, the `eqrApp` tests using `django_employee_qr.test_settings`, and Python compilation. The test settings only replace manifest static storage with local static storage and use a faster test password hasher; they are not used by the deployed application.

The final deployment should also be tested manually with these cases:

- Login/logout and password reset for all four roles; for the class demo, verify reset links are printed to the console and visible in `journalctl -u worktrack` (no email is sent); verify new accounts are forced to change their temporary password and repeated failed logins trigger the username-based one-hour lockout.
- Verify Administrator can access system overview, sanitized warning/error logs, employee account support (username, name, and password only), and the protected QR kiosk; attendance and leave records remain read-only.
- Verify HR can hire/update/terminate employees and supervisors, process acknowledged leave requests, manage balances/holidays, and use the shared calendar; HR Company Attendance is removed and HR cannot operate the QR kiosk or edit attendance.
- Verify the standard leave catalogue is global and fixed in the application UI, with identical active categories for all employees.
- Administrator-only kiosk access; verify employee, supervisor and HR accounts receive HTTP 403 for both the kiosk page and scan endpoint.
- Employee and Supervisor daily QR display; confirm HR and Administrator role accounts do not receive employee QR codes.
- Submit a leave request with a valid document; verify the assigned supervisor/backup supervisor workflow and final HR approval.
- Configure a holiday and leave balance; verify working-day calculations, half-day requests, insufficient-balance rejection, and balance deduction only after final approval.
- Verify the first QR scan records check-in, the second records check-out, a third scan is rejected, and full-day approved leave blocks scanning. Verify Administrator manual-attendance and attendance-edit endpoints return HTTP 403 and do not change records.
- Verify HR and supervisors can monitor only their authorized attendance scope, while the kiosk accepts QR scans and verified Administrator entries. No role can manually edit attendance in this demo build.
- Upload and download a document through the application and verify the object exists in the private S3 bucket. Verify the URL expires and an unauthorized role cannot retrieve the document.
- Create/read/update/delete application data and verify corresponding records in RDS PostgreSQL.
- Present EC2, RDS, S3, VPC/subnets/route tables, security groups, IAM instance profile/policies, and the request path through the live AWS console.

A local check and test run does not prove AWS connectivity or production behavior. Deploy the stack, run the manual end-to-end scenarios in `docs/aws-live-demo-checklist.md`, and record the actual output and screenshots. Do not state that tests or AWS deployment passed unless they were run in the group's environment.

## 11. Privacy and security notes

Leave documents can contain medical certificates or other sensitive personal information. Restrict access by role, use private S3 storage and encryption, use HTTPS for public traffic, keep logs/audit data appropriately, configure backups and retention with the organization, and apply the Data Privacy Act of 2012 (Republic Act No. 10173) as applicable. File-signature validation is a baseline check, not malware scanning; no antivirus scan is implemented. The optional kiosk IP restriction depends on trusted reverse-proxy configuration. A daily QR is unchanged during the day and may be screenshotted/shared; it is not biometric identity verification. The current application also lacks an employee attendance correction-request workflow. See `docs/demo-limitations.md` for all class-demo limitations, including availability, monitoring, load testing, HTTP, privacy, and maintainability.

## 12. Repository and deliverable contents

- `django_employee_qr/` - Django settings, URLs, WSGI and production settings.
- `eqrApp/` - WorkTrack data models, forms, views, role checks, templates, tests and management commands.
- `infra/cloudformation/` - AWS infrastructure template.
- `deploy/aws/` - EC2 systemd, Nginx and deployment script.
- `sql/schema.sql` and `sql/demo_data.sql` - PostgreSQL schema reference, fixed leave catalogue and optional fictional sample SQL.
- `docs/demo-deployment-guide.md` - SSH tunnel, AWS account options, email, and demo data instructions.
- `docs/demo-limitations.md` - transparent presentation limitations.
- `docs/architecture.md` - application architecture, request workflow and ERD.
- `.env.example` - configuration example with placeholders only.

Retain the original Git commit history if the group already has a repository. This ZIP does not create Git commits or prove individual contributions. Add each member's actual task/commit information and actual AWS screenshots to the formal CCS4301 documentation.


## Marketing-company employee setup

Employee and supervisor profiles use fixed Department and Job Position dropdowns. Departments are HR, IT, Finance, Marketing, Administration, and Management. Job title options depend on the selected department. The department field displays a short system-usage description based on the supplied company reference: HR handles employee and leave operations; IT maintains the system; Finance views attendance summaries for payroll; Marketing monitors employee attendance and leave; Administration monitors office personnel and daily attendance; and Management views company-wide reports. These descriptions explain department responsibilities only. The WorkTrack access role remains a separate security field (Employee or Supervisor for HR-created accounts); a job title containing “Manager” does not grant elevated application permissions. Position labels retain the staffing counts from the reference where supplied (for example, Software Developer (3)); the saved job-title value excludes the count.

The employee/supervisor dashboard QR card polls a private, authenticated status endpoint and changes from “Not scanned yet” to “Check-in recorded” or “Check-in and check-out recorded” after the administrator-operated kiosk saves attendance. The endpoint exposes only the signed-in user's own attendance times and does not return QR tokens.

The account password fields include accessible Show/Hide controls. The kiosk remains a separate page protected by Administrator role checks on both the page and scan endpoint; other dashboards do not embed the scanner.


## Dedicated QR kiosk security

The QR kiosk is a standalone scanner page, separate from the Administrator dashboard. An Administrator opens **Activate QR Kiosk** from the system dashboard and must confirm the current Administrator password before WorkTrack activates kiosk mode. Once activated, server-side `KioskSessionLockMiddleware` keeps that same authenticated session on the kiosk routes: dashboard, employee, attendance, system log, password, and logout requests are redirected back to the scanner. The scan endpoint also requires the active kiosk session, Administrator role, CSRF protection, and the optional kiosk IP allowlist.

The scanner page has no visible exit control or dashboard navigation. To open the hidden settings, the activating Administrator presses **Ctrl+0** and re-enters their password. The settings panel provides camera selection, manual attendance by employee ID, and verified exit. Exit opens a second password-confirmation step for the same Administrator. Five failed verification attempts temporarily lock settings or exit for five minutes. Activation, settings unlocks, failed attempts, and exit events are written to the System Logs. The camera starts automatically when the authenticated scanner page loads.

**Browser/OS limitation:** Web application code cannot prevent a person from closing the browser, switching Windows applications, using browser chrome, or powering off the laptop. For a genuinely shared terminal, launch Chrome or Edge in the operating system's kiosk mode using a dedicated Windows kiosk account, and restrict the Windows account so it cannot access the desktop or other applications. The WorkTrack server-side lock remains the application-level security control; full-screen display alone is not a security boundary.


### Optional Windows kiosk-browser launcher

For the shared attendance laptop, see `deploy/kiosk/Start-WorkTrackKiosk.ps1` and `deploy/kiosk/README.md`. The launcher opens Chrome in kiosk display mode with a dedicated persistent browser profile. Use a separate standard Windows account and Windows Assigned Access for the stronger operating-system restriction. Chrome's `--kiosk` flag by itself does not prevent all OS-level navigation or application switching.


## Latest revision: scanner-only kiosk and consolidated workflows

The latest Demo Edition revision implements the uploaded `CHANGES (1).txt` and subsequent CHANGES v2 requirements alongside the marketing-company department structure. Search fields support username, employee name, employee ID, and other displayed fields where appropriate. Dropdown/date filters submit automatically. The Company Calendar is visible to Employee, Supervisor, and HR roles; it shows configured holidays and approved leave information according to role scope, while only HR can create, edit, or deactivate holidays. Attendance views use one date-specific table with Present, Late, Absent, and On Leave rows. Leave Requests combines pending approval queues, searchable/sortable history, the fixed leave catalogue in a collapsible section, and day-based leave balances. Leave entitlement numbers are demonstration defaults and must be checked against applicable law and the employer's actual policy before production use.

New kiosk behavior: on loading the standalone, Administrator-authenticated kiosk page, the ZXing scanner starts automatically. No manual QR-token input, Start/Stop buttons, Reduce Glare button, or visible exit button appears on the main scanner surface. The page is designed to fit one viewport with the camera/instructions and a recent attendance table; the log has its own internal scroll when it contains more rows. A large fixed top banner and a full-screen check/cross confirmation flash make success and failure visible immediately. The camera automatically requests continuous focus/exposure/white balance and applies a gentle negative exposure compensation when the hardware supports it. A faster scan loop runs at about 150 ms between frame attempts.

The hidden **Ctrl+0** settings panel opens for 10 minutes after Administrator password verification. Select **Manual attendance**, enter the employee ID, choose **Check in** or **Check out**, and select **Record attendance**. The server records the current time and the Administrator responsible.

Application-level kiosk navigation restrictions cannot stop a person from physically closing the browser or switching out to the desktop. Use Windows Assigned Access or an equivalent managed OS kiosk account for a genuinely shared terminal. Browser key interception is only a deterrent; the server-side kiosk session and role checks remain the application security boundary.


## Latest policy update: CHANGES v2

- HR accounts are role accounts and do not receive employee QR credentials. Only Employee and Supervisor profiles receive daily QR credentials.
- HR Company Attendance is removed; HR performs leave administration and employee lifecycle management.
- Employee hire dates cannot be in the future. Supervisor positions are restricted to the approved supervisor-title list, and employee reporting supervisors must be in the same department.
- A Supervisor can acknowledge an assigned employee leave request but cannot approve or reject it. HR can make the final decision only after acknowledgement.
- Leave balances are grouped by employee with name/employee-ID search; pending approvals and request history use separate search and filter controls.
- Administrator System Logs display warnings and errors only, with date and severity filters. The user interface suppresses employee identity and actor information.
- Administrator Employee Account Support can change only the account username, first/last name, and password. It cannot change roles, departments, positions, supervisor assignments, attendance, or leave records.
- Kiosk settings support camera selection, manual attendance by employee ID, and verified exit. Historical corrections remain disabled.
- The application layout uses responsive breakpoints and a resize-aware navigation layout for desktop, tablet, and mobile widths.


## CHANGES v2 policy update

The latest CHANGES v2 revision tightens the leave and administration rules:

- HR is a role account and never receives employee QR credentials or a Company Attendance module.
- Hire dates are validated against the current local date; Supervisor job titles are restricted to the eight configured titles, Employee titles use the remaining job-title catalogue, and employee supervisor choices are limited to the same department.
- Employee-role leave applications must have a Supervisor acknowledgment before HR can approve or decline them. Supervisors can acknowledge only; HR makes the final decision. Unacknowledged legacy employee requests remain in the supervisor queue even if their stored workflow status is already `pending_hr`.
- HR leave balances are grouped by employee in collapsible rows and searchable only by employee name or ID. Pending queues and request histories use separate search and filter parameters.
- Administrator system logs present only Warning and Error events using generic summaries; actor and employee identifiers, IP addresses, request paths, raw messages and status codes are not displayed.
- Administrator Account Support can change only an account's name, username and password. It cannot change department, position, access role, attendance or leave records.
- The attendance log is read-only. Administrators can record a current check-in or check-out in unlocked kiosk settings.
- The shared interface uses fluid CSS grids, responsive breakpoints, touch-friendly navigation and mobile table overflow handling.

Current kiosk policy permits manual attendance by employee ID in unlocked settings.


## CHANGES v2 verification status

Static checks in the build environment covered Python compilation and AST parsing, JavaScript syntax (including kiosk inline scripts), CSS brace balance, deployment shell syntax, and CloudFormation YAML parsing. Django is not installed in that environment, so `python manage.py check`, `makemigrations --check`, and the Django test suite were not run here. Run `deploy/aws/verify_local.ps1` on Windows or `deploy/aws/verify_local.sh` on Linux/macOS before using the build for a live demo. No live AWS deployment or webcam test is claimed.
