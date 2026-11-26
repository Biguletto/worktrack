> **Revision history.** For current kiosk procedures, see the [kiosk operator guide](kiosk-operator-guide.md). Administrators can enter punches, correct times or daily status, and delete mistaken records inside the password-protected Ctrl+0 settings.

# WorkTrack Revision Summary - Architecture-Aligned Build

## Scope

This build aligns the WorkTrack application with the supplied `SYSARCH.drawio` architecture and the later CHANGES v2 policy. It retains the signed daily QR workflow and Administrator-operated standalone kiosk, but disables manual attendance entry and attendance corrections because the current policy makes attendance records read-only for Administrator.

## Role and dashboard changes

- **Employee:** The main dashboard shows the employee's daily QR and personal attendance status. The Leave Requests module contains both the request history and the action to submit a leave application; there is no separate Leave Application sidebar item.
- **Supervisor:** The dashboard includes the supervisor's daily QR and team summaries. Team Attendance and Team Leave Requests are limited to assigned primary/backup reports and the supervisor's own self-service records. Team Leave Approvals contains requests assigned to that supervisor for acknowledgement only; supervisors cannot approve or decline.
- **HR Personnel:** HR owns employee/supervisor account creation, editing and employment-status changes; HR has no Company Attendance page; HR owns the final leave decision after Supervisor acknowledgement, balances and holiday calendar. HR can view the shared standard leave catalogue but cannot modify it in the application.
- **Administrator (IT Personnel):** The dashboard is restricted to system overview, sanitized warning/error logs, employee account support limited to username/name/password resets, and the secured QR kiosk. Attendance and leave records are read-only. HR employee lifecycle and leave decisions are not available to Administrator.

## HR account provisioning and access controls

- The app's Administrator role cannot access employee account CRUD pages, leave balances, holiday management or leave-type configuration. Direct URL access is denied, not merely hidden from the sidebar.
- HR is the only application role that can create/update Employee and Supervisor accounts and change their employment status. HR cannot create another HR or Administrator account.
- The initial IT Administrator is created with `python manage.py createsuperuser`. The initial HR Personnel user is provisioned from the command line with `python manage.py create_hr_user`; the command prompts for and validates a temporary password, creates an HR profile in the fixed HR department with the HR Manager job title, and forces a password change on first login. For the shared demonstration kiosk, create a separate Administrator superuser used only on that laptop.
- The Django `/admin/` route is not exposed as a second unrestricted business-data console.
- Employee and Supervisor leave submissions are accessed from their Leave Requests module. HR and Administrator cannot submit a leave application through the employee-facing endpoint.

## Leave catalogue and calendar

- Migration `0031_system_event_log_and_fixed_leave_catalogue` installs the shared starter categories `VL` Vacation Leave, `SL` Sick Leave, `EL` Emergency Leave, `PL` Personal Leave, and `LWOP` Leave Without Pay.
- Non-standard catalogue rows already in the database are deactivated, not deleted, to preserve historical application references. New leave applications can select only active rows from the fixed catalogue. The starter paid/balance flags are technical defaults and must be confirmed against the employer's policy before production use.
- HR manages the month-grid Holiday Calendar. The existing application does not contain a separate Event model or event-registration workflow, so the architecture's calendar-app note is applied to Holidays only.

## IT event handling and password recovery

- Added `SystemEventLog` and `SystemEventLoggingMiddleware`. Selected HTTP errors/access-denied responses, successful/failed logins and logouts are visible on an Administrator-only System Logs page.
- Logs store a sanitized event summary, actor, route, HTTP method/status, severity, timestamp and optional client IP. They do not store passwords, request bodies or signed QR tokens.
- Client IP headers are trusted only when the immediate peer belongs to `WORKTRACK_TRUSTED_PROXY_IPS`. The included same-host Nginx/Gunicorn configuration defaults this to loopback. Kiosk network restriction remains separately controlled by `WORKTRACK_KIOSK_IP_RANGES`.
- Added Forgot Password / password-reset views and templates. Reset links expire after one hour. Local development uses console email by default; production requires an SMTP provider configuration such as Amazon SES SMTP credentials.

## QR attendance controls retained

- Employee and Supervisor profiles receive their own signed daily QR code, generated per employee and Asia/Manila date and rotated at midnight. HR and Administrator are role accounts and do not receive QR credentials.
- The Administrator-operated laptop kiosk scans the code. The first accepted scan records check-in and the next accepted scan of that employee’s daily code records check-out; duplicate video frames are suppressed and scans after check-out are rejected. The kiosk page and scan endpoint require Administrator authentication; an optional network allow-list can further restrict access.
- Attendance logs are grouped by employee, not mixed by timestamp. The kiosk includes today's attendance log panel.
- Supervisors see assigned-team attendance; HR Company Attendance is removed; Administrator attendance views are read-only. Validated QR scans remain in `AttendanceAudit`.

## Files and database changes

- Added migration `0031_system_event_log_and_fixed_leave_catalogue.py`.
- Added `SystemEventLog`, event middleware, `system_logs` view/template and `create_hr_user` management command.
- Added password-reset templates and environment variables for SMTP/password-reset setup.
- Updated dashboard navigation, role templates, kiosk log panel, employee pages, fixed leave catalogue page, README, `docs/architecture.md`, and SQL schema reference.

## Verification performed for the earlier architecture-aligned build (historical; not this revision)

- `python manage.py test eqrApp` - **46 tests passed**. Tests ran with a temporary local test settings module that switches static-file storage to non-manifest storage and uses a faster test-only password hasher; this temporary settings file is not included in the deliverable.
- `python manage.py check` - passed.
- `python manage.py makemigrations --check --dry-run` - passed; no missing model migrations.
- `python -m compileall -q eqrApp django_employee_qr` - passed.
- Migration `0031` applied during the test database setup.

These checks do not prove production AWS connectivity. The CloudFormation stack, EC2, RDS, S3, HTTPS and SMTP delivery still need to be deployed and integration-tested in the project's AWS account.

## Implementation decisions

- The diagram contains an isolated “Suggestion: Remove” annotation beside the QR area, without clearly naming the object to remove. It was not interpreted as a request to remove QR attendance because the previous explicit requirement was to implement and retain the QR attendance system.
- The architecture note describes Administrator modules as system overviews/logs/error handling. Only Administrator can activate and operate the kiosk; attendance and leave records remain read-only for Administrator. Administrator cannot manage HR employee records or approve leave requests.
- The diagram does not enumerate the fixed leave categories. The five categories above are starter values introduced by migration `0031`; verify their names and policy flags with the company before production use.

## Production work still required

1. Install the complete `requirements.txt` in a clean environment and repeat the documented checks/tests.
2. Configure the production secret key, database, private S3 bucket, TLS, trusted proxy, kiosk IP range and SMTP sender credentials.
3. Back up the existing database before applying migration `0031`; review its catalogue deactivation behavior before applying to a production database.
4. Provision the initial Administrator and HR users, schedule the daily QR generation and absence/reminder jobs, and verify role permissions with real test accounts.
5. Deploy the AWS stack and verify RDS/S3/SES integration. Do not describe the system as deployed until the live checks pass.


## QR kiosk browser compatibility update

Replaced the kiosk's native `BarcodeDetector` requirement and subsequent `html5-qrcode` implementation with the pinned `@zxing/browser` 0.2.1 library. The kiosk now enumerates/selects cameras in hidden Administrator settings; requests high-resolution video; enables continuous focus/auto-exposure when supported; and retries QR decoding with a normalized/sharpened crop and a thresholded crop when the original frame fails. After a successful scan, the kiosk suppresses repeated frames of the same visible token and automatically becomes ready for another scan after the QR leaves the camera view; there is no manual re-arm button. Manual token entry has been removed; the existing signed-token POST validation remains mandatory. The employee QR display was enlarged and its quiet zone/source resolution improved. Camera access still requires localhost during local development or HTTPS in deployment. ZXing is loaded from a pinned jsDelivr UMD build, with an unpkg fallback, so the kiosk browser needs CDN access.


## ZXing camera-scanner enhancement

- Replaced the `html5-qrcode` decoder with `@zxing/browser` 0.2.1 (ZXing Browser UMD).
- Added raw-frame, contrast-normalized/sharpened, and Otsu-thresholded decoding passes.
- Historical scanner version: camera selection and device controls were originally exposed in the kiosk interface. This behavior is superseded by the latest uploaded CHANGES (1).txt implementation below, where camera options are available only inside hidden Administrator settings and exposure controls are automatic.
- Added fallback camera constraints when a webcam rejects the preferred 1080p/24 fps request.
- Added clear guidance for browser camera permission, HTTPS/localhost, overexposure, reflections, and phone brightness.
- Added same-token suppression until a QR leaves the camera view; the scanner automatically prepares for the next employee without a manual re-arm button.
- Enlarged the employee QR image and rendered a larger quiet zone/source bitmap for better optical capture.
- No database schema changes or migration required.


## Demo Edition deployment revisions

The supplied `WorkTrack_Revision_List_Demo_Edition.docx` is implemented where the ZIP can be changed without access to the user's AWS account or deployed database:

1. **Gunicorn/Nginx:** Gunicorn now uses two workers and binds to `127.0.0.1:8000`; Nginx proxies to that TCP endpoint. This avoids a root-owned `/run` socket and gives the Django request a loopback peer when Nginx forwards the real client address.
2. **Login lockout:** Django Axes locks by username only (`AXES_LOCKOUT_PARAMETERS = ['username']`) so lockout does not rely on a client-supplied forwarded IP. A known username can consequently be locked for the one-hour cool-off window; see `docs/demo-limitations.md`.
3. **Kiosk camera secure context:** The demo guide uses an SSH port-forward so the kiosk browser opens `http://localhost:8000`. The scanner has no QR-token paste field. Under the later CHANGES v2 policy, the password-protected Ctrl+0 settings panel provides camera selection/restart and verified exit only; it cannot write attendance manually. The EC2 security group should not expose plain HTTP publicly for this tunnel-only mode. The service binds to loopback only.
4. **SQL catalogue and demo records:** Removed the stale `UL` catalogue insert and the statement that HR can edit the catalogue. `sql/schema.sql` contains a single set of five migration-0031 categories. Added `seed_worktrack_demo` to create fictional users, holidays, leave requests, balances, attendance rows, and daily QR rows; `sql/demo_data.sql` contains additional sample SQL. No live RDS connection or actual `pg_dump` export was available in this editing environment, so the package does not mislabel these samples as a deployed database dump.
5. **Documentation:** `rework-summary-2026-11.md` is marked superseded by this current summary.
6. **Server timezone:** The EC2 deployment script runs `timedatectl set-timezone Asia/Manila`; cron examples use the host's local timezone and no longer rely on `CRON_TZ`.
7. **Workers and environment-file access:** Gunicorn uses two workers. The deploy script sets `/etc/worktrack/worktrack.env` to owner `root`, group `www-data`, mode `0640` before the service reads it.
8. **Local verification:** Added a clean-environment verification script for Windows PowerShell and Linux/macOS, plus test-only settings that avoid the production static manifest during unit tests.
9. **IAM account choices:** CloudFormation defaults to creating the least-privilege instance role for a personal AWS account. A parameter now supports an existing Learner Lab instance profile without creating IAM resources; that external profile must already grant the required S3 and Secrets Manager access.
10. **Class demo email:** The deployment guide uses Django's console email backend and leaves SES disabled. Reset links and notifications can be demonstrated in `journalctl -u worktrack`; no real email is delivered in this mode.
11. **Secrets Manager:** The database secret remains in Secrets Manager. The docs call out possible monthly per-secret charges and require `DB_ADMIN_SECRET_ARN` to be removed after one-time application-user provisioning.
12. **ZXing CDN:** The pinned jsDelivr build and unpkg fallback are retained. The pre-demo checklist now verifies classroom access to these CDNs.
13. **SSH:** Security-group SSH ingress remains limited to `AdminCidr`; documentation says to update it when the admin public IP changes and to use Session Manager where available.
14. **Kiosk account:** Documentation recommends a dedicated Administrator account for the kiosk laptop rather than leaving a personal Administrator session signed in.

## Demo limitations to disclose

The daily QR remains valid for the whole Manila calendar day and can be screenshotted/shared; kiosk-side visual identity checking is only a demo mitigation. There is no employee attendance-correction request workflow. The five leave categories are fixed starter values, statutory leave types and company-policy entitlements are not modeled, and HR cannot edit the catalogue. The AWS template is a single-availability-zone application/database deployment without failover; CloudWatch alarms and log-retention automation are not configured; uploads have file-type/size/signature validation but no antivirus scanning; load/performance testing has not been done; plain HTTP is acceptable only for dummy data and the SSH-tunnel demo; sample data must be fictional under a privacy review; and `views.py` remains a large single module. See `docs/demo-limitations.md` for presentation wording.

## Verification for this revision

The source package includes a reproducible clean-venv script and one additional test for the demo-data seeder. The current editing environment did not include Django, and package-index DNS/network access prevented installing `requirements.txt`; therefore the full Django test suite, `manage.py check`, and migration autodetector could not be executed for this revision. Python compilation, shell syntax, and CloudFormation YAML parsing were checked locally. No AWS deployment, RDS export, SES send, real camera test, or classroom CDN test is claimed by this ZIP build.


## Additional company configuration and kiosk revisions

- Added fixed department choices (HR, IT, Finance, Marketing, Administration, Management) with department-dependent job position choices from the supplied marketing-company reference. The staffing counts shown in the reference are retained in option labels where applicable. New account forms start with no department or job position preselected, and the form displays the selected department’s documented WorkTrack usage as guidance.
- Separated the employee's job position from the internal WorkTrack access role. HR-created accounts remain restricted to Employee or Supervisor access; privileged HR/Administrator accounts are provisioned separately.
- Added Show/Hide password controls to sign-in, account creation/editing, password change, and password reset confirmation forms.
- Expanded company attendance search to support username, employee ID, and multi-word full-name queries.
- Added a private live QR scan-status endpoint so an employee's own dashboard clearly reports whether today's QR has not been scanned, check-in was recorded, or check-out is complete.
- Kept the kiosk on its own dedicated page. The page and scan endpoint remain Administrator-only, the Admin dashboard opens the kiosk separately, and kiosk activation is written to the system event log.

- Added dynamic department responsibility guidance to the HR account form using the second supplied marketing-company reference image; the descriptions are informational and do not grant application permissions. Updated the fictional demo seeder to use HR, IT, and Marketing departments with job titles from the fixed catalogue.


## Verification for the marketing-company account and kiosk revisions

- Added automated tests covering the six fixed department choices, each department's job-position list and usage guidance, cross-department position rejection, username/full-name/employee-ID attendance search, employee-only QR scan status, password-toggle script inclusion, and Administrator-only kiosk activation.
- Python source was syntax-compiled and AST-parsed; the account form's inline JavaScript and the password-toggle JavaScript passed Node syntax checks.
- Django runtime tests and migration checks were not executable in the editing environment because Django was not installed and package-index access was unavailable. Run `deploy/aws/verify_local.ps1` or `deploy/aws/verify_local.sh` on a machine with package access before the class demonstration.
- No live camera hardware test or AWS deployment is claimed.


## Dedicated kiosk isolation (security revision)

- Replaced the shared base-dashboard kiosk rendering with an independent, no-navigation scanner page.
- Added password-confirmed activation and password-confirmed exit for the same Administrator account.
- Rotates the Django session key on activation and exit.
- Added `KioskSessionLockMiddleware`, which redirects all non-kiosk WorkTrack routes (including dashboard and logout) back to the scanner while the kiosk session is active.
- Added a separate active-session check to the scan endpoint; an Administrator role alone is no longer sufficient to submit a scan.
- Added a per-session five-failure / five-minute lockout for activation and exit password checks.
- Added no-store cache headers, noindex metadata, history-back handling, and audit events for activation, failed attempts, and exit.
- Removed the attendance data table and admin navigation from the earlier standalone-kiosk version; the latest kiosk design restores a compact live attendance log while keeping the scanner-only interface and hidden Administrator settings. No raw QR token is accepted as a manual fallback.
- Limitation: application code cannot prevent browser/OS-level exit; use Windows Assigned Access and Chrome/Edge kiosk mode for a physically locked terminal.


## Latest uploaded CHANGES (1).txt implementation

This update supersedes the earlier kiosk operating instructions above where they describe a visible exit button, manual QR-token entry, or on-screen exposure/glare controls. The kiosk now starts its camera automatically as the standalone page loads, presents only the camera, concise instructions, and today's attendance history, and keeps the main page within a single viewport. The main scanner has no visible Start, Stop, Reduce Glare, manual QR token, or Exit controls.

Scan success/failure is shown with a fixed top notification and a high-visibility check/cross overlay. Successful scan responses insert or update the attendance log row immediately without refreshing the page. The scanner's frame interval is 150 ms; the same visible QR remains suppressed until it disappears from the frame so a stationary code cannot automatically produce both check-in and check-out.

A hidden **Ctrl+0** key binding opens Administrator verification. The settings session is active for ten minutes after successful password reauthentication and offers camera-device selection/restart and Exit Kiosk only. The exit action requires the activating Administrator's password again. Manual attendance by Employee ID and attendance correction have been removed from the interface and disabled at the server endpoints with HTTP 403 responses. No raw QR token can be manually pasted into the scanner.

Camera controls request continuous focus, exposure, and white-balance modes when supported and apply a gentle negative exposure compensation when the webcam exposes that capability. Camera selection and restart are hidden behind Administrator settings. Browser key interception is a deterrent only; Windows Assigned Access or an equivalent managed OS kiosk profile is still required to prevent browser closure, task switching, or desktop access.

The rest of CHANGES (1).txt is retained in this build: date/status roster attendance; searchable/filterable leave queues and histories; standard day-based leave balances; shared role-scoped calendar showing holidays and approved leave; auto-submit search/dropdown filters; fixed marketing-company department/position options; automatic employee username and temporary password provisioning; HR-only holiday maintenance; Admin account support; and keyword/date system-log filtering without an HTTP status column or severity filter. Leave entitlements are demo starter values and are not a substitute for HR/legal confirmation of company policy and statutory eligibility.

### Verification status for this update

Python source compilation, template/static content inspection, JavaScript syntax checking, configuration consistency inspection, and ZIP integrity are run for this packaging step. The current runtime does not have Django installed and the package index is unavailable, so the Django test suite, rendered-template checks, camera hardware test, and AWS deployment are not claimed as verified for this update. Run `python manage.py check`, `python manage.py makemigrations --check --dry-run`, and `python manage.py test eqrApp` after installing requirements in a clean local virtual environment.


## CHANGES v2 policy update

The later CHANGES v2 requirements supersede earlier demo revision notes where they conflict. In particular, HR is a role account and does not receive employee QR codes; HR's Company Attendance page is removed; future hire dates are rejected; Supervisor job titles are restricted to the approved list and reporting supervisors must be in the same department; supervisors only acknowledge leave applications and HR makes the final decision after acknowledgement; leave pending/history filters are independent; the Administrator log view contains warning/error events only and suppresses actor and employee identity; and Administrator account support is limited to name, username, and password. Administrator cannot edit attendance or leave records. The kiosk hidden settings therefore retain camera selection/restart and verified exit, while manual attendance entry and attendance correction are disabled.


## Latest CHANGES v2 policy enforcement

- Employee-role leave requests cannot receive an HR decision until an assigned Supervisor has acknowledged them. This also covers legacy `pending_hr` employee requests that lack `manager_reviewed_at`: they are kept in the Supervisor pending queue once a same-department Supervisor is assigned, then move to the Supervisor history only after acknowledgment. HR dashboard counts distinguish items awaiting Supervisor acknowledgment from items ready for HR decision.
- The hidden kiosk settings are scan-only administration controls: camera selection/restart and password-verified exit remain; manual attendance entry and attendance correction remain disabled with HTTP 403 responses.
- HR does not receive QR credentials and cannot access Company Attendance.
- Responsive CSS uses fluid grids, `clamp()` sizing, breakpoints, a mobile navigation drawer, and horizontally scrollable data tables.
- Administrator logs expose only sanitized warning/error summaries, date/severity filters, and no actor or employee identifiers. Admin Account Support is limited to name, username and password changes.


## CHANGES v2 static verification note

For this source revision, Python source compilation/AST parsing, static JavaScript syntax checks (including kiosk inline scripts), CSS brace checks, deployment shell syntax, CloudFormation YAML parsing with intrinsic tags, and ZIP integrity were checked. Django is not installed in the editing runtime, so `manage.py check`, `makemigrations --check`, and the Django automated test suite were not run here. Run `deploy/aws/verify_local.ps1` (Windows) or `deploy/aws/verify_local.sh` (Linux/macOS) before deploying. No live AWS or physical camera test is claimed.
