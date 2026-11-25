-- Optional fictional sample records for the CCS4301 class demonstration.
-- First run migrations and then:
--   python manage.py seed_worktrack_demo
-- This command creates the DEMO-EMP-001 and DEMO-EMP-002 profiles and sample
-- holidays, leave requests, attendance rows, balances, and daily QR credentials.
-- This SQL file adds a small additional set of idempotent examples. It is not
-- an export from a deployed RDS database.

-- Example future holiday.
INSERT INTO "eqrApp_holiday" (date, name, is_active, created_at)
VALUES (CURRENT_DATE + 60, 'Demo Community Day (SQL Sample)', TRUE, NOW())
ON CONFLICT (date) DO NOTHING;

-- Example leave application for DEMO-EMP-001 using the migration-0032 VL type.
INSERT INTO "eqrApp_leaveapplication"
    (start_date, end_date, is_half_day, reason, status, submitted_at,
     manager_reviewed_at, manager_comments, reviewed_at, reviewer_comments,
     last_reminder_at, employee_id, leave_type_id, manager_reviewed_by_id, reviewed_by_id)
SELECT
    CURRENT_DATE + 14,
    CURRENT_DATE + 15,
    FALSE,
    'Fictional SQL sample leave request.',
    'pending_manager',
    NOW(),
    NULL,
    '',
    NULL,
    '',
    NULL,
    employee.id,
    leave_type.id,
    NULL,
    NULL
FROM "eqrApp_employeeprofile" employee
JOIN "eqrApp_leavetype" leave_type ON leave_type.code = 'VL' AND leave_type.is_active = TRUE
WHERE employee.employee_id = 'DEMO-EMP-001'
  AND NOT EXISTS (
      SELECT 1 FROM "eqrApp_leaveapplication" existing
      WHERE existing.employee_id = employee.id
        AND existing.reason = 'Fictional SQL sample leave request.'
  );

-- Example completed attendance row for DEMO-EMP-002 on the previous day.
INSERT INTO "eqrApp_attendancerecord"
    (attendance_date, check_in, check_out, status, source, remarks,
     created_at, updated_at, employee_id, recorded_by_id)
SELECT
    CURRENT_DATE - 1,
    (CURRENT_DATE - 1)::timestamp + TIME '08:55',
    (CURRENT_DATE - 1)::timestamp + TIME '17:05',
    'present',
    'admin',
    'Fictional SQL sample attendance row.',
    NOW(),
    NOW(),
    employee.id,
    NULL
FROM "eqrApp_employeeprofile" employee
WHERE employee.employee_id = 'DEMO-EMP-002'
ON CONFLICT (employee_id, attendance_date) DO NOTHING;
