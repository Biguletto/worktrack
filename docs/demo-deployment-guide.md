# WorkTrack CCS4301 Demo Deployment Guide

This guide applies the Demo Edition changes. Use fictional employee data only. The ZIP contains application and infrastructure code; it does not prove that an AWS account, RDS database, EC2 instance, S3 bucket, HTTPS endpoint, or mail service has been deployed.

## 1. Choose the AWS account route

### Personal AWS account

Use the CloudFormation template with its default `UseManagedIamRole=true`. It creates the WorkTrack EC2 role, instance profile, scoped S3 access, application-secret access, and Systems Manager managed-instance policy. Deploy with `CAPABILITY_NAMED_IAM`.

### AWS Academy Learner Lab / restricted student account

Some labs prevent creation of IAM roles, policies, or instance profiles. Use the same template with:

- `UseManagedIamRole=false`
- `ExistingInstanceProfileName=<the name or ARN of the lab-provided instance profile>`

The template then omits the WorkTrack IAM role, IAM policies, and instance profile and attaches the existing profile to EC2. Before relying on this route, confirm that the existing profile already permits the required S3 object operations and Secrets Manager access. It should also permit Systems Manager if Session Manager will be used. If the provided profile lacks those permissions and the lab will not permit them, use the lab-approved manual infrastructure path and document the actual permissions; do not claim the template-created role exists.

The CloudFormation default keeps `EnableSesNotifications=false`. Leave it false for the class demonstration. In Learner Lab mode, also set `EnableDatabaseProvisioning=false`: the template deliberately does not create its temporary master-secret policy when it is not creating the managed role. Provision the restricted `worktrack_app` database login through the lab-approved/manual database process, leave `DB_ADMIN_SECRET_ARN` unset, and confirm the supplied instance profile can read the application secret and access the configured S3 bucket.

## 2. Budget and service guardrails

The revision list describes the AWS new-account Free Plan as starting with $100 in credits, with up to $100 more for onboarding, for up to six months or until credits are exhausted; it also notes that prior AWS account holders may not qualify. Treat those figures as the review document's assumption, not a guarantee: AWS plan terms and eligibility can change, so check the current Free Plan page and the account's Credits page before launching anything. AWS Academy Learner Lab is a separate route with different session and IAM limits. Create a low-value AWS Budget alert before deployment. Keep the template's small instance and 20 GB storage defaults unless the lab/account requires another permitted size. Do not add a NAT Gateway, load balancer, Multi-AZ database, extra Elastic IP, or other resources not needed for the demonstration. Stop EC2 and RDS between rehearsals; note that RDS may automatically restart after about seven days stopped, so check its state and billing. After grading, delete the stack and separately inspect retained S3 buckets, Secrets Manager secrets, final RDS snapshots, and Elastic IPs for remaining charges.

Secrets Manager is retained for the database-password/no-password-in-source-code design. A Secrets Manager secret may incur a monthly charge; check current regional pricing and the account's credits rather than calling it permanently free. Remove `DB_ADMIN_SECRET_ARN` and disable `EnableDatabaseProvisioning` after the one-time application database user has been provisioned.

## 3. SSH-tunnel camera setup for the kiosk laptop

The browser camera APIs require a secure context. `http://localhost` is treated as a secure context by current browsers, so use an SSH port-forward for the class kiosk when a public HTTPS hostname is not ready.

The EC2 service now runs Gunicorn on `127.0.0.1:8000`; the port is not exposed to the network. For tunnel mode, configure the EC2 environment file with:

```dotenv
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost,http://127.0.0.1
DJANGO_SECURE_SSL_REDIRECT=false
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

This is a temporary tunnel-only configuration. In the EC2 security group, remove public inbound HTTP (80) and HTTPS (443) rules while using this mode. Keep SSH port 22 restricted to the administrator's current public IP `/32`. Do not open Gunicorn port 8000 to the internet. The browser-to-EC2 application traffic is carried inside the SSH tunnel. Do not use this HTTP configuration for a public website or real employee data.

On the kiosk laptop, run (replace the key path and public EC2 DNS/IP):

```bash
ssh -i /path/to/worktrack-key.pem -N -L 8000:127.0.0.1:8000 ubuntu@<EC2_PUBLIC_IP>
```

Keep the terminal open. On that same laptop, open:

```text
http://localhost:8000/accounts/attendance/kiosk/
```

For the Session Manager route, when the EC2 role/lab profile and account support it, use AWS CLI port forwarding:

```bash
aws ssm start-session \
  --target <EC2_INSTANCE_ID> \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8000"],"localPortNumber":["8000"]}'
```

Then open the same `http://localhost:8000/...` URL. Session Manager requires the SSM agent, a suitable instance profile, AWS CLI credentials, and the Session Manager plugin. If those prerequisites are unavailable, use the SSH tunnel and the SSH rule restricted to the administrator CIDR.

For a normal public deployment, configure a domain and HTTPS with Certbot, then set `DJANGO_ALLOWED_HOSTS` to the real hostnames, `DJANGO_CSRF_TRUSTED_ORIGINS=https://<domain>`, and `DJANGO_SECURE_SSL_REDIRECT=true`. Do not keep the tunnel-only HTTP settings for a publicly reachable site.

In the kiosk, press **Ctrl+0**, enter the activating Administrator’s password, and open **Manual attendance**. Enter the employee ID, choose **Check in** or **Check out**, and select **Record attendance**. WorkTrack records the current time and the Administrator responsible.

## 4. Dedicated kiosk Administrator account

Do not leave a personal Administrator session signed in on a shared classroom kiosk. Create a separate superuser used only for the kiosk laptop. Run the command with the production environment loaded so it targets the RDS-backed database:

```bash
sudo -u www-data bash -c 'cd /opt/worktrack/app && set -a && . /etc/worktrack/worktrack.env && set +a && /opt/worktrack/venv/bin/python manage.py createsuperuser --username worktrack-kiosk'
```

Use a unique password, do not save it in the repository, and sign out when the kiosk is unattended. Django superusers are treated as Administrators by WorkTrack. If the application environment or database is not ready, create the account only after migrations have completed.

## 5. Demo records

After migrations, create fictional demo users and records:

```bash
python manage.py seed_worktrack_demo
```

The command prompts for one initial password and applies it only to newly created accounts. Demo usernames are `demo.admin`, `demo.hr`, `demo.supervisor`, `demo.employee001`, and `demo.employee002`. Existing demo-account passwords are not overwritten. It creates the `DEMO-*` employee profiles, future holidays, leave requests, balances, today's attendance rows, and daily QR rows. The command refuses to seed when `DEBUG=False` unless the operator explicitly adds `--allow-production` and confirms the action. Use that override only on a disposable/class-demo database containing fictional data.

`sql/demo_data.sql` contains additional optional SQL sample rows for the seeded `DEMO-EMP-*` profiles. They are not a pg_dump from a live RDS database. Run migrations first; then use the command above if sample data is needed.

## 6. Host timezone and scheduled commands

The EC2 deploy script runs:

```bash
sudo timedatectl set-timezone Asia/Manila
```

Cron entries in `deploy/aws/worktrack-daily-jobs.example` therefore use the server's local Manila time; they do not depend on a `CRON_TZ` crontab extension. During a presentation, the operator may run the following commands manually after loading `/etc/worktrack/worktrack.env`:

```bash
python manage.py generate_daily_attendance_qr
python manage.py mark_daily_absences
python manage.py send_pending_leave_reminders
```

The QR task is normally scheduled at 12:00 AM. Run absence generation only after the configured workday cutoff, and reminders according to the class demo schedule.

## 7. Email and ZXing CDN

The demo environment uses `django.core.mail.backends.console.EmailBackend`. It does not deliver real email. Password-reset links and notification messages are written to the WorkTrack service output; inspect them with:

```bash
sudo journalctl -u worktrack -f
```

Do not enable SES for the class demo. SES remains disabled in CloudFormation by default; SES has its own verification/sandbox requirements and can introduce cost.

The kiosk loads the pinned ZXing browser bundle from jsDelivr with an unpkg fallback. Confirm the classroom network allows both hosts from the kiosk browser before demo day:

```bash
curl -I https://cdn.jsdelivr.net/npm/@zxing/browser@0.2.1/umd/zxing-browser.min.js
curl -I https://unpkg.com/@zxing/browser@0.2.1
```

If both CDNs are blocked, the camera scanner cannot start until the classroom network permits the pinned ZXing CDN or the script is packaged locally. There is no manual attendance or plain-token fallback under the current policy; resolve the camera/network issue before the demonstration and retain a separate backup kiosk device.

## 8. SSH and administrator IP changes

The CloudFormation security group limits SSH ingress to the `AdminCidr` parameter supplied at deployment. If the administrator's public IP changes, update the security-group SSH rule to the new public IP `/32`; do not use `0.0.0.0/0`. If Session Manager is available and correctly configured, it can avoid inbound SSH entirely.

## 9. Local verification and evidence

On Windows PowerShell, run from the folder containing `manage.py`:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\aws\verify_local.ps1
```

On Linux/macOS:

```bash
bash deploy/aws/verify_local.sh
```

The scripts create a clean `.venv`, install `requirements.txt`, run `manage.py check`, `makemigrations --check --dry-run`, the `eqrApp` test suite with test-only static storage settings, and Python compilation. Record the actual output. A clean local run does not prove AWS deployment or RDS/S3/SES integration.

Capture real console screenshots only from the group's own AWS account and application. Keep an offline copy of screenshots, sample accounts, and a tested backup kiosk device ready. Use Administrator kiosk settings for manual attendance if needed. Do not fabricate resource IDs, test results, or deployment status.
