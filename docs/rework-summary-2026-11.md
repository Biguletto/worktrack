> **Historical note:** This summary is superseded by `revision-summary.md` and the current deployment/demo guidance. Refer to those files for the current roles, QR scanner behavior, and deployment configuration.

# WorkTrack UI and workflow rework

This update applies the specified changes to the uploaded WorkTrack Django project.

## Implemented changes

1. **Login lockout/error page** - Django Axes now renders a branded WorkTrack lockout page instead of the default plain-text response. The existing security policy remains unchanged: five failed attempts, a one-hour cool-off, and HTTP 429 for a lockout response.
2. **Department for HR and administrator accounts** - The account form hides the Department field when HR Personnel or Administrator is selected. The field remains required for Employee and Supervisor positions. HR and administrator profiles save with an empty department.
3. **One visible Position field** - The account form no longer presents separate Role and Position inputs. The Position dropdown contains Employee, Supervisor, HR Personnel, and Administrator. The selected position is synchronized with the underlying `EmployeeProfile.role` field, which is retained for authorization and dashboard access control. Dashboard headers and account tables display the consolidated Position label.
4. **Employment status** - New accounts no longer show Employment status and are created as Active. The status field remains available when editing an existing employee account.
5. **Holiday calendar and date validation** - The holiday list is now a month-grid calendar with previous/next month navigation and holiday actions inside the date cells. The date input sets today's date as its minimum, and server-side validation rejects past dates. The uploaded project has no separate Event model or event-management workflow, so this applies to the existing Holiday feature only.
6. **Attendance grouped by employee** - HR/Admin and Supervisor attendance pages now group each employee's attendance rows together. Dates are shown newest first within each employee group, instead of mixing employees in one time-sorted list.

## Database migration

One migration was added:

- `eqrApp/migrations/0029_employeeprofile_department_blank.py`

It allows an empty department for HR and Administrator profiles. Existing employee and supervisor forms still require a department.

After extracting this project, run the migration before starting the server:

```powershell
python manage.py migrate
```

## Verification

- `python manage.py check` - passed.
- `python manage.py makemigrations --check --dry-run` - passed; no missing model migrations.
- `python manage.py test eqrApp` - 26 tests passed.

The tests were executed with the project's bundled dependencies and a test-only static-files storage override. The production AWS services were not deployed or tested as part of this UI update.

## Items not specified in the request

The original numbered list skips item 6 and ends with an unfinished item 8. No additional behavior was inferred for those missing items. The project also does not currently contain a separate Event model; only the Holiday calendar was reworked.


## QR attendance rework (November 2026)

1. Active Employee, Supervisor, and HR Personnel profiles receive their own signed QR credential on their dashboards.
2. A QR record is generated per profile and Asia/Manila date. Its random nonce and date are signed using Django's `SECRET_KEY`; old-date tokens are rejected.
3. Added the `generate_daily_attendance_qr` management command for a 12:00 AM daily scheduler. Dashboard loading initializes the daily QR as a fallback.
4. Added an Administrator-only laptop kiosk using browser camera scanning with the native `BarcodeDetector` API. First scan records check-in; second scan records check-out; further scans are rejected.
5. Employee attendance monitoring is self-only, Supervisor monitoring is limited to assigned team members plus the supervisor's own record, HR monitoring is organization-wide read-only, and Administrator has full oversight.
6. Attendance add/edit/delete routes and the kiosk scan endpoint require Administrator access. Attendance scan/correction actions are preserved in `AttendanceAudit`.
7. Optional `WORKTRACK_KIOSK_IP_RANGES` provides an additional allowlist for a dedicated production kiosk laptop.
