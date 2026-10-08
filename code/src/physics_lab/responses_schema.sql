-- responses_schema.sql — 응답 DB: 응시 기록 · 보기별 응답 · 시험지 · 과제 · 진단 결과
-- 개인정보는 계정 DB 에만 둔다. 여기는 시스템이 만든 익명 ID 만 쓴다.
-- 보기별 응답은 판단함 / 모르겠다 / 무응답 세 상태. 응답마다 목적(시험 · 연습 · 과제)과 입력 형식을 남긴다.
-- 잘못된 데이터는 CHECK · FK 제약으로 입력 시점에 막는다. DROP 이 없어 다시 실행해도 데이터가 안 지워진다.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

INSERT OR IGNORE INTO meta (key, value, updated_at)
VALUES ('schema_version', '6', '2026-10-07T00:00:00Z');

CREATE TABLE IF NOT EXISTS students (
    student_id  TEXT PRIMARY KEY,
    consent     INTEGER NOT NULL DEFAULT 0
                CHECK (consent IN (0, 1)),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exam_sets (
    exam_set_id     TEXT PRIMARY KEY,
    class_id        TEXT NOT NULL,
    title           TEXT NOT NULL,
    round_no        INTEGER,

    mode            TEXT NOT NULL DEFAULT 'diagnostic'
                    CHECK (mode IN ('diagnostic', 'realistic')),

    created_by      TEXT,
    created_at      TEXT NOT NULL,
    opened_at       TEXT,
    closed_at       TEXT,
    administered_at TEXT,
    note            TEXT
);

CREATE INDEX IF NOT EXISTS ix_exam_sets_class ON exam_sets (class_id, round_no);

CREATE TABLE IF NOT EXISTS exam_items (
    exam_set_id  TEXT NOT NULL REFERENCES exam_sets (exam_set_id),
    item_key     TEXT NOT NULL,
    seq          INTEGER NOT NULL,

    input_format TEXT NOT NULL DEFAULT 'per_statement'
                 CHECK (input_format IN ('per_statement', 'choice', 'short')),
    note         TEXT,

    PRIMARY KEY (exam_set_id, item_key),
    UNIQUE (exam_set_id, seq)
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id   TEXT PRIMARY KEY,
    student_id   TEXT NOT NULL REFERENCES students (student_id),

    purpose      TEXT NOT NULL
                 CHECK (purpose IN ('exam', 'homework', 'practice', 'pilot')),
    exam_set_id  TEXT REFERENCES exam_sets (exam_set_id),

    device       TEXT,
    viewport     TEXT,
    orientation  TEXT
                 CHECK (orientation IS NULL OR orientation IN ('landscape', 'portrait')),

    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    note         TEXT,

    CHECK (purpose NOT IN ('exam', 'pilot') OR exam_set_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ix_attempts_student ON attempts (student_id);
CREATE INDEX IF NOT EXISTS ix_attempts_exam    ON attempts (exam_set_id);
CREATE INDEX IF NOT EXISTS ix_attempts_started ON attempts (started_at);

CREATE TABLE IF NOT EXISTS responses (
    attempt_id     TEXT NOT NULL REFERENCES attempts (attempt_id),
    item_key       TEXT NOT NULL,
    seq            INTEGER NOT NULL,

    source         TEXT NOT NULL
                   CHECK (source IN ('exam_set', 'assigned',
                                     'recommended', 'self_selected')),
    target_concept      TEXT,

    input_format   TEXT NOT NULL DEFAULT 'per_statement'
                   CHECK (input_format IN ('per_statement', 'choice', 'short')),
    capture_method TEXT NOT NULL DEFAULT 'app'
                   CHECK (capture_method IN ('app', 'transcribed', 'photo')),

    choice_no      INTEGER
                   CHECK (choice_no IS NULL OR choice_no BETWEEN 1 AND 5),
    choice_source  TEXT
                   CHECK (choice_source IS NULL OR choice_source IN ('given', 'derived')),
    answer_text    TEXT,

    elapsed_ms     INTEGER,
    focus_lost_ms  INTEGER,
    scroll_px      INTEGER,

    shown_at       TEXT,
    answered_at    TEXT,

    PRIMARY KEY (attempt_id, item_key),
    UNIQUE (attempt_id, seq),

    CHECK (capture_method = 'app' OR elapsed_ms IS NULL),

    CHECK (choice_no IS NULL OR choice_source IS NOT NULL),

    CHECK (choice_source IS NULL
           OR (input_format = 'choice'        AND choice_source = 'given')
           OR (input_format IN ('per_statement', 'short') AND choice_source = 'derived')),

    CHECK (answer_text IS NULL OR input_format = 'short')
);

CREATE INDEX IF NOT EXISTS ix_responses_item   ON responses (item_key);
CREATE INDEX IF NOT EXISTS ix_responses_source ON responses (source);

CREATE TABLE IF NOT EXISTS statement_responses (
    attempt_id   TEXT NOT NULL,
    item_key     TEXT NOT NULL,
    label        TEXT NOT NULL,

    judged_true  INTEGER
                 CHECK (judged_true IS NULL OR judged_true IN (0, 1)),
    unsure       INTEGER NOT NULL DEFAULT 0
                 CHECK (unsure IN (0, 1)),

    answered_at  TEXT,
    changed_cnt  INTEGER NOT NULL DEFAULT 0,

    PRIMARY KEY (attempt_id, item_key, label),
    FOREIGN KEY (attempt_id, item_key)
        REFERENCES responses (attempt_id, item_key),

    CHECK (unsure = 0 OR judged_true IS NULL)
);

CREATE INDEX IF NOT EXISTS ix_stmt_resp_item ON statement_responses (item_key, label);

CREATE TABLE IF NOT EXISTS diagnoses (
    diagnosis_id     TEXT PRIMARY KEY,
    attempt_id       TEXT NOT NULL REFERENCES attempts (attempt_id),

    engine        TEXT NOT NULL,
    concept_map_version  TEXT NOT NULL,

    created_at       TEXT NOT NULL,
    shown_to_student INTEGER NOT NULL DEFAULT 0
                     CHECK (shown_to_student IN (0, 1))
);

CREATE INDEX IF NOT EXISTS ix_diagnoses_attempt ON diagnoses (attempt_id);

CREATE TABLE IF NOT EXISTS diagnosis_concept (
    diagnosis_id  TEXT NOT NULL REFERENCES diagnoses (diagnosis_id),
    concept            TEXT NOT NULL,

    diagnosis       REAL,
    n_units       INTEGER NOT NULL,
    verdict       TEXT NOT NULL
                  CHECK (verdict IN ('mastered', 'not_mastered', 'insufficient')),

    PRIMARY KEY (diagnosis_id, concept)
);

CREATE INDEX IF NOT EXISTS ix_diagnosis_concept_concept ON diagnosis_concept (concept);

CREATE TABLE IF NOT EXISTS assignments (
    assignment_id     TEXT PRIMARY KEY,
    student_id        TEXT NOT NULL REFERENCES students (student_id),
    item_key          TEXT NOT NULL,

    target_concept         TEXT,
    from_diagnosis_id TEXT REFERENCES diagnoses (diagnosis_id),

    assigned_by       TEXT NOT NULL
                      CHECK (assigned_by IN ('teacher', 'system')),
    assigned_at       TEXT NOT NULL,
    due_at            TEXT,

    status            TEXT NOT NULL DEFAULT 'assigned'
                      CHECK (status IN ('assigned', 'done', 'skipped')),

    UNIQUE (student_id, item_key, assigned_at)
);

CREATE INDEX IF NOT EXISTS ix_assignments_student ON assignments (student_id, status);
CREATE INDEX IF NOT EXISTS ix_assignments_concept      ON assignments (target_concept);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id TEXT PRIMARY KEY,
    attempt_id  TEXT REFERENCES attempts (attempt_id),
    item_key    TEXT,

    kind        TEXT NOT NULL
                CHECK (kind IN ('pre_guess',
                                'validity_1_5',
                                'usefulness_1_5',
                                'why_wrong',
                                'free')),
    value_num   INTEGER,
    value_text  TEXT,
    created_at  TEXT NOT NULL,

    CHECK (value_num IS NULL OR value_num BETWEEN 1 AND 5),
    CHECK (kind NOT IN ('validity_1_5', 'usefulness_1_5')
           OR value_num IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ix_feedback_attempt ON feedback (attempt_id);
