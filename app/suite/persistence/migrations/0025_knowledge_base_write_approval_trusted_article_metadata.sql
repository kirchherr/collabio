-- 0025_knowledge_base_write_approval_trusted_article_metadata.sql
-- Pins Knowledge Base create metadata into the append-only approval ledger before execution.

ALTER TABLE knowledge_base.write_approval_evidence
    ADD COLUMN IF NOT EXISTS article_key text NOT NULL DEFAULT 'legacy-untrusted',
    ADD COLUMN IF NOT EXISTS title text NOT NULL DEFAULT 'Legacy untrusted knowledge base write',
    ADD COLUMN IF NOT EXISTS proposed_version_label text NOT NULL DEFAULT 'legacy-untrusted',
    ADD COLUMN IF NOT EXISTS source_system text NOT NULL DEFAULT 'legacy';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'kb_write_approval_article_key_not_empty'
    ) THEN
        ALTER TABLE knowledge_base.write_approval_evidence
            ADD CONSTRAINT kb_write_approval_article_key_not_empty
            CHECK (article_key <> '');
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'kb_write_approval_title_not_empty'
    ) THEN
        ALTER TABLE knowledge_base.write_approval_evidence
            ADD CONSTRAINT kb_write_approval_title_not_empty
            CHECK (title <> '');
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'kb_write_approval_proposed_version_label_not_empty'
    ) THEN
        ALTER TABLE knowledge_base.write_approval_evidence
            ADD CONSTRAINT kb_write_approval_proposed_version_label_not_empty
            CHECK (proposed_version_label <> '');
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'kb_write_approval_source_system_format'
    ) THEN
        ALTER TABLE knowledge_base.write_approval_evidence
            ADD CONSTRAINT kb_write_approval_source_system_format
            CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$');
    END IF;
END
$$;

COMMENT ON COLUMN knowledge_base.write_approval_evidence.article_key IS
    'Trusted article key captured at approval time so create execution does not trust caller-supplied article metadata.';

COMMENT ON COLUMN knowledge_base.write_approval_evidence.title IS
    'Trusted article title captured at approval time; article bodies and source text remain excluded from the ledger.';

COMMENT ON COLUMN knowledge_base.write_approval_evidence.proposed_version_label IS
    'Trusted proposed article-version label captured before execution.';

COMMENT ON COLUMN knowledge_base.write_approval_evidence.source_system IS
    'Trusted source-system identifier captured before create execution.';

CREATE INDEX IF NOT EXISTS kb_write_approval_evidence_article_key_idx
    ON knowledge_base.write_approval_evidence (tenant_id, article_key, approval_state);

CREATE INDEX IF NOT EXISTS kb_write_approval_evidence_source_system_idx
    ON knowledge_base.write_approval_evidence (tenant_id, source_system, approval_state);
