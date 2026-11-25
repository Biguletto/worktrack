-- WorkTrack application schema for Amazon RDS PostgreSQL.
-- Django's auth_* tables are created by `python manage.py migrate` and are not
-- duplicated here. Run migrations first on a new RDS database. This file is a
-- reviewable schema reference and sample SQL deliverable; refresh it from the
-- deployed database with pg_dump --schema-only before final submission.

CREATE TABLE IF NOT EXISTS "eqrApp_employeeprofile" (
    id BIGSERIAL PRIMARY KEY,
    employee_id VARCHAR(30) NOT NULL UNIQUE,
    role VARCHAR(12) NOT NULL DEFAULT 'employee',
    department VARCHAR(100) NOT NULL,
    position VARCHAR(100) NOT NULL,
    phone_number VARCHAR(30) NOT NULL DEFAULT '',
    hire_date DATE NULL,
    employment_status VARCHAR(15) NOT NULL DEFAULT 'active',
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    user_id BIGINT NOT NULL UNIQUE REFERENCES auth_user(id) ON DELETE CASCADE,
    manager_id BIGINT NULL REFERENCES auth_user(id) ON DELETE SET NULL,
    backup_manager_id BIGINT NULL REFERENCES auth_user(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS "eqrApp_holiday" (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS "eqrApp_leavetype" (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(80) NOT NULL UNIQUE,
    code VARCHAR(20) NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    requires_document BOOLEAN NOT NULL DEFAULT FALSE,
    is_paid BOOLEAN NOT NULL DEFAULT TRUE,
    track_balance BOOLEAN NOT NULL DEFAULT FALSE,
    default_entitled_days NUMERIC(6,2) NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS "eqrApp_leavebalance" (
    id BIGSERIAL PRIMARY KEY,
    year SMALLINT NOT NULL,
    entitled_days NUMERIC(6,2) NOT NULL DEFAULT 0 CHECK (entitled_days >= 0),
    used_days NUMERIC(6,2) NOT NULL DEFAULT 0 CHECK (used_days >= 0),
    updated_at TIMESTAMPTZ NOT NULL,
    employee_id BIGINT NOT NULL REFERENCES "eqrApp_employeeprofile"(id) ON DELETE CASCADE,
    leave_type_id BIGINT NOT NULL REFERENCES "eqrApp_leavetype"(id) ON DELETE NO ACTION,
    CONSTRAINT unique_leave_balance_employee_type_year UNIQUE (employee_id, leave_type_id, year),
    CONSTRAINT leave_balance_used_not_over_entitlement CHECK (used_days <= entitled_days)
);

CREATE TABLE IF NOT EXISTS "eqrApp_leaveapplication" (
    id BIGSERIAL PRIMARY KEY,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    is_half_day BOOLEAN NOT NULL DEFAULT FALSE,
    reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending_hr',
    submitted_at TIMESTAMPTZ NOT NULL,
    manager_reviewed_at TIMESTAMPTZ NULL,
    manager_comments TEXT NOT NULL DEFAULT '',
    reviewed_at TIMESTAMPTZ NULL,
    reviewer_comments TEXT NOT NULL DEFAULT '',
    last_reminder_at TIMESTAMPTZ NULL,
    employee_id BIGINT NOT NULL REFERENCES "eqrApp_employeeprofile"(id) ON DELETE CASCADE,
    leave_type_id BIGINT NOT NULL REFERENCES "eqrApp_leavetype"(id) ON DELETE NO ACTION,
    manager_reviewed_by_id BIGINT NULL REFERENCES auth_user(id) ON DELETE SET NULL,
    reviewed_by_id BIGINT NULL REFERENCES auth_user(id) ON DELETE SET NULL,
    CONSTRAINT leave_end_on_or_after_start CHECK (end_date >= start_date),
    CONSTRAINT half_day_leave_single_date CHECK (NOT is_half_day OR start_date = end_date)
);

CREATE TABLE IF NOT EXISTS "eqrApp_leavedocument" (
    id BIGSERIAL PRIMARY KEY,
    file VARCHAR(100) NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL,
    application_id BIGINT NOT NULL REFERENCES "eqrApp_leaveapplication"(id) ON DELETE CASCADE,
    uploaded_by_id BIGINT NULL REFERENCES auth_user(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS "eqrApp_leaveaction" (
    id BIGSERIAL PRIMARY KEY,
    action VARCHAR(20) NOT NULL,
    comments TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    application_id BIGINT NOT NULL REFERENCES "eqrApp_leaveapplication"(id) ON DELETE CASCADE,
    actor_id BIGINT NULL REFERENCES auth_user(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS "eqrApp_leavedeletionaudit" (
    id BIGSERIAL PRIMARY KEY,
    application_reference BIGINT NOT NULL,
    employee_id_snapshot VARCHAR(30) NOT NULL,
    employee_name_snapshot VARCHAR(160) NOT NULL,
    leave_type_name VARCHAR(80) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    previous_status VARCHAR(20) NOT NULL,
    deleted_at TIMESTAMPTZ NOT NULL,
    employee_id BIGINT NULL REFERENCES "eqrApp_employeeprofile"(id) ON DELETE SET NULL,
    actor_id BIGINT NULL REFERENCES auth_user(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS "eqrApp_dailyattendanceqr" (
    id BIGSERIAL PRIMARY KEY,
    qr_date DATE NOT NULL,
    nonce UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    employee_id BIGINT NOT NULL REFERENCES "eqrApp_employeeprofile"(id) ON DELETE CASCADE,
    CONSTRAINT unique_daily_attendance_qr_employee_date UNIQUE (employee_id, qr_date)
);

CREATE TABLE IF NOT EXISTS "eqrApp_attendancerecord" (
    id BIGSERIAL PRIMARY KEY,
    attendance_date DATE NOT NULL,
    check_in TIMESTAMPTZ NULL,
    check_out TIMESTAMPTZ NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'present',
    source VARCHAR(20) NOT NULL DEFAULT 'self_service',
    remarks TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    employee_id BIGINT NOT NULL REFERENCES "eqrApp_employeeprofile"(id) ON DELETE CASCADE,
    recorded_by_id BIGINT NULL REFERENCES auth_user(id) ON DELETE SET NULL,
    CONSTRAINT unique_employee_attendance_per_day UNIQUE (employee_id, attendance_date),
    CONSTRAINT attendance_checkout_not_before_checkin CHECK (check_in IS NULL OR check_out IS NULL OR check_out >= check_in)
);

CREATE TABLE IF NOT EXISTS "eqrApp_attendanceaudit" (
    id BIGSERIAL PRIMARY KEY,
    action VARCHAR(10) NOT NULL,
    old_values JSONB NOT NULL DEFAULT '{}'::jsonb,
    new_values JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    employee_id BIGINT NOT NULL REFERENCES "eqrApp_employeeprofile"(id) ON DELETE RESTRICT,
    attendance_id BIGINT NULL REFERENCES "eqrApp_attendancerecord"(id) ON DELETE SET NULL,
    actor_id BIGINT NULL REFERENCES auth_user(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS eqrapp_attendancerecord_date_idx
    ON "eqrApp_attendancerecord" (attendance_date DESC);
CREATE INDEX IF NOT EXISTS eqrapp_leaveapplication_status_submitted_idx
    ON "eqrApp_leaveapplication" (status, submitted_at DESC);
CREATE INDEX IF NOT EXISTS eqrapp_leaveapplication_employee_dates_idx
    ON "eqrApp_leaveapplication" (employee_id, start_date, end_date);
CREATE INDEX IF NOT EXISTS eqrapp_leavedeletionaudit_deleted_idx
    ON "eqrApp_leavedeletionaudit" (deleted_at DESC);
CREATE INDEX IF NOT EXISTS eqrapp_attendanceaudit_employee_created_idx
    ON "eqrApp_attendanceaudit" (employee_id, created_at DESC);

-- WorkTrack migrations 0031 and 0032 install the fixed company leave catalogue and demo entitlement defaults.
-- The catalogue is fixed in the application UI; HR cannot edit it.

-- Example INSERT: create an attendance row for an existing employee profile (normally recorded through the admin QR kiosk).
-- INSERT INTO "eqrApp_attendancerecord"
--   (attendance_date, check_in, check_out, status, source, remarks, created_at, updated_at, employee_id)
-- VALUES (CURRENT_DATE, NOW(), NULL, 'present', 'admin', 'Manual administrator record', NOW(), NOW(), 1);

-- SELECT: read a month's attendance with employee details.
-- SELECT p.employee_id, u.first_name, u.last_name, a.attendance_date, a.status
-- FROM "eqrApp_attendancerecord" a
-- JOIN "eqrApp_employeeprofile" p ON p.id = a.employee_id
-- JOIN auth_user u ON u.id = p.user_id
-- WHERE a.attendance_date >= DATE_TRUNC('month', CURRENT_DATE)::date
-- ORDER BY a.attendance_date, p.employee_id;

-- UPDATE: HR correction example only when the configured attendance policy permits HR correction.
-- UPDATE "eqrApp_attendancerecord" SET status = 'late', remarks = 'Approved correction', updated_at = NOW()
-- WHERE employee_id = 1 AND attendance_date = CURRENT_DATE;

-- DELETE: example test-record cleanup only; application permissions and audit rules govern real changes.
-- DELETE FROM "eqrApp_attendancerecord" WHERE id = 999999;

-- CREATE: Django's migration system is authoritative for the table definitions above.


CREATE TABLE IF NOT EXISTS "eqrApp_systemeventlog" (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(40) NOT NULL DEFAULT 'application_event',
    severity VARCHAR(12) NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    request_path VARCHAR(500) NOT NULL DEFAULT '',
    http_method VARCHAR(12) NOT NULL DEFAULT '',
    status_code SMALLINT NULL,
    ip_address INET NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    actor_id BIGINT NULL REFERENCES auth_user(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS system_event_severity_date_idx
    ON "eqrApp_systemeventlog" (severity, created_at DESC);
CREATE INDEX IF NOT EXISTS system_event_status_date_idx
    ON "eqrApp_systemeventlog" (status_code, created_at DESC);

-- Fixed company-wide leave catalogue and demonstration entitlements (matches migration 0032).
-- Vacation/sick/emergency/bereavement defaults are examples, not a statement of company policy.
INSERT INTO "eqrApp_leavetype"
    (name, code, description, requires_document, is_paid, track_balance, default_entitled_days, is_active, created_at)
VALUES
    ('Service Incentive Leave', 'SIL', '5 paid days per year. Confirm statutory and company eligibility.', FALSE, TRUE, TRUE, 5, TRUE, NOW()),
    ('Maternity Leave', 'MAT', '105 paid days for childbirth. Eligibility and legal conditions require review.', FALSE, TRUE, TRUE, 105, TRUE, NOW()),
    ('Paternity Leave', 'PAT', '7 paid days. Eligibility and legal conditions require review.', FALSE, TRUE, TRUE, 7, TRUE, NOW()),
    ('Vacation Leave', 'VL', '10 paid days per year as a demonstration company-policy default.', FALSE, TRUE, TRUE, 10, TRUE, NOW()),
    ('Sick Leave', 'SL', '10 paid days per year as a demonstration company-policy default.', FALSE, TRUE, TRUE, 10, TRUE, NOW()),
    ('Emergency Leave', 'EL', '3 paid days per year as a demonstration company-policy default.', FALSE, TRUE, TRUE, 3, TRUE, NOW()),
    ('Bereavement Leave', 'BL', '3 paid days per year as a demonstration company-policy default.', FALSE, TRUE, TRUE, 3, TRUE, NOW())
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    requires_document = EXCLUDED.requires_document,
    is_paid = EXCLUDED.is_paid,
    track_balance = EXCLUDED.track_balance,
    default_entitled_days = EXCLUDED.default_entitled_days,
    is_active = TRUE;

UPDATE "eqrApp_leavetype"
SET is_active = FALSE, track_balance = FALSE
WHERE code NOT IN ('SIL', 'MAT', 'PAT', 'VL', 'SL', 'EL', 'BL');
