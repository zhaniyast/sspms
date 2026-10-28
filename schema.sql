-- =====================================================================
-- University portal: full database schema (PostgreSQL 14+)
-- Student side + teacher side. Registration is closed: all accounts are
-- created by admins. Roles: student / teacher / admin ("advisor" is NOT a
-- role, it is a row in advisor_assignments).
-- Order: A reference -> B people -> C courses -> D grading -> E attendance
--        F communication -> G feedback -> H risk model -> I advising
--        J student tools -> K views, functions, triggers
-- =====================================================================

-- ---------------------------------------------------------------------
-- A. REFERENCE DATA
-- ---------------------------------------------------------------------
CREATE TABLE departments (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(120) NOT NULL UNIQUE
);

CREATE TABLE programs (                       -- specialties / degree programs
    id            SERIAL PRIMARY KEY,
    code          VARCHAR(20)  NOT NULL UNIQUE,
    name          VARCHAR(120) NOT NULL,
    total_credits INT NOT NULL DEFAULT 240,
    department_id INT REFERENCES departments(id)
);

CREATE TABLE student_groups (
    id             SERIAL PRIMARY KEY,
    code           VARCHAR(20) NOT NULL UNIQUE,
    program_id     INT NOT NULL REFERENCES programs(id),
    admission_year SMALLINT NOT NULL
);

CREATE TABLE semesters (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(40) NOT NULL UNIQUE,   -- e.g. 'Fall 2026'
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL,
    total_weeks SMALLINT NOT NULL DEFAULT 16,
    is_current  BOOLEAN NOT NULL DEFAULT FALSE,
    CHECK (end_date > start_date)
);
CREATE UNIQUE INDEX one_current_semester ON semesters (is_current) WHERE is_current;

CREATE TABLE rooms (
    id       SERIAL PRIMARY KEY,
    building VARCHAR(40) NOT NULL,
    number   VARCHAR(20) NOT NULL,
    capacity INT,
    UNIQUE (building, number)
);

-- single source of truth for letters / GPA points (no hardcoded scales)
CREATE TABLE grade_scales (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(60) NOT NULL UNIQUE
);
CREATE TABLE grade_scale_levels (
    id           SERIAL PRIMARY KEY,
    scale_id     INT NOT NULL REFERENCES grade_scales(id) ON DELETE CASCADE,
    letter       VARCHAR(3) NOT NULL,
    min_percent  NUMERIC(5,2) NOT NULL CHECK (min_percent BETWEEN 0 AND 100),
    gpa_points   NUMERIC(3,2) NOT NULL CHECK (gpa_points BETWEEN 0 AND 4),
    UNIQUE (scale_id, letter),
    UNIQUE (scale_id, min_percent)
);

CREATE TABLE late_policies (
    id                SERIAL PRIMARY KEY,
    name              VARCHAR(60) NOT NULL,
    grace_hours       INT NOT NULL DEFAULT 0,
    penalty_pct_day   NUMERIC(5,2) NOT NULL DEFAULT 0,
    max_penalty_pct   NUMERIC(5,2) NOT NULL DEFAULT 100
);

-- ---------------------------------------------------------------------
-- B. PEOPLE AND ACCESS
-- ---------------------------------------------------------------------
CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    login_id      VARCHAR(20) NOT NULL UNIQUE,   -- ID issued by admin
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(10) NOT NULL CHECK (role IN ('student','teacher','admin')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    last_login    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by    INT REFERENCES users(id)       -- which admin created the account
);

CREATE TABLE user_settings (
    user_id  INT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    language VARCHAR(2) NOT NULL DEFAULT 'ru' CHECK (language IN ('kk','ru','en')),
    theme    VARCHAR(10) NOT NULL DEFAULT 'system' CHECK (theme IN ('light','dark','system'))
);

CREATE TABLE students (
    user_id        INT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    first_name     VARCHAR(60) NOT NULL,
    last_name      VARCHAR(80) NOT NULL,
    email          VARCHAR(120) UNIQUE,
    phone          VARCHAR(20),
    photo_url      TEXT,
    group_id       INT NOT NULL REFERENCES student_groups(id),
    program_id     INT NOT NULL REFERENCES programs(id),
    admission_year SMALLINT NOT NULL,
    status         VARCHAR(12) NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active','academic_leave','graduated','expelled')),
    UNIQUE (first_name, last_name)               -- full name must not repeat
);

CREATE TABLE teachers (
    user_id           INT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    first_name        VARCHAR(60) NOT NULL,
    last_name         VARCHAR(80) NOT NULL,
    email             VARCHAR(120) UNIQUE,
    photo_url         TEXT,
    title             VARCHAR(60),
    department_id     INT NOT NULL REFERENCES departments(id),
    office            VARCHAR(30),
    office_hours_note VARCHAR(200),
    UNIQUE (first_name, last_name)
);

-- ---------------------------------------------------------------------
-- C. COURSES
-- ---------------------------------------------------------------------
CREATE TABLE courses (                         -- catalog (semester independent)
    id            SERIAL PRIMARY KEY,
    code          VARCHAR(20) NOT NULL UNIQUE,
    name          VARCHAR(160) NOT NULL,
    credits       SMALLINT NOT NULL CHECK (credits > 0),
    department_id INT REFERENCES departments(id),
    description   TEXT
);

CREATE TABLE course_offerings (                -- a course in a specific semester
    id               SERIAL PRIMARY KEY,
    course_id        INT NOT NULL REFERENCES courses(id),
    semester_id      INT NOT NULL REFERENCES semesters(id),
    teacher_id       INT NOT NULL REFERENCES teachers(user_id),   -- responsible teacher
    color            CHAR(7) NOT NULL DEFAULT '#3B82F6',          -- one colour everywhere
    grade_scale_id   INT NOT NULL REFERENCES grade_scales(id),
    max_absence_pct  NUMERIC(5,2) NOT NULL DEFAULT 20,
    format_note      VARCHAR(200),
    UNIQUE (course_id, semester_id)
);

CREATE TABLE offering_staff (                  -- co-teachers and assistants
    offering_id INT NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
    teacher_id  INT NOT NULL REFERENCES teachers(user_id),
    staff_role  VARCHAR(10) NOT NULL CHECK (staff_role IN ('lecturer','ta')),
    PRIMARY KEY (offering_id, teacher_id)
);

CREATE TABLE sections (
    id          SERIAL PRIMARY KEY,
    offering_id INT NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
    name        VARCHAR(20) NOT NULL,
    UNIQUE (offering_id, name)
);

CREATE TABLE enrollments (
    id          SERIAL PRIMARY KEY,
    student_id  INT NOT NULL REFERENCES students(user_id),
    offering_id INT NOT NULL REFERENCES course_offerings(id),
    section_id  INT REFERENCES sections(id),
    status      VARCHAR(10) NOT NULL DEFAULT 'enrolled'
                CHECK (status IN ('enrolled','dropped','completed','failed')),
    enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (student_id, offering_id)
);

CREATE TABLE schedule_slots (                  -- weekly timetable
    id          SERIAL PRIMARY KEY,
    offering_id INT NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
    section_id  INT REFERENCES sections(id),
    weekday     SMALLINT NOT NULL CHECK (weekday BETWEEN 1 AND 7),
    start_time  TIME NOT NULL,
    end_time    TIME NOT NULL,
    room_id     INT REFERENCES rooms(id),
    lesson_type VARCHAR(10) NOT NULL CHECK (lesson_type IN ('lecture','practice','lab')),
    CHECK (end_time > start_time)
);

CREATE TABLE class_meetings (                  -- concrete dated lessons
    id          SERIAL PRIMARY KEY,
    offering_id INT NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
    section_id  INT REFERENCES sections(id),
    slot_id     INT REFERENCES schedule_slots(id),
    meeting_date DATE NOT NULL,
    start_time  TIME NOT NULL,
    end_time    TIME NOT NULL,
    room_id     INT REFERENCES rooms(id),
    lesson_type VARCHAR(10) NOT NULL CHECK (lesson_type IN ('lecture','practice','lab')),
    topic       VARCHAR(200),
    week_no     SMALLINT
);
CREATE INDEX idx_meetings_offering_date ON class_meetings (offering_id, meeting_date);

CREATE TABLE syllabus_weeks (
    id          SERIAL PRIMARY KEY,
    offering_id INT NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
    week_no     SMALLINT NOT NULL,
    topic       VARCHAR(200) NOT NULL,
    description TEXT,
    UNIQUE (offering_id, week_no)
);

CREATE TABLE materials (
    id            SERIAL PRIMARY KEY,
    offering_id   INT NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
    week_no       SMALLINT,
    title         VARCHAR(200) NOT NULL,
    material_type VARCHAR(10) NOT NULL CHECK (material_type IN ('pdf','slides','video','link','other')),
    url           TEXT NOT NULL,
    visibility    VARCHAR(10) NOT NULL DEFAULT 'visible' CHECK (visibility IN ('visible','hidden','scheduled')),
    visible_from  TIMESTAMPTZ,
    uploaded_by   INT REFERENCES teachers(user_id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE announcements (                   -- offering_id NULL = university-wide
    id           SERIAL PRIMARY KEY,
    author_id    INT NOT NULL REFERENCES users(id),
    offering_id  INT REFERENCES course_offerings(id) ON DELETE CASCADE,
    title        VARCHAR(200) NOT NULL,
    body         TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE discussion_threads (
    id          SERIAL PRIMARY KEY,
    offering_id INT NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
    author_id   INT NOT NULL REFERENCES users(id),
    title       VARCHAR(200) NOT NULL,
    is_pinned   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE discussion_posts (
    id         SERIAL PRIMARY KEY,
    thread_id  INT NOT NULL REFERENCES discussion_threads(id) ON DELETE CASCADE,
    author_id  INT NOT NULL REFERENCES users(id),
    body       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- D. ASSESSMENT AND GRADES
-- ---------------------------------------------------------------------
CREATE TABLE assessment_categories (           -- weights of one offering must sum to 100
    id          SERIAL PRIMARY KEY,
    offering_id INT NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
    name        VARCHAR(60) NOT NULL,           -- Assignments, Midterm, Final ...
    weight_pct  NUMERIC(5,2) NOT NULL CHECK (weight_pct > 0 AND weight_pct <= 100),
    UNIQUE (offering_id, name)
);

CREATE TABLE assessments (
    id             SERIAL PRIMARY KEY,
    offering_id    INT NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
    category_id    INT NOT NULL REFERENCES assessment_categories(id),
    title          VARCHAR(200) NOT NULL,
    description    TEXT,
    kind           VARCHAR(12) NOT NULL DEFAULT 'assignment'
                   CHECK (kind IN ('assignment','quiz','midterm','final','project')),
    due_at         TIMESTAMPTZ NOT NULL,
    max_score      NUMERIC(6,2) NOT NULL CHECK (max_score > 0),
    weight_pct     NUMERIC(5,2) NOT NULL DEFAULT 0,      -- share inside the course
    status         VARCHAR(10) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published')),
    visible_from   TIMESTAMPTZ,
    late_policy_id INT REFERENCES late_policies(id),
    created_by     INT REFERENCES teachers(user_id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_assessments_offering ON assessments (offering_id, due_at);

CREATE TABLE rubrics (                          -- optional, can be postponed
    id            SERIAL PRIMARY KEY,
    assessment_id INT NOT NULL UNIQUE REFERENCES assessments(id) ON DELETE CASCADE
);
CREATE TABLE rubric_criteria (
    id        SERIAL PRIMARY KEY,
    rubric_id INT NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
    title     VARCHAR(120) NOT NULL,
    max_score NUMERIC(6,2) NOT NULL CHECK (max_score > 0)
);

CREATE TABLE submissions (
    id            SERIAL PRIMARY KEY,
    assessment_id INT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    student_id    INT NOT NULL REFERENCES students(user_id),
    status        VARCHAR(14) NOT NULL DEFAULT 'not_submitted'
                  CHECK (status IN ('not_submitted','submitted','late','graded')),
    file_url      TEXT,
    text_answer   TEXT,
    attempt_no    SMALLINT NOT NULL DEFAULT 1,
    submitted_at  TIMESTAMPTZ,
    UNIQUE (assessment_id, student_id, attempt_no)
);
CREATE INDEX idx_submissions_queue ON submissions (assessment_id, status);

CREATE TABLE grades (
    id            SERIAL PRIMARY KEY,
    assessment_id INT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    student_id    INT NOT NULL REFERENCES students(user_id),
    submission_id INT REFERENCES submissions(id),
    score         NUMERIC(6,2) CHECK (score >= 0),
    late_penalty  NUMERIC(6,2) NOT NULL DEFAULT 0,
    is_excused    BOOLEAN NOT NULL DEFAULT FALSE,   -- "освобождён"
    status        VARCHAR(10) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published')),
    comment       TEXT,
    graded_by     INT REFERENCES teachers(user_id),
    graded_at     TIMESTAMPTZ,
    published_at  TIMESTAMPTZ,
    UNIQUE (assessment_id, student_id)
);
CREATE INDEX idx_grades_student ON grades (student_id, status);

CREATE TABLE rubric_scores (
    grade_id     INT NOT NULL REFERENCES grades(id) ON DELETE CASCADE,
    criterion_id INT NOT NULL REFERENCES rubric_criteria(id) ON DELETE CASCADE,
    score        NUMERIC(6,2) NOT NULL CHECK (score >= 0),
    PRIMARY KEY (grade_id, criterion_id)
);

-- append-only history of every grade change (updates/deletes are blocked, see K)
CREATE TABLE grade_audit_log (
    id          BIGSERIAL PRIMARY KEY,
    grade_id    INT NOT NULL REFERENCES grades(id),
    changed_by  INT NOT NULL REFERENCES users(id),
    old_score   NUMERIC(6,2),
    new_score   NUMERIC(6,2),
    old_status  VARCHAR(10),
    new_status  VARCHAR(10),
    reason      TEXT,
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE comment_bank (                     -- teacher's quick comments
    id         SERIAL PRIMARY KEY,
    teacher_id INT NOT NULL REFERENCES teachers(user_id) ON DELETE CASCADE,
    text       TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- E. ATTENDANCE
-- ---------------------------------------------------------------------
CREATE TABLE excuse_documents (
    id          SERIAL PRIMARY KEY,
    student_id  INT NOT NULL REFERENCES students(user_id),
    meeting_id  INT NOT NULL REFERENCES class_meetings(id),
    file_url    TEXT NOT NULL,
    status      VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    reviewed_by INT REFERENCES teachers(user_id),
    review_comment TEXT,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ,
    UNIQUE (student_id, meeting_id)
);

CREATE TABLE attendance (
    id                 SERIAL PRIMARY KEY,
    meeting_id         INT NOT NULL REFERENCES class_meetings(id) ON DELETE CASCADE,
    student_id         INT NOT NULL REFERENCES students(user_id),
    status             VARCHAR(10) NOT NULL CHECK (status IN ('present','absent','late','excused')),
    marked_by          INT REFERENCES teachers(user_id),
    marked_at          TIMESTAMPTZ,
    excuse_document_id INT REFERENCES excuse_documents(id),
    UNIQUE (meeting_id, student_id)
);
CREATE INDEX idx_attendance_student ON attendance (student_id);

-- ---------------------------------------------------------------------
-- F. COMMUNICATION AND NOTIFICATIONS
-- ---------------------------------------------------------------------
CREATE TABLE conversations (
    id          SERIAL PRIMARY KEY,
    kind        VARCHAR(10) NOT NULL DEFAULT 'direct' CHECK (kind IN ('direct','course','broadcast')),
    offering_id INT REFERENCES course_offerings(id),
    title       VARCHAR(120),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE conversation_participants (
    conversation_id INT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         INT NOT NULL REFERENCES users(id),
    last_read_at    TIMESTAMPTZ,
    PRIMARY KEY (conversation_id, user_id)
);
CREATE TABLE messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id INT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender_id       INT NOT NULL REFERENCES users(id),
    body            TEXT NOT NULL,
    attachment_url  TEXT,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_conv ON messages (conversation_id, sent_at);

CREATE TABLE message_reads (
    message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id    INT NOT NULL REFERENCES users(id),
    read_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, user_id)
);

CREATE TABLE message_templates (
    id         SERIAL PRIMARY KEY,
    teacher_id INT REFERENCES teachers(user_id) ON DELETE CASCADE,   -- NULL = shared template
    title      VARCHAR(120) NOT NULL,
    body       TEXT NOT NULL
);

CREATE TABLE notifications (
    id         BIGSERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type       VARCHAR(30) NOT NULL CHECK (type IN (
                 'new_grade','deadline','message','risk_up',
                 'submission_new','excuse_pending','appointment_request','grading_due')),
    title      VARCHAR(200) NOT NULL,
    link       VARCHAR(200),
    is_read    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_notifications_user ON notifications (user_id, is_read, created_at DESC);

CREATE TABLE notification_settings (            -- table "event type x channel"
    user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type       VARCHAR(30) NOT NULL,
    by_email   BOOLEAN NOT NULL DEFAULT TRUE,
    in_app     BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (user_id, type)
);

-- ---------------------------------------------------------------------
-- G. COURSE FEEDBACK (anonymous: participation and responses are NOT linked)
-- ---------------------------------------------------------------------
CREATE TABLE feedback_surveys (
    id          SERIAL PRIMARY KEY,
    offering_id INT NOT NULL UNIQUE REFERENCES course_offerings(id),
    opens_at    TIMESTAMPTZ NOT NULL,
    closes_at   TIMESTAMPTZ NOT NULL
);
CREATE TABLE feedback_participation (           -- only the fact "this student answered"
    survey_id  INT NOT NULL REFERENCES feedback_surveys(id) ON DELETE CASCADE,
    student_id INT NOT NULL REFERENCES students(user_id),
    PRIMARY KEY (survey_id, student_id)
);
CREATE TABLE feedback_responses (               -- NO student_id here, date without time
    id                  SERIAL PRIMARY KEY,
    survey_id           INT NOT NULL REFERENCES feedback_surveys(id) ON DELETE CASCADE,
    rating_content      SMALLINT NOT NULL CHECK (rating_content BETWEEN 1 AND 5),
    rating_teaching     SMALLINT NOT NULL CHECK (rating_teaching BETWEEN 1 AND 5),
    rating_materials    SMALLINT NOT NULL CHECK (rating_materials BETWEEN 1 AND 5),
    rating_assessment   SMALLINT NOT NULL CHECK (rating_assessment BETWEEN 1 AND 5),
    rating_availability SMALLINT NOT NULL CHECK (rating_availability BETWEEN 1 AND 5),
    comment             TEXT,
    answered_on         DATE NOT NULL DEFAULT CURRENT_DATE
);

-- ---------------------------------------------------------------------
-- H. ACTIVITY AND RISK MODEL
-- ---------------------------------------------------------------------
CREATE TABLE weekly_activity (
    id               SERIAL PRIMARY KEY,
    student_id       INT NOT NULL REFERENCES students(user_id),
    offering_id      INT NOT NULL REFERENCES course_offerings(id),
    week_no          SMALLINT NOT NULL,
    logins           INT NOT NULL DEFAULT 0,
    materials_viewed INT NOT NULL DEFAULT 0,
    forum_posts      INT NOT NULL DEFAULT 0,
    minutes_online   INT NOT NULL DEFAULT 0,
    UNIQUE (student_id, offering_id, week_no)
);

CREATE TABLE model_versions (
    id          SERIAL PRIMARY KEY,
    version     VARCHAR(30) NOT NULL UNIQUE,
    trained_at  TIMESTAMPTZ NOT NULL,
    metrics     JSONB,                           -- accuracy, AUC, F1 ...
    description TEXT
);

-- features must use only PUBLISHED grades
CREATE TABLE risk_predictions (
    id               SERIAL PRIMARY KEY,
    student_id       INT NOT NULL REFERENCES students(user_id),
    offering_id      INT NOT NULL REFERENCES course_offerings(id),
    week_no          SMALLINT NOT NULL,
    model_id         INT NOT NULL REFERENCES model_versions(id),
    risk_probability NUMERIC(5,4) NOT NULL CHECK (risk_probability BETWEEN 0 AND 1),
    risk_level       VARCHAR(6) NOT NULL CHECK (risk_level IN ('low','medium','high')),
    predicted_score_low  NUMERIC(5,2),
    predicted_score_high NUMERIC(5,2),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (student_id, offering_id, week_no, model_id)
);
CREATE INDEX idx_predictions_offering_week ON risk_predictions (offering_id, week_no, risk_level);

CREATE TABLE prediction_explanations (          -- SHAP factors in plain language
    id            SERIAL PRIMARY KEY,
    prediction_id INT NOT NULL REFERENCES risk_predictions(id) ON DELETE CASCADE,
    feature       VARCHAR(60) NOT NULL,
    impact        NUMERIC(6,4) NOT NULL,         -- >0 raises risk (red), <0 lowers (green)
    text_kk       TEXT,
    text_ru       TEXT,
    text_en       TEXT
);

CREATE TABLE recommendations (
    id          SERIAL PRIMARY KEY,
    student_id  INT NOT NULL REFERENCES students(user_id),
    offering_id INT REFERENCES course_offerings(id),
    priority    SMALLINT NOT NULL DEFAULT 3,
    text        VARCHAR(300) NOT NULL,
    is_done     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE student_risk_overall (             -- used ONLY on the Advising page
    id          SERIAL PRIMARY KEY,
    student_id  INT NOT NULL REFERENCES students(user_id),
    semester_id INT NOT NULL REFERENCES semesters(id),
    week_no     SMALLINT NOT NULL,
    risk_probability NUMERIC(5,4) NOT NULL CHECK (risk_probability BETWEEN 0 AND 1),
    risk_level  VARCHAR(6) NOT NULL CHECK (risk_level IN ('low','medium','high')),
    method      VARCHAR(60) NOT NULL,            -- e.g. 'max_over_courses'
    UNIQUE (student_id, semester_id, week_no)
);

CREATE TABLE course_risk_snapshots (            -- fast charts for Class Insights
    id           SERIAL PRIMARY KEY,
    offering_id  INT NOT NULL REFERENCES course_offerings(id),
    week_no      SMALLINT NOT NULL,
    low_count    INT NOT NULL DEFAULT 0,
    medium_count INT NOT NULL DEFAULT 0,
    high_count   INT NOT NULL DEFAULT 0,
    avg_risk     NUMERIC(5,4),
    UNIQUE (offering_id, week_no)
);

-- ---------------------------------------------------------------------
-- I. ADVISING, INTERVENTIONS, OFFICE HOURS
-- ---------------------------------------------------------------------
CREATE TABLE advisor_assignments (              -- advisor = a teacher with an active row
    id          SERIAL PRIMARY KEY,
    advisor_id  INT NOT NULL REFERENCES teachers(user_id),
    student_id  INT NOT NULL REFERENCES students(user_id),
    starts_on   DATE NOT NULL DEFAULT CURRENT_DATE,
    ends_on     DATE,                            -- NULL = active; never delete rows
    assigned_by INT REFERENCES users(id),
    CHECK (ends_on IS NULL OR ends_on >= starts_on)
);
CREATE INDEX idx_advisor_active ON advisor_assignments (advisor_id, student_id);

CREATE TABLE interventions (
    id            SERIAL PRIMARY KEY,
    student_id    INT NOT NULL REFERENCES students(user_id),
    offering_id   INT REFERENCES course_offerings(id),     -- NULL for advising scope
    author_id     INT NOT NULL REFERENCES teachers(user_id),
    kind          VARCHAR(10) NOT NULL CHECK (kind IN ('message','meeting','referral','other')),
    scope         VARCHAR(10) NOT NULL DEFAULT 'course' CHECK (scope IN ('course','advising')),
    summary       TEXT NOT NULL,
    outcome       TEXT,
    recheck_on    DATE,
    prediction_id INT REFERENCES risk_predictions(id),     -- forecast that triggered it
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE office_hour_slots (
    id         SERIAL PRIMARY KEY,
    teacher_id INT NOT NULL REFERENCES teachers(user_id),
    starts_at  TIMESTAMPTZ NOT NULL,
    ends_at    TIMESTAMPTZ NOT NULL,
    room_id    INT REFERENCES rooms(id),
    capacity   SMALLINT NOT NULL DEFAULT 1,
    CHECK (ends_at > starts_at)
);
CREATE TABLE appointments (
    id         SERIAL PRIMARY KEY,
    slot_id    INT NOT NULL REFERENCES office_hour_slots(id) ON DELETE CASCADE,
    student_id INT NOT NULL REFERENCES students(user_id),
    topic      VARCHAR(200),
    status     VARCHAR(10) NOT NULL DEFAULT 'requested'
               CHECK (status IN ('requested','accepted','declined','rescheduled','done')),
    notes      TEXT,
    UNIQUE (slot_id, student_id)
);

CREATE TABLE access_log (                       -- advisor opened data from other courses
    id         BIGSERIAL PRIMARY KEY,
    teacher_id INT NOT NULL REFERENCES teachers(user_id),
    student_id INT NOT NULL REFERENCES students(user_id),
    page       VARCHAR(60) NOT NULL,
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- J. STUDENT TOOLS, AI ASSISTANT, DOCUMENTS
-- ---------------------------------------------------------------------
CREATE TABLE student_goals (                    -- "Goal" card on Performance
    student_id   INT NOT NULL REFERENCES students(user_id),
    offering_id  INT NOT NULL REFERENCES course_offerings(id),
    target_grade VARCHAR(3) NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (student_id, offering_id)
);

CREATE TABLE calendar_events (                  -- personal reminders
    id         SERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      VARCHAR(200) NOT NULL,
    starts_at  TIMESTAMPTZ NOT NULL,
    ends_at    TIMESTAMPTZ,
    note       TEXT
);

CREATE TABLE study_planner_tasks (                      -- Study Planner board
    id          SERIAL PRIMARY KEY,
    student_id  INT NOT NULL REFERENCES students(user_id) ON DELETE CASCADE,
    offering_id INT REFERENCES course_offerings(id),
    assessment_id INT REFERENCES assessments(id),
    title       VARCHAR(200) NOT NULL,
    column_name VARCHAR(12) NOT NULL DEFAULT 'this_week' CHECK (column_name IN ('this_week','in_progress','done')),
    due_on      DATE
);

CREATE TABLE chat_sessions (                    -- AI assistant
    id         SERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE chat_messages (
    id         BIGSERIAL PRIMARY KEY,
    session_id INT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    sender     VARCHAR(10) NOT NULL CHECK (sender IN ('user','assistant')),
    body       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE document_requests (                -- certificates etc. (can be a stub)
    id         SERIAL PRIMARY KEY,
    student_id INT NOT NULL REFERENCES students(user_id),
    doc_type   VARCHAR(60) NOT NULL,
    status     VARCHAR(12) NOT NULL DEFAULT 'new' CHECK (status IN ('new','processing','ready','rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE library_resources (
    id          SERIAL PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    url         TEXT NOT NULL,
    description TEXT,
    category    VARCHAR(60)
);

CREATE TABLE faq_items (
    id         SERIAL PRIMARY KEY,
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    language   VARCHAR(2) NOT NULL DEFAULT 'ru' CHECK (language IN ('kk','ru','en')),
    sort_order INT NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------
-- K. ACCESS RULES: FUNCTIONS, VIEWS, TRIGGERS
-- ---------------------------------------------------------------------

-- teacher sees an offering if responsible teacher or in offering_staff
CREATE FUNCTION teaches(p_teacher INT, p_offering INT) RETURNS BOOLEAN AS $$
    SELECT EXISTS (SELECT 1 FROM course_offerings WHERE id = p_offering AND teacher_id = p_teacher)
        OR EXISTS (SELECT 1 FROM offering_staff WHERE offering_id = p_offering AND teacher_id = p_teacher);
$$ LANGUAGE sql STABLE;

-- teacher sees a student as advisor only while the assignment is active
CREATE FUNCTION advises(p_teacher INT, p_student INT) RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM advisor_assignments
        WHERE advisor_id = p_teacher AND student_id = p_student
          AND starts_on <= CURRENT_DATE
          AND (ends_on IS NULL OR ends_on >= CURRENT_DATE));
$$ LANGUAGE sql STABLE;

-- the application must read student grades ONLY through this view
CREATE VIEW student_visible_grades AS
    SELECT g.* FROM grades g WHERE g.status = 'published';

-- teachers get ONLY these aggregates, never feedback_responses directly
CREATE VIEW feedback_results AS
    SELECT s.offering_id,
           COUNT(*)                          AS answers,
           AVG(r.rating_content)::NUMERIC(3,2)      AS avg_content,
           AVG(r.rating_teaching)::NUMERIC(3,2)     AS avg_teaching,
           AVG(r.rating_materials)::NUMERIC(3,2)    AS avg_materials,
           AVG(r.rating_assessment)::NUMERIC(3,2)   AS avg_assessment,
           AVG(r.rating_availability)::NUMERIC(3,2) AS avg_availability
    FROM feedback_responses r
    JOIN feedback_surveys s ON s.id = r.survey_id
    GROUP BY s.offering_id
    HAVING COUNT(*) >= 5;

-- comments without date, only when there are at least 5 answers
CREATE VIEW feedback_comments_anon AS
    SELECT s.offering_id, r.comment
    FROM feedback_responses r
    JOIN feedback_surveys s ON s.id = r.survey_id
    WHERE r.comment IS NOT NULL
      AND (SELECT COUNT(*) FROM feedback_responses x WHERE x.survey_id = r.survey_id) >= 5;

-- grade_audit_log is append-only
CREATE FUNCTION forbid_audit_change() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'grade_audit_log is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_no_update_delete
    BEFORE UPDATE OR DELETE ON grade_audit_log
    FOR EACH ROW EXECUTE FUNCTION forbid_audit_change();

-- every grade change is written to the log automatically
CREATE FUNCTION log_grade_change() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' OR OLD.score IS DISTINCT FROM NEW.score OR OLD.status IS DISTINCT FROM NEW.status THEN
        INSERT INTO grade_audit_log (grade_id, changed_by, old_score, new_score, old_status, new_status)
        VALUES (NEW.id,
                COALESCE(NEW.graded_by, (SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1)),
                CASE WHEN TG_OP = 'UPDATE' THEN OLD.score END, NEW.score,
                CASE WHEN TG_OP = 'UPDATE' THEN OLD.status END, NEW.status);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_grades_audit
    AFTER INSERT OR UPDATE ON grades
    FOR EACH ROW EXECUTE FUNCTION log_grade_change();

-- check: category weights of an offering sum to exactly 100
-- usage: SELECT * FROM offerings_with_bad_weights;  (must be empty)
CREATE VIEW offerings_with_bad_weights AS
    SELECT offering_id, SUM(weight_pct) AS total
    FROM assessment_categories
    GROUP BY offering_id
    HAVING SUM(weight_pct) <> 100;
