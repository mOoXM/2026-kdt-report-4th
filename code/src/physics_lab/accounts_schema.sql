-- accounts_schema.sql — 계정 DB: 사용자 · 학원 · 반 · 명단 · 세션 · 초대
-- 모든 사용자는 시스템이 만든 user_id 로 식별한다. 실명 등 개인정보는 이 DB 에만 있다.
-- 비밀번호 · 세션 토큰 · 초대 토큰은 원문을 저장하지 않는다 (해시만).

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

INSERT OR IGNORE INTO meta (key, value, updated_at)
VALUES ('schema_version', '1', '2026-09-28T00:00:00Z');

CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,
    kind            TEXT NOT NULL
                    CHECK (kind IN ('student', 'teacher', 'guest')),
    login_key       TEXT UNIQUE,
    email           TEXT UNIQUE,
    email_verified  INTEGER NOT NULL DEFAULT 0
                    CHECK (email_verified IN (0, 1)),
    display_name    TEXT,
    is_admin        INTEGER NOT NULL DEFAULT 0
                    CHECK (is_admin IN (0, 1)),
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'disabled')),
    expires_at      TEXT,
    issued_by_org   TEXT REFERENCES orgs (org_id),
    created_at      TEXT NOT NULL,

    CHECK ((kind = 'teacher' AND email IS NOT NULL)
        OR (kind IN ('student', 'guest') AND login_key IS NOT NULL)),
    CHECK (kind = 'guest' OR expires_at IS NULL)
);

CREATE INDEX IF NOT EXISTS ix_users_kind ON users (kind);

CREATE TABLE IF NOT EXISTS credentials (
    user_id         TEXT PRIMARY KEY REFERENCES users (user_id),
    password_hash   TEXT NOT NULL,
    must_change     INTEGER NOT NULL DEFAULT 0
                    CHECK (must_change IN (0, 1)),
    failed_count    INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_hash    TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users (user_id),
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    last_seen_at    TEXT,
    user_agent      TEXT
);

CREATE INDEX IF NOT EXISTS ix_sessions_user    ON sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_sessions_expires ON sessions (expires_at);

CREATE TABLE IF NOT EXISTS orgs (
    org_id          TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'active', 'disabled')),
    created_at      TEXT NOT NULL,
    note            TEXT
);

CREATE TABLE IF NOT EXISTS org_members (
    org_id          TEXT NOT NULL REFERENCES orgs (org_id),
    user_id         TEXT NOT NULL REFERENCES users (user_id),
    role            TEXT NOT NULL
                    CHECK (role IN ('owner', 'teacher')),
    joined_at       TEXT NOT NULL,
    left_at         TEXT,

    PRIMARY KEY (org_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_org_members_user ON org_members (user_id);

CREATE TABLE IF NOT EXISTS invites (
    token_hash      TEXT PRIMARY KEY,
    org_id          TEXT NOT NULL REFERENCES orgs (org_id),
    email           TEXT,
    role            TEXT NOT NULL DEFAULT 'teacher'
                    CHECK (role IN ('teacher')),
    created_by      TEXT NOT NULL REFERENCES users (user_id),
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    used_by         TEXT REFERENCES users (user_id),
    used_at         TEXT
);

CREATE INDEX IF NOT EXISTS ix_invites_org ON invites (org_id);

CREATE TABLE IF NOT EXISTS classes (
    class_id        TEXT PRIMARY KEY,
    org_id          TEXT NOT NULL REFERENCES orgs (org_id),
    teacher_id      TEXT REFERENCES users (user_id),
    name            TEXT NOT NULL,
    subject         TEXT NOT NULL DEFAULT 'ph1',
    created_at      TEXT NOT NULL,
    archived_at     TEXT
);

CREATE INDEX IF NOT EXISTS ix_classes_org     ON classes (org_id);
CREATE INDEX IF NOT EXISTS ix_classes_teacher ON classes (teacher_id);

CREATE TABLE IF NOT EXISTS class_members (
    class_id        TEXT NOT NULL REFERENCES classes (class_id),
    user_id         TEXT NOT NULL REFERENCES users (user_id),
    display_name    TEXT NOT NULL,
    school          TEXT,
    entry_year      INTEGER
                    CHECK (entry_year IS NULL OR entry_year BETWEEN 2000 AND 2100),
    phone           TEXT,
    joined_at       TEXT NOT NULL,
    left_at         TEXT,
    note            TEXT,

    PRIMARY KEY (class_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_class_members_user ON class_members (user_id);
