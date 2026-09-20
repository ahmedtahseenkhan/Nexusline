"""Phase 4E schema: the questionnaire engine.

New tables (created from metadata): sections, portal links and the portal access log.
Column additions on questionnaires / questions / options / assessments / answers /
findings, vendors (due-diligence rating) and rcsa_risks (control self-rating).

Backfill, safe to re-run (every UPDATE only touches rows still in their pre-4E shape):

* every existing questionnaire becomes **version 1, published** of its own family
  (``family_id = id``) — existing assessments already point at it, so they are pinned;
* the seeded "Inherent risk tiering" questionnaire gets ``purpose = vendor_tiering``,
  its bands (70 / 45 / 20 %) and mandatory questions;
* each questionnaire without sections gets one "Questions" section holding its questions;
* questions and options get stable keys (``q`` / ``o`` + the first ten hex digits of
  their id) so conditions can refer to them;
* existing answers keep their single option; nothing is deleted;
* the unused ``assessments.access_hash`` is blanked (it was exposed by the old read schema).
"""
from __future__ import annotations

TABLES: tuple[str, ...] = ("questionnaire_sections", "assessment_links", "assessment_access_logs")

#: (table, column, DDL type/default)
COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("questionnaires", "family_id", "UUID"),
    ("questionnaires", "version", "INTEGER NOT NULL DEFAULT 1"),
    # Existing rows were usable questionnaires: they become published. New rows default
    # to draft (the default is switched below, after the column exists).
    ("questionnaires", "status", "VARCHAR(16) NOT NULL DEFAULT 'published'"),
    ("questionnaires", "purpose", "VARCHAR(40) NOT NULL DEFAULT 'general'"),
    ("questionnaires", "bands", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
    ("questionnaires", "change_note", "TEXT NOT NULL DEFAULT ''"),
    ("questionnaires", "published_at", "TIMESTAMPTZ"),
    ("questionnaires", "origin", "VARCHAR(24) NOT NULL DEFAULT 'tenant'"),
    ("questionnaires", "library_key", "VARCHAR(80) NOT NULL DEFAULT ''"),
    ("questionnaires", "library_version", "INTEGER"),
    ("questions", "key", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("questions", "qtype", "VARCHAR(24) NOT NULL DEFAULT 'single_choice'"),
    ("questions", "mandatory", "BOOLEAN NOT NULL DEFAULT false"),
    ("questions", "weight", "DOUBLE PRECISION NOT NULL DEFAULT 1"),
    ("questions", "conditions", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
    ("questions", "config", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
    ("question_options", "value", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("question_options", "is_na", "BOOLEAN NOT NULL DEFAULT false"),
    ("question_options", "risk_flag", "BOOLEAN NOT NULL DEFAULT false"),
    ("question_options", "finding_title", "VARCHAR(255) NOT NULL DEFAULT ''"),
    ("question_options", "finding_severity", "VARCHAR(16) NOT NULL DEFAULT 'medium'"),
    ("assessments", "contact_name", "VARCHAR(200) NOT NULL DEFAULT ''"),
    ("assessments", "contact_email", "VARCHAR(255) NOT NULL DEFAULT ''"),
    ("assessments", "sent_at", "TIMESTAMPTZ"),
    ("assessments", "reviewed_at", "TIMESTAMPTZ"),
    ("assessments", "submitted_by", "VARCHAR(255) NOT NULL DEFAULT ''"),
    ("assessments", "result_score", "DOUBLE PRECISION"),
    ("assessments", "result_max", "DOUBLE PRECISION"),
    ("assessments", "result_pct", "DOUBLE PRECISION"),
    ("assessments", "result_band", "VARCHAR(80) NOT NULL DEFAULT ''"),
    ("assessments", "result_rating", "VARCHAR(16)"),
    ("assessments", "scored_at", "TIMESTAMPTZ"),
    ("assessments", "recurrence_months", "INTEGER"),
    ("assessments", "next_issue_on", "DATE"),
    ("assessments", "last_reminder_on", "DATE"),
    ("assessments", "overdue_alerted_on", "DATE"),
    ("assessment_answers", "option_ids", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
    ("assessment_answers", "value_text", "TEXT NOT NULL DEFAULT ''"),
    ("assessment_answers", "value_number", "DOUBLE PRECISION"),
    ("assessment_answers", "value_date", "DATE"),
    ("assessment_answers", "not_applicable", "BOOLEAN NOT NULL DEFAULT false"),
    ("assessment_answers", "review_state", "VARCHAR(16) NOT NULL DEFAULT 'pending'"),
    ("assessment_answers", "review_comment", "TEXT NOT NULL DEFAULT ''"),
    ("assessment_answers", "reviewed_at", "TIMESTAMPTZ"),
    ("assessment_answers", "answered_by", "VARCHAR(255) NOT NULL DEFAULT ''"),
    ("assessment_answers", "answered_at", "TIMESTAMPTZ"),
    ("assessment_findings", "question_key", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("assessment_findings", "option_value", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("assessment_findings", "auto_raised", "BOOLEAN NOT NULL DEFAULT false"),
    ("vendors", "risk_rating_override_reason", "TEXT NOT NULL DEFAULT ''"),
    ("vendors", "last_due_diligence_on", "DATE"),
    ("vendors", "next_due_diligence_on", "DATE"),
    ("rcsa_risks", "self_design_rating", "VARCHAR(24)"),
    ("rcsa_risks", "self_operation_rating", "VARCHAR(24)"),
)

#: (table, column, referenced table, ON DELETE)
FK_COLUMNS: tuple[tuple[str, str, str, str], ...] = (
    ("questionnaires", "published_by_id", "users", "SET NULL"),
    ("questions", "section_id", "questionnaire_sections", "CASCADE"),
    ("assessments", "sent_by_id", "users", "SET NULL"),
    ("assessments", "reviewer_id", "users", "SET NULL"),
    ("assessments", "reviewed_by_id", "users", "SET NULL"),
    ("assessments", "parent_assessment_id", "assessments", "SET NULL"),
    ("assessments", "rcsa_assessment_id", "rcsa_assessments", "SET NULL"),
    ("assessment_answers", "reviewed_by_id", "users", "SET NULL"),
    ("assessment_findings", "answer_id", "assessment_answers", "SET NULL"),
    ("assessment_findings", "issue_id", "issues", "SET NULL"),
    ("rcsa_risks", "self_assessment_id", "assessments", "SET NULL"),
)

_POLICY = "tenant_isolation"
_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"

TIERING_BANDS_JSON = (
    '[{"label": "Critical", "min_pct": 70, "rating": "critical"}, '
    '{"label": "High", "min_pct": 45, "rating": "high"}, '
    '{"label": "Medium", "min_pct": 20, "rating": "medium"}, '
    '{"label": "Low", "min_pct": 0, "rating": "low"}]'
)


def backfill_statements() -> list[str]:
    return [
        # 1. Every pre-4E questionnaire is version 1 of its own family.
        "UPDATE questionnaires SET family_id = id WHERE family_id IS NULL",
        "UPDATE questionnaires SET published_at = COALESCE(published_at, created_at) "
        "WHERE status = 'published' AND published_at IS NULL",
        # 2. The seeded tiering questionnaire is recognised by purpose from now on.
        "UPDATE questionnaires SET purpose = 'vendor_tiering' "
        "WHERE purpose = 'general' AND lower(regexp_replace(btrim(name), '\\s+', ' ', 'g')) = 'inherent risk tiering'",
        f"UPDATE questionnaires SET bands = '{TIERING_BANDS_JSON}'::jsonb "
        "WHERE purpose = 'vendor_tiering' AND bands = '[]'::jsonb",
        "UPDATE questions SET mandatory = true WHERE mandatory = false AND questionnaire_id IN "
        "(SELECT id FROM questionnaires WHERE purpose = 'vendor_tiering' AND status = 'published' "
        "AND origin = 'tenant' AND library_key = '') AND NOT EXISTS "
        "(SELECT 1 FROM questionnaire_sections s WHERE s.questionnaire_id = questions.questionnaire_id)",
        # 3. Stable keys.
        "UPDATE questions SET key = 'q' || substr(replace(id::text, '-', ''), 1, 10) WHERE key = ''",
        "UPDATE question_options SET value = 'o' || substr(replace(id::text, '-', ''), 1, 10) WHERE value = ''",
        # 4. One section per questionnaire that has none, holding its unsectioned questions.
        "INSERT INTO questionnaire_sections (id, tenant_id, questionnaire_id, key, title, description, "
        "order_index, conditions, created_at, updated_at) "
        "SELECT gen_random_uuid(), q.tenant_id, q.id, 'questions', 'Questions', '', 0, '{}'::jsonb, now(), now() "
        "FROM questionnaires q WHERE NOT EXISTS "
        "(SELECT 1 FROM questionnaire_sections s WHERE s.questionnaire_id = q.id)",
        "UPDATE questions SET section_id = (SELECT s.id FROM questionnaire_sections s "
        "WHERE s.questionnaire_id = questions.questionnaire_id ORDER BY s.order_index LIMIT 1) "
        "WHERE section_id IS NULL",
        # 5. The old access hash was never used and was exposed on read.
        "UPDATE assessments SET access_hash = '' WHERE access_hash <> ''",
        # 6. Answers given before per-answer review are treated as accepted once reviewed.
        "UPDATE assessment_answers SET review_state = 'accepted' WHERE review_state = 'pending' "
        "AND assessment_id IN (SELECT id FROM assessments WHERE status = 'reviewed' AND reviewed_at IS NULL)",
    ]


def ddl_statements() -> list[str]:
    statements: list[str] = []
    for table, col, ddl in COLUMNS:
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}")
    for table, col, target, on_delete in FK_COLUMNS:
        name = f"fk_{table}_{col}"[:63]
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} UUID")
        statements.append(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            f"WHERE conname = '{name}') THEN ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({col}) REFERENCES {target}(id) ON DELETE {on_delete} NOT VALID; "
            "END IF; END $$;"
        )
        statements.append(f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} ON {table} ({col})"[:200])
    statements.extend(backfill_statements())
    # New rows start as drafts (existing rows were set to published above).
    statements.append("ALTER TABLE questionnaires ALTER COLUMN status SET DEFAULT 'draft'")
    statements.append(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_questionnaires_family_version "
        "ON questionnaires (family_id, version)"
    )
    statements.append("CREATE INDEX IF NOT EXISTS ix_assessments_due_status ON assessments (status, due_date)")
    # Row-level security for the new tables (also listed in app/db/rls.py).
    for table in TABLES:
        statements.append(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        statements.append(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        statements.append(f"DROP POLICY IF EXISTS {_POLICY} ON {table}")
        statements.append(
            f"CREATE POLICY {_POLICY} ON {table} USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )
    return statements
