# WorkTrack AWS Live Demonstration Checklist

Use this list only after the group has deployed the application in its own AWS account. Take screenshots from the group's own AWS Management Console and running application; do not use generic tutorial screenshots.

## Application and role workflow

- [ ] Open the actual EC2-backed application URL/domain.
- [ ] Sign in separately as Employee, Supervisor, HR Personnel and Administrator.
- [ ] Use a dedicated kiosk Administrator account on the shared kiosk laptop; do not leave a personal account signed in.
- [ ] Create fictional demonstration records with `python manage.py seed_worktrack_demo` (never use real personal or medical data in the class demo).
- [ ] Demonstrate first-login password replacement for a newly provisioned user.
- [ ] Create an employee account and show its profile row in RDS.
- [ ] Create, view, update and delete an eligible record; explain why cancelled/rejected leave records are deletable while approved records are retained.
- [ ] Submit a leave request with a supporting PDF/JPG/PNG document.
- [ ] Demonstrate supervisor or backup-supervisor review, then HR's final decision.
- [ ] Show working-day calculation, half-day leave, holiday exclusion and configured balance validation.
- [ ] Demonstrate employee/supervisor daily QR issuance, kiosk check-in/check-out, and confirm Administrator attendance views remain read-only.
- [ ] Confirm the kiosk attendance table updates immediately from each successful scan without a page refresh; confirm the scanner automatically rearms for another employee.
- [ ] Verify that an Administrator can record attendance by employee ID in unlocked kiosk settings if camera scanning is unavailable.
- [ ] Explain that the QR stays the same for the Manila day and may be shared; Administrator visually checks the person presenting it.
- [ ] Verify the kiosk denies access to Employee, Supervisor, and HR accounts and accepts only Administrator access.
- [ ] Verify the QR issued before midnight is rejected after midnight (Asia/Manila).
- [ ] Download an authorized document and confirm an unauthorized role cannot access it.
- [ ] Export a monthly attendance CSV.

## Kiosk camera and network preparation

- [ ] Confirm the classroom network can reach the pinned ZXing jsDelivr URL and the unpkg fallback; verify camera auto-start and the Administrator-only camera-device selection/restart controls in hidden settings.
- [ ] Use an SSH tunnel or Session Manager port forward and open the kiosk as `http://localhost:8000/accounts/attendance/kiosk/` on the kiosk laptop.
- [ ] Do not open Gunicorn port 8000 to the network. For tunnel-only demo mode, remove public HTTP/HTTPS ingress from the EC2 security group and keep SSH restricted to the administrator's current public IP `/32`.
- [ ] Confirm `DJANGO_ALLOWED_HOSTS` includes `localhost,127.0.0.1`, `DJANGO_CSRF_TRUSTED_ORIGINS` includes `http://localhost,http://127.0.0.1`, and `DJANGO_SECURE_SSL_REDIRECT=false` only for tunnel-only mode.
- [ ] Confirm `worktrack.service` uses two Gunicorn workers bound to `127.0.0.1:8000`, Nginx proxies to that address, and `/etc/worktrack/worktrack.env` is `root:www-data` mode `0640`.
- [ ] Confirm EC2 timezone is `Asia/Manila`; manually demonstrate scheduled QR/absence/reminder commands if the cron schedule is not active.
- [ ] Confirm email backend is console and show the relevant service output with `journalctl -u worktrack`; no real email should be expected.

## Amazon RDS

- [ ] Show the actual RDS PostgreSQL instance, engine/version, endpoint and private-network configuration.
- [ ] Show the `eqrApp_*` WorkTrack tables and sanitized records.
- [ ] Create/update/delete a record through WorkTrack and verify the corresponding RDS row.
- [ ] Run or display the sanitized SQL schema and CRUD query examples.

## Amazon S3

- [ ] Show the private bucket, Block Public Access, encryption and versioning settings.
- [ ] Upload a leave document through WorkTrack and show the key under `leave-documents/`.
- [ ] Generate a monthly report and show the key under `worktrack-reports/`.
- [ ] Retrieve the file through the permission-checked application link and explain the short-lived signed URL.
- [ ] Do not paste signed URLs, credentials or secrets into the report.

## EC2, VPC, security groups and IAM

- [ ] Show the EC2 instance, Elastic IP, Ubuntu OS and running `worktrack.service` / Nginx.
- [ ] Show the custom VPC, public EC2 subnet, two private RDS subnets and route-table associations.
- [ ] Show the public route to the Internet Gateway and the absence of a public default route on the RDS private subnets.
- [ ] Show the S3 Gateway VPC Endpoint.
- [ ] Explain EC2 security group rules: for a public TLS deployment, HTTP/HTTPS are open as configured and SSH is limited to the administrator CIDR; for the SSH-tunnel-only demo, remove public HTTP/HTTPS ingress and keep SSH limited to the administrator CIDR.
- [ ] Explain RDS security group rules: PostgreSQL only from the EC2 security group.
- [ ] Show the EC2 instance profile and the least-privilege S3/Secrets Manager policy if the personal-account CloudFormation role was created. For Learner Lab, show the actual provided instance profile and do not claim the template created a role.
- [ ] Confirm port 22 is limited to the administrator's current IP `/32`; update the rule if that IP changes, or use Session Manager where available.
- [ ] Explain that the database password is retrieved from Secrets Manager and no long-lived AWS access key is embedded in the application.

## Demo limitations to disclose

- [ ] State that the QR is daily rather than rotating every 30-60 seconds and may be screenshotted/shared.
- [ ] State that employees do not yet have an in-app attendance correction request workflow.
- [ ] State that the leave catalogue has five fixed starter categories and statutory leave/policy entitlements are not fully modeled.
- [ ] State that the architecture has no failover, automated CloudWatch alarms, log-retention policy, antivirus scan, or load/performance test.
- [ ] State that plain HTTP is for dummy-data/tunnel demonstration only; production needs HTTPS.
- [ ] State that data is fictional and privacy/retention review is required before real employee information is used.
- [ ] State that a username-only failed-login lockout can temporarily lock a known username for one hour.
- [ ] State that `views.py` remains a large module scheduled for future refactoring.

## Evidence to insert in the final documentation

Capture actual, readable screenshots with figure numbers and short captions for the deployed UI, RDS instance/tables, S3 objects/configuration, EC2, VPC/subnets/route tables, security groups, IAM role/policy, and the end-to-end create-record/upload-file integration. Add the real application URL, selected AWS Region, resource identifiers (excluding secrets), test date, test results, and actual member contributions. A completed checkbox is not evidence by itself; attach the corresponding screenshot or live demonstration result.



## Cost and cleanup guardrails

- [ ] Check the account's current Free Plan/Free Tier eligibility and Credits page; do not describe the deployment as permanently free.
- [ ] Create a low-value AWS Budget alert before provisioning.
- [ ] Keep the small instance/storage defaults and avoid NAT Gateways, load balancers, Multi-AZ, extra Elastic IPs, or other unneeded services.
- [ ] Stop EC2 and RDS between rehearsals and confirm whether RDS has automatically restarted.
- [ ] After grading, delete the stack and inspect retained S3 buckets, Secrets Manager secrets, final RDS snapshots, and Elastic IPs for ongoing charges.
