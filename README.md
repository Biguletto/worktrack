# WorkTrack – Employee Leave and Attendance Management System

WorkTrack is a role-based web information system that keeps an organization's employee accounts, daily attendance and leave applications in one place. Employees check in and out by showing a signed daily QR code at an Administrator-operated kiosk, submit leave requests with supporting documents, and follow each request from supervisor acknowledgment to the final HR decision.

WorkTrack was built for the **CCS4301 Cloud Computing** final project (Project Option 8, Employee Leave and Attendance Management System) and is deployed as an integrated cloud application on Amazon Web Services: Django runs on **Amazon EC2**, records are stored in **Amazon RDS for PostgreSQL**, documents and reports are stored in **Amazon S3**, the network is isolated in an **Amazon VPC** with security groups, and permissions are granted through an **AWS IAM** role.

**Live application:** https://56-10-45-11.sslip.io  (deployed 26 November 2026 in the Asia Pacific (Singapore) Region, `ap-southeast-1`)

![WorkTrack architecture on AWS](docs/screenshots/00-architecture.png)

## Contents

1. [Objectives](#1-objectives)
2. [Users and features](#2-users-and-features)
3. [Main workflows](#3-main-workflows)
4. [Technologies used](#4-technologies-used)
5. [Database](#5-database)
6. [AWS services implemented](#6-aws-services-implemented)
7. [Running WorkTrack locally](#7-running-worktrack-locally)
8. [Deploying to AWS](#8-deploying-to-aws)
9. [Testing](#9-testing)
10. [Repository structure](#10-repository-structure)
11. [Screenshots](#11-screenshots)
12. [Group members](#12-group-members)
13. [Security notes](#13-security-notes)

## 1. Objectives

**General objective:** to design, develop and deploy a secure web-based Employee Leave and Attendance Management System on AWS that integrates a Django application on EC2, a PostgreSQL database on RDS, private file storage on S3, network isolation through a VPC and security groups, and permission control through IAM.

Specific objectives:

- Provide role-specific dashboards, navigation, data entry forms, listing pages and view, edit and delete functions that work on laptops and phones.
- Manage accounts for four roles (Employee, Supervisor, HR Personnel, Administrator) with secure sign-in, forced password change, account lockout and role-based access.
- Implement a two-stage leave workflow: the supervisor acknowledges, then only HR approves or rejects, with automatic working-day and balance computation.
- Record attendance with signed daily QR codes scanned at an Administrator kiosk, with manual entry and audited corrections.
- Store all records in a normalized relational database on Amazon RDS and demonstrate CREATE, INSERT, SELECT, UPDATE, DELETE and JOIN operations.
- Keep leave documents and reports private in Amazon S3 and give access only through short-lived signed links.
- Deploy on EC2 inside a custom VPC with least-privilege security groups and an IAM role instead of stored access keys, within the AWS Free plan credits.

## 2. Users and features

| Role | Main features |
|---|---|
| **Employee** | Dashboard with today's QR code and attendance status; own attendance history; apply for leave (seven leave types, half-day option, PDF/JPG/PNG attachments up to 5 MB); track request status; cancel pending requests and delete cancelled or rejected ones; view own leave balances. |
| **Supervisor** | All Employee features; view the attendance and leave requests of assigned team members; acknowledge team leave requests so they go to HR (supervisors cannot approve or reject). |
| **HR Personnel** | Create and edit Employee and Supervisor accounts (WorkTrack generates a random one-time temporary password); assign department, access role, job position and supervisor; change employment status; approve or reject acknowledged leave; view company leave balances; maintain the holiday calendar. |
| **Administrator (IT)** | Activate and run the secured QR attendance kiosk; manual attendance, audited corrections with a before-and-after preview, and a read-only correction history (Ctrl+0 settings); read-only attendance logs and monthly CSV export to S3; warning and error system logs; account support (name, username, password reset, unlock a locked account). |

Other features:

- Attendance days without a record are labeled **Rest Day** (weekends), **Holiday** (active holidays) or **Not Yet Scanned** (today) instead of Absent.
- An account is locked for one hour after five failed sign-ins; the lock applies to that username only.
- Every page gives success, warning or error feedback, and every view checks the user's role on the server (403 Forbidden otherwise).
- Responsive layout with a collapsible menu for phones.

## 3. Main workflows

**Leave application and approval**

1. An Employee (who must have an assigned supervisor) or a Supervisor submits a request; files are uploaded to S3 under `leave-documents/<employee ID>/<year>/<month>/`.
2. Status *Awaiting Supervisor Acknowledgment* → the assigned supervisor acknowledges → *Pending HR Approval*. A Supervisor's own request goes to their manager if one is assigned, otherwise directly to HR.
3. HR approves or rejects. Approval deducts the working days (weekdays that are not holidays) from the leave balance and marks the days *On Leave* in attendance, in one database transaction.

**QR attendance**

1. Each day every active Employee and Supervisor receives a QR code signed with the server's secret key (profile, date and random nonce).
2. The Administrator activates the kiosk with their password; the session is then locked to the scanner.
3. The first valid scan records check-in (Late after 9:00 AM), the next records check-out; a repeat scan within 10 seconds is ignored.
4. Mistakes are fixed in the password-protected kiosk settings; every correction is stored in an audit table with the Administrator and reason.

## 4. Technologies used

| Category | Technology |
|---|---|
| Languages | Python, HTML5, CSS3, JavaScript, SQL, YAML, Bash |
| Framework | Django 5.2 (Model–View–Template) |
| Web and application server | Nginx 1.24 (HTTPS reverse proxy), Gunicorn (2 workers) |
| Database | PostgreSQL 18.3 on Amazon RDS (production); SQLite (local development) |
| Main libraries | psycopg 3, boto3, django-storages (S3), django-axes (lockout), qrcode and Pillow, whitenoise, ZXing browser 0.2.1 (kiosk camera scanning) |
| Hosting OS | Ubuntu Server 24.04 LTS on Amazon EC2 |
| HTTPS | Let's Encrypt certificate obtained with Certbot for 56-10-45-11.sslip.io |
| Tools | Visual Studio Code, Git, GitHub, Google Chrome |

## 5. Database

WorkTrack uses a relational database on **Amazon RDS for PostgreSQL** (`worktrack-db`, database `worktrack`). The application connects as the restricted user `worktrack_app` over SSL; its password is read from AWS Secrets Manager at start-up.

Main tables (Django's `auth_user` plus twelve WorkTrack tables):

| Table | Purpose |
|---|---|
| `eqrApp_employeeprofile` | Employee ID, role, department, position, hire date, supervisor, status (1:1 with `auth_user`) |
| `eqrApp_leavetype` | Fixed catalogue: SIL, MAT, PAT, VL, SL, EL, BL |
| `eqrApp_leavebalance` | Entitled and used days per employee, leave type and year |
| `eqrApp_leaveapplication` | Leave requests with status and reviewer columns |
| `eqrApp_leavedocument` | S3 object key of each attachment |
| `eqrApp_leaveaction` | History of submissions, acknowledgments, decisions and cancellations |
| `eqrApp_leavedeletionaudit` | Summary kept for every deleted request |
| `eqrApp_attendancerecord` | One record per employee per day (check-in, check-out, status, source) |
| `eqrApp_dailyattendanceqr` | One QR nonce per employee per day |
| `eqrApp_attendanceaudit` | Before-and-after values of every scan and correction |
| `eqrApp_holiday` | Company holiday calendar |
| `eqrApp_systemeventlog` | Warning and error events |

Integrity rules include foreign keys, unique constraints (one attendance record and one QR per employee per day, one balance per employee/type/year) and check constraints (`leave_end_on_or_after_start`, `half_day_leave_single_date`, `attendance_checkout_not_before_checkin`, `leave_balance_used_not_over_entitlement`).

SQL files:

- [`sql/schema.sql`](sql/schema.sql) – table definitions, keys, constraints, indexes and the leave catalogue.
- [`sql/demo_data.sql`](sql/demo_data.sql) – fictional sample records.

The schema is created on RDS with `python manage.py migrate` (migrations 0001–0035).

## 6. AWS services implemented

All resources are defined in [`infra/cloudformation/worktrack-aws-stack.yaml`](infra/cloudformation/worktrack-aws-stack.yaml) and were created as the CloudFormation stack `worktrack` (27 resources).

| Service | How WorkTrack uses it |
|---|---|
| **Amazon EC2** | `worktrack-web` (t3.micro, Ubuntu 24.04, Elastic IP 56.10.45.11) runs Nginx → Gunicorn → Django as the `worktrack` systemd service. IMDSv2 required. |
| **Amazon RDS** | `worktrack-db` (PostgreSQL 18.3, db.t3.micro, 20 GiB encrypted gp3, single-AZ), not publicly accessible, SSL required. |
| **Amazon S3** | Private bucket `worktrack-uploadsbucket-scpmyxbl9lx0`: Block Public Access on, versioning, SSE-S3 encryption, HTTPS-only bucket policy. Folders `leave-documents/` and `worktrack-reports/attendance/`. Downloads use pre-signed URLs valid for 5 minutes. |
| **Amazon VPC** | `worktrack-vpc` 10.24.0.0/16 with one public subnet (10.24.1.0/24) for EC2, two private subnets (10.24.11.0/24, 10.24.12.0/24) for RDS, an Internet Gateway, route tables (no internet route in the private subnets) and an S3 Gateway Endpoint. |
| **Security groups** | EC2: 80 and 443 from anywhere, 22 from the administrator's IP only. RDS: 5432 only from the EC2 security group. |
| **AWS IAM** | EC2 instance role with `AmazonSSMManagedInstanceCore` and an inline least-privilege policy (S3 access to the two folders only, read of the application database secret only). No access keys are stored anywhere. |
| **AWS Secrets Manager** | Generated master and application database passwords. |
| **Systems Manager Session Manager** | Browser terminal to the server without opening SSH. |
| **AWS Budgets** | Cost alert to stay within the Free plan credits. |

![Deployed network](docs/screenshots/09-aws-network.png)

## 7. Running WorkTrack locally

Requirements: Python 3.12 or newer and Git.

```bash
git clone https://github.com/Biguletto/worktrack.git
cd worktrack
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # Windows   (macOS/Linux: cp .env.example .env)
python manage.py migrate
python manage.py seed_worktrack_demo      # optional fictional demo accounts and records
python manage.py createsuperuser          # first Administrator
python manage.py runserver
```

Open http://127.0.0.1:8000/. On Windows, `Start-WorkTrack.cmd` does the same and starts the server on http://127.0.0.1:8765. The local setup uses SQLite and local files instead of RDS and S3. Set a long random `SECRET_KEY` in `.env`; never commit `.env`.

Useful commands:

| Command | Purpose |
|---|---|
| `python manage.py create_hr_user` | Create the first HR account |
| `python manage.py generate_daily_attendance_qr` | Pre-create today's QR codes (scheduled daily at midnight) |
| `python manage.py mark_daily_absences` | Mark absences after working hours (scheduled) |
| `python manage.py send_pending_leave_reminders` | Remind reviewers about old pending requests (scheduled) |

## 8. Deploying to AWS

1. **Create the infrastructure.** In AWS CloudFormation (Region ap-southeast-1), create a stack from `infra/cloudformation/worktrack-aws-stack.yaml`, giving your public IP (/32) for SSH and an EC2 key pair. Wait for `CREATE_COMPLETE` and note the Outputs (Elastic IP, RDS endpoint, bucket name, secret ARNs).
2. **Configure the server.** Connect with Session Manager and create `/etc/worktrack/worktrack.env` (owner `root:www-data`, mode `0640`) with `DJANGO_SETTINGS_MODULE=django_employee_qr.production_settings`, the allowed hosts, the RDS endpoint, `DB_SECRET_ARN`, the bucket name, the Region and a random `SECRET_KEY`. No passwords go in this file.
3. **Install WorkTrack.** Run `deploy/aws/deploy_ec2.sh`. It installs Python, Nginx and the PostgreSQL client, clones this repository to `/opt/worktrack/app`, creates the virtual environment, creates the restricted `worktrack_app` database user, runs the migrations, collects static files and starts `worktrack.service` and Nginx.
4. **Enable HTTPS.** Run Certbot for the sslip.io host name and set `DJANGO_SECURE_SSL_REDIRECT=true`.
5. **Harden.** Remove the temporary master-secret setting and the temporary IAM provisioning policy.

Deploying a later commit:

```bash
sudo -u www-data git -C /opt/worktrack/app pull --ff-only origin main &&
sudo systemctl restart worktrack &&
sudo systemctl is-active worktrack
```

More detail: [`docs/demo-deployment-guide.md`](docs/demo-deployment-guide.md) and [`docs/aws-live-demo-checklist.md`](docs/aws-live-demo-checklist.md).

## 9. Testing

```bash
.venv\Scripts\python.exe manage.py test eqrApp --settings=django_employee_qr.test_settings
```

90 automated tests cover role permissions, the leave workflow, hire-date and department rules, QR check-in/check-out and duplicate scans, simultaneous approvals and submissions, attendance corrections and history, attendance labels, lockout and unlocking, temporary passwords, document validation and system logs. All 90 pass. In addition, 52 manual functional, database, storage, network/security and integration test cases were run on the deployed system on 26 November 2026, all passing (see the project documentation, Chapter 6).

## 10. Repository structure

```text
worktrack/
├── README.md
├── manage.py, requirements.txt, .env.example, Start-WorkTrack.cmd, build.sh
├── django_employee_qr/      settings.py, production_settings.py, test_settings.py, urls.py, wsgi.py
├── eqrApp/                  models, views, forms, urls, roles, middleware, attendance QR signing,
│   ├── management/commands/ create_hr_user, seed_worktrack_demo, provision_rds_app_user, daily jobs
│   ├── migrations/          0001–0035
│   ├── templates/, static/  pages, stylesheet and scripts
│   └── tests.py             automated tests
├── deploy/aws/              deploy_ec2.sh, nginx-worktrack.conf, worktrack.service, daily jobs
├── infra/cloudformation/    worktrack-aws-stack.yaml
├── sql/                     schema.sql, demo_data.sql
└── docs/                    guides, revision history and screenshots
```

## 11. Screenshots

| | |
|---|---|
| ![Login](docs/screenshots/01-login.png) Login | ![Employee dashboard](docs/screenshots/02-employee-dashboard.png) Employee dashboard with daily QR |
| ![Leave application](docs/screenshots/03-leave-application.png) Leave application | ![Supervisor acknowledgment](docs/screenshots/04-supervisor-acknowledgment.png) Supervisor acknowledgment |
| ![HR approval](docs/screenshots/05-hr-approval.png) HR approval | ![QR kiosk](docs/screenshots/06-qr-kiosk-scan.png) QR kiosk scan |
| ![Administrator dashboard](docs/screenshots/07-admin-dashboard.png) Administrator dashboard | ![Account support](docs/screenshots/08-account-support.png) Account support with sign-in lock |

## 12. Group members

| Member | GitHub | Contribution |
|---|---|---|
| Francios Deo A. Garabato | [Mikazuki40](https://github.com/Mikazuki40) | Lead developer of the original application (shared through Google Drive and uploaded in the initial commit) |
| John Clarence G. Arellano | [Biguletto](https://github.com/Biguletto) | Repository owner, AWS deployment, lockout fix and audited attendance corrections, documentation |
| Elyssa Jay G. Alviz | [00kanae](https://github.com/00kanae) | Bug fixes: attendance labels, supervisor deactivation guard, lockout reset, temporary passwords |
| Casey Karsten B. Labios | [coding-programming-s](https://github.com/coding-programming-s) | Correction preview, correction history, account unlock |
| Rency Nathaniel M. Bitbit | — | Quality assurance and testing; application workflow decisions |

## 13. Security notes

- No AWS access keys, passwords, database credentials or private keys are stored in this repository. `.env`, `db.sqlite3`, uploaded files and keys are excluded by `.gitignore`.
- The EC2 instance gets temporary credentials from its IAM role; the database password is read from AWS Secrets Manager.
- All demonstration accounts and records are fictional.
- Known limitations (daily QR can be screenshotted, single-AZ database, console email backend, no payroll) are listed in [`docs/demo-limitations.md`](docs/demo-limitations.md).
