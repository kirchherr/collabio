-- 0024_knowledge_base_write_approval_transition_lineage.sql
-- Adds append-only lineage for Knowledge Base write-approval state transitions.

ALTER TABLE knowledge_base.write_approval_evidence
    ADD COLUMN IF NOT EXISTS transition_source_evidence_hash text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'kb_write_approval_transition_source_hash_format'
    ) THEN
        ALTER TABLE knowledge_base.write_approval_evidence
            ADD CONSTRAINT kb_write_approval_transition_source_hash_format
            CHECK (
                transition_source_evidence_hash IS NULL
                OR transition_source_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'kb_write_approval_transition_source_required'
    ) THEN
        ALTER TABLE knowledge_base.write_approval_evidence
            ADD CONSTRAINT kb_write_approval_transition_source_required
            CHECK (
                (
                    approval_state = 'dry_run'
                    AND transition_source_evidence_hash IS NULL
                )
                OR (
                    approval_state <> 'dry_run'
                    AND transition_source_evidence_hash IS NOT NULL
                    AND transition_source_evidence_hash <> evidence_hash
                )
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS kb_write_approval_evidence_transition_source_idx
    ON knowledge_base.write_approval_evidence (
        tenant_id,
        transition_source_evidence_hash,
        approval_state
    );
