# Latest WorkTrack Demo Revision Coverage

This document summarizes the implementation of the requirements in the latest `CHANGES (1).txt` revision and includes the latest scanner-only kiosk behavior.

## General application behavior

- Filter dropdowns and date controls in the employee, attendance, leave, and system-log filter forms submit automatically when changed.
- Search fields debounce typing and automatically submit; server-side query handling searches the relevant employee name, username, ID, email, leave type, event message, or path fields.
- The shared monthly calendar is available to HR, supervisors, and employees, but not the Administrator role. It displays active holidays and approved leave. Employee users see their own leave; supervisors see their own and assigned-team leave; HR sees company leave.
- Only HR can create, edit, or deactivate holidays.
- Shared templates and page layouts include responsive breakpoints for common mobile and desktop widths.

## HR and employee account management

- HR creates Employee and Supervisor accounts without manually entering username or password.
- The generated username is `lastnamefirstname`; collisions are handled with a numeric suffix.
- A random temporary password is generated, shown to HR once, and must be changed at first sign-in.
- HR account forms use the fixed six-department marketing-company list and department-specific job-position choices from the supplied reference screenshots.
- The WorkTrack access role is independent of the job title. A job title containing “Manager” does not grant Supervisor privileges.
- The primary and backup reporting fields are labelled Supervisor and Backup Supervisor.
- Administrator has a read-only Employee Account Support page and can reset a supported account's username, password, or both. Administrator cannot edit employee profiles, attendance, or leave records.

## Attendance

- The HR Company Attendance module is removed. Supervisors see a date-specific team attendance table; employees see their own attendance history.
- Supervisors see the equivalent roster limited to assigned primary/backup reports and their own record.
- Employees see their own attendance history.
- Attendance filters include date and status, and the search supports username, name, and employee ID.
- An employee with an approved leave application covering a selected date is shown as On Leave for that date, without showing On Leave on unrelated dates.
- Administrators can view attendance and record current check-ins and check-outs by employee ID in unlocked kiosk settings.

## Leave Requests and balances

- Leave requests, approval queues, request history, the fixed leave catalogue, and balances are consolidated in the Leave Requests module for HR, supervisors, and employees.
- HR sees company requests and company balances. Supervisors see assigned-team requests and balances. Employees see their own requests and balances.
- Search, status/type filters, and sorting apply to the relevant queue and history.
- The leave catalogue is a collapsible information section; new leave requests use the fixed catalogue.
- The current demo defaults are SIL 5 days, Maternity 105 days, Paternity 7 days, Vacation 10 days, Sick 10 days, Emergency 3 days, and Bereavement 3 days. Vacation, sick, emergency, and bereavement values are illustrative company-policy defaults. Statutory eligibility and actual entitlements must be confirmed by qualified HR/legal personnel before real use.
- Approved usage is tracked against annual balances, and pending requests reserve available days when eligibility is checked.
- Supervisors can acknowledge requests from assigned primary/backup reports only; they cannot approve or decline. HR makes the final decision only after acknowledgement.

## Standalone Administrator QR kiosk

- The kiosk has a separate activation page. An authenticated Administrator must re-enter the current username and password to activate it.
- Activation rotates the Django session key and binds kiosk mode to the activating Administrator. While active, other WorkTrack application routes are redirected to the standalone kiosk.
- The scanner page contains the camera, instructions, and a compact live attendance history; it has no ordinary dashboard sidebar, QR token paste field, or visible kiosk operation/settings buttons.
- ZXing loads from the pinned CDN build. The camera starts automatically when the authenticated kiosk page loads. Camera focus/exposure/white balance are requested where supported; device selection and restart are available only in Administrator settings.
- A successful or failed scan triggers a prominent full-screen check/cross confirmation and a fixed high-visibility banner. Scan responses update the kiosk attendance history without refreshing the page.
- `Ctrl+0` opens the hidden settings authentication prompt. The activating Administrator must reauthenticate before using camera-device controls, recording attendance by Employee ID, correcting a record, or exiting the kiosk.
- Closing settings revokes the short-lived settings grant. Exit requires the activating Administrator's password; failed attempts are rate-limited and logged.
- The scanner accepts camera scans. Manual attendance by employee ID is available in unlocked settings.
- The browser UI blocks common navigation shortcuts and application routes, but application code cannot guarantee that a person cannot close the browser, switch to another Windows application, or access the desktop. Use Windows Assigned Access or another managed OS kiosk profile on a shared physical device.

## Verification and deployment limitations

- Static checks for this package include Python compilation, inline JavaScript syntax checks, shell-script syntax checks, CloudFormation YAML parsing when the YAML parser is available, content consistency checks, and ZIP integrity.
- The editing environment does not have Django installed and package-index access is unavailable. The Django runtime test suite, rendered-template tests, camera hardware tests, and AWS deployment are therefore not claimed as passed for this package. Run the documented local verification script on a machine with package access before using this build for a live demonstration.
- The QR token remains valid for the Manila calendar day. It can be screenshotted or shared; visual identity checking at the kiosk is still required for a demonstration.
- The database/application schema, leave entitlements, account seed data, and AWS infrastructure should be backed up and checked in the target environment before applying this version to real data.


## CHANGES v2 implementation notes

CHANGES v2 is the current authorization policy. Employee-role requests require a supervisor acknowledgment before HR's final approval/decline. Supervisors acknowledge only. Legacy employee requests in `pending_hr` with no acknowledgment are shown in the assigned Supervisor queue after assignment and withheld from HR decision until acknowledged. HR role accounts have no QR and no Company Attendance module. Job title choices are partitioned by Employee/Supervisor access role; supervisor options are restricted to the employee's department. Hire dates cannot be in the future. Administrator logs are warning/error-only and use generic safe summaries with no actor/employee details. Administrator Account Support is limited to name, username and password. Attendance can be recorded through QR scans or by employee ID in unlocked Administrator kiosk settings.
