from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def read_doc(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_knowledge_base_docs_follow_module_implementation_contract() -> None:
    charter = read_doc("docs/modules/KNOWLEDGE_BASE_MODULE_CHARTER.md")
    slice_doc = read_doc("docs/modules/KNOWLEDGE_BASE_ARTICLES_VERTICAL_SLICE.md")
    evidence_doc = read_doc("docs/modules/KNOWLEDGE_BASE_SOURCE_RESTORE_EVIDENCE.md")
    ledger_doc = read_doc("docs/modules/KNOWLEDGE_BASE_WRITE_APPROVAL_LEDGER.md")

    for doc in (charter, slice_doc, evidence_doc, ledger_doc):
        assert "tenant context" in doc.lower()
        assert "legal hold" in doc.lower()
        assert "metadata-only" in doc.lower()

    for doc in (charter, slice_doc, evidence_doc):
        assert "restore" in doc.lower()
        assert "candidate" in doc.lower()
        assert "local llm gateway" in doc.lower()

    for doc in (charter, slice_doc, ledger_doc):
        assert "MODULE_IMPLEMENTATION_CONTRACT.md" in doc
        assert "backup" in doc.lower()
        assert "no hard" in doc.lower()
        assert "RLS" in doc

    assert "`knowledge_base`" in charter
    assert "`knowledge_base.articles.read`" in charter
    assert "`kb.article`" in charter
    assert "`kb.article_version`" in charter
    assert "`POST /v1/admin/kb/runtime/activate`" in charter
    assert "`POST /v1/admin/kb/runtime/reconcile`" in charter
    assert "`GET /v1/admin/kb/evidence`" in charter
    assert "`POST /v1/admin/kb/articles/write-dry-run`" in charter
    assert "`POST /v1/admin/kb/articles/write-approvals/approve`" in charter
    assert "`POST /v1/admin/kb/articles/write-approvals/refresh-preview`" in charter
    assert "`POST /v1/admin/kb/articles/write-approvals/execution-skeleton`" in charter
    assert "`POST /v1/admin/kb/articles/write-approvals/execute`" in charter
    assert "`projected_restore_evidence_preview_hash`" in charter
    assert "`execution_plan_hash`" in charter
    assert "`refreshed_restore_evidence_hash`" in charter
    assert "`source_object_write_receipt_hash`" in charter
    assert "`KnowledgeBaseWriteUnitOfWork`" in charter
    assert "`PostgresKnowledgeBaseWriteUnitOfWork`" in charter
    assert "`write_unit_of_work_committed=true`" in charter
    assert "`write_unit_of_work_contract`" in charter
    assert "`source_content_recovery_required=true`" in charter
    assert "`source_content_recovery_evidence_hash`" in charter
    assert "`production_write_deployment_gate_evidence_hash`" in charter
    assert "`knowledge_base_production_write_deployment_gate.v1`" in charter
    assert "`s3_compatible_provider_profile_evidence.v1`" in charter
    assert "`S3CompatibleSourceObjectContentStore`" in charter
    assert "`Boto3S3CompatibleObjectStoreClient`" in charter
    assert "`source_object_content_recovery_evidence.v1`" in charter
    assert "`api_wiring_allowed=true`" in charter
    assert "`execution_allowed=false`" in charter
    assert "`PgKnowledgeBaseArticleRepository`" in charter
    assert "`PgSourceObjectRepository`" in charter
    assert "Article bodies are not stored in the first slice" in charter
    assert "0022_knowledge_base_source_restore_evidence.sql" in charter
    assert "0023_knowledge_base_write_approval_evidence.sql" in charter
    assert "0024_knowledge_base_write_approval_transition_lineage.sql" in charter
    assert "0025_knowledge_base_write_approval_trusted_article_metadata.sql" in charter
    assert "0026_source_object_write_receipts.sql" in charter
    assert "0027_source_object_metadata_storage_bridge.sql" in charter
    assert "0028_knowledge_base_runtime_activation.sql" in charter
    assert "0029_knowledge_base_runtime_reconciliation.sql" in charter
    assert "current `kb.article_version`" in slice_doc
    assert "`GET /v1/admin/kb/evidence`" in slice_doc
    assert "`POST /v1/admin/kb/runtime/activate`" in slice_doc
    assert "`POST /v1/admin/kb/runtime/reconcile`" in slice_doc
    assert "`POST /v1/admin/kb/articles/write-dry-run`" in slice_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/approve`" in slice_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/refresh-preview`" in slice_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/execution-skeleton`" in slice_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/execute`" in slice_doc
    assert "`projected_restore_evidence_preview_hash`" in slice_doc
    assert "`execution_plan_hash`" in slice_doc
    assert "`refreshed_restore_evidence_hash`" in slice_doc
    assert "`source_object_write_receipt_hash`" in slice_doc
    assert "`KnowledgeBaseWriteUnitOfWork`" in slice_doc
    assert "`PostgresKnowledgeBaseWriteUnitOfWork`" in slice_doc
    assert "`source_object_content_recovery_evidence.v1`" in slice_doc
    assert "`source_content_recovery_evidence_hash`" in slice_doc
    assert "`production_write_deployment_gate_evidence_hash`" in slice_doc
    assert "`knowledge_base_production_write_deployment_gate.v1`" in slice_doc
    assert "`s3_compatible_provider_profile_evidence.v1`" in slice_doc
    assert "`S3CompatibleSourceObjectContentStore`" in slice_doc
    assert "`Boto3S3CompatibleObjectStoreClient`" in slice_doc
    assert "`api_wiring_allowed`" in slice_doc
    assert "`PgKnowledgeBaseArticleRepository`" in slice_doc
    assert "`PgSourceObjectRepository`" in slice_doc
    assert "source-version evidence hash" in slice_doc.lower()
    assert "`GET /v1/admin/kb/evidence`" in evidence_doc
    assert "`POST /v1/admin/kb/runtime/activate`" in evidence_doc
    assert "`POST /v1/admin/kb/runtime/reconcile`" in evidence_doc
    assert "`POST /v1/admin/kb/articles/write-dry-run`" in evidence_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/approve`" in evidence_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/refresh-preview`" in evidence_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/execution-skeleton`" in evidence_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/execute`" in evidence_doc
    assert "`projected_restore_evidence_preview_hash`" in evidence_doc
    assert "`execution_plan_hash`" in evidence_doc
    assert "`source_object_write_receipt_hash`" in evidence_doc
    assert "`KnowledgeBaseWriteUnitOfWork`" in evidence_doc
    assert "`PostgresKnowledgeBaseWriteUnitOfWork`" in evidence_doc
    assert "`source_object_content_recovery_evidence.v1`" in evidence_doc
    assert "`source_content_recovery_evidence_hash`" in evidence_doc
    assert "`production_write_deployment_gate_evidence_hash`" in evidence_doc
    assert "`knowledge_base_production_write_deployment_gate.v1`" in evidence_doc
    assert "`s3_compatible_provider_profile_evidence.v1`" in evidence_doc
    assert "`S3CompatibleSourceObjectContentStore`" in evidence_doc
    assert "`Boto3S3CompatibleObjectStoreClient`" in evidence_doc
    assert "source text out of audit metadata, receipts, and responses" in evidence_doc
    assert "`execution_allowed=false`" in evidence_doc
    assert "`PgKnowledgeBaseArticleRepository`" in evidence_doc
    assert "`PgSourceObjectRepository`" in evidence_doc
    assert "`knowledge_base.source_version_evidence`" in evidence_doc
    assert "`knowledge_base.restore_evidence`" in evidence_doc
    assert "Drift blocks the evidence build" in evidence_doc
    assert "`knowledge_base.write_approval_evidence`" in ledger_doc
    assert "`0023_knowledge_base_write_approval_evidence.sql`" in ledger_doc
    assert "`0024_knowledge_base_write_approval_transition_lineage.sql`" in ledger_doc
    assert "`0025_knowledge_base_write_approval_trusted_article_metadata.sql`" in ledger_doc
    assert "`0026_source_object_write_receipts.sql`" in ledger_doc
    assert "`transition_source_evidence_hash`" in ledger_doc
    assert "article key" in ledger_doc.lower()
    assert "proposed version label" in ledger_doc.lower()
    assert "source system" in ledger_doc.lower()
    assert "`POST /v1/admin/kb/articles/write-approvals/refresh-preview`" in ledger_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/execution-skeleton`" in ledger_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/execute`" in ledger_doc
    assert "`projected_restore_evidence_preview_hash`" in ledger_doc
    assert "`execution_plan_hash`" in ledger_doc
    assert "`source_object_write_receipt_hash`" in ledger_doc
    assert "`KnowledgeBaseWriteUnitOfWork`" in ledger_doc
    assert "`PostgresKnowledgeBaseWriteUnitOfWork`" in ledger_doc
    assert "`write_unit_of_work_committed=true`" in ledger_doc
    assert "`write_unit_of_work_contract`" in ledger_doc
    assert "shared PostgreSQL metadata transaction" in ledger_doc
    assert "`source_object_content_recovery_evidence.v1`" in ledger_doc
    assert "`source_content_recovery_evidence_hash`" in ledger_doc
    assert "`production_write_deployment_gate_evidence_hash`" in ledger_doc
    assert "`knowledge_base_production_write_deployment_gate.v1`" in ledger_doc
    assert "`s3_compatible_provider_profile_evidence.v1`" in ledger_doc
    assert "`S3CompatibleSourceObjectContentStore`" in ledger_doc
    assert "`Boto3S3CompatibleObjectStoreClient`" in ledger_doc
    assert "`api_wiring_allowed`" in ledger_doc
    assert "refreshed source/restore evidence hashes" in ledger_doc
    assert "`execution_allowed=false`" in ledger_doc
    assert "`PgKnowledgeBaseArticleRepository`" in ledger_doc
    assert "`PgSourceObjectRepository`" in ledger_doc
    assert "`tests/test_knowledge_base_write_unit_of_work.py`" in ledger_doc
    assert "Dry-run evidence cannot allow persistence" in ledger_doc
    assert "`KnowledgeBaseSourceObjectWriteGuard`" in ledger_doc
    assert "expected current version" in ledger_doc
    assert "retention policy" in ledger_doc.lower()
    assert "Legal Hold state" in ledger_doc
