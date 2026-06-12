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
    assert "`GET /v1/admin/kb/evidence`" in charter
    assert "`POST /v1/admin/kb/articles/write-dry-run`" in charter
    assert "`POST /v1/admin/kb/articles/write-approvals/approve`" in charter
    assert "`POST /v1/admin/kb/articles/write-approvals/refresh-preview`" in charter
    assert "`POST /v1/admin/kb/articles/write-approvals/execution-skeleton`" in charter
    assert "`projected_restore_evidence_preview_hash`" in charter
    assert "`execution_plan_hash`" in charter
    assert "`execution_allowed=false`" in charter
    assert "Article bodies are not stored in the first slice" in charter
    assert "0022_knowledge_base_source_restore_evidence.sql" in charter
    assert "0023_knowledge_base_write_approval_evidence.sql" in charter
    assert "0024_knowledge_base_write_approval_transition_lineage.sql" in charter
    assert "current `kb.article_version`" in slice_doc
    assert "`GET /v1/admin/kb/evidence`" in slice_doc
    assert "`POST /v1/admin/kb/articles/write-dry-run`" in slice_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/approve`" in slice_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/refresh-preview`" in slice_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/execution-skeleton`" in slice_doc
    assert "`projected_restore_evidence_preview_hash`" in slice_doc
    assert "`execution_plan_hash`" in slice_doc
    assert "source-version evidence hash" in slice_doc.lower()
    assert "`GET /v1/admin/kb/evidence`" in evidence_doc
    assert "`POST /v1/admin/kb/articles/write-dry-run`" in evidence_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/approve`" in evidence_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/refresh-preview`" in evidence_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/execution-skeleton`" in evidence_doc
    assert "`projected_restore_evidence_preview_hash`" in evidence_doc
    assert "`execution_plan_hash`" in evidence_doc
    assert "`execution_allowed=false`" in evidence_doc
    assert "`knowledge_base.source_version_evidence`" in evidence_doc
    assert "`knowledge_base.restore_evidence`" in evidence_doc
    assert "Drift blocks the evidence build" in evidence_doc
    assert "`knowledge_base.write_approval_evidence`" in ledger_doc
    assert "`0023_knowledge_base_write_approval_evidence.sql`" in ledger_doc
    assert "`0024_knowledge_base_write_approval_transition_lineage.sql`" in ledger_doc
    assert "`transition_source_evidence_hash`" in ledger_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/refresh-preview`" in ledger_doc
    assert "`POST /v1/admin/kb/articles/write-approvals/execution-skeleton`" in ledger_doc
    assert "`projected_restore_evidence_preview_hash`" in ledger_doc
    assert "`execution_plan_hash`" in ledger_doc
    assert "`execution_allowed=false`" in ledger_doc
    assert "Dry-run evidence cannot allow persistence" in ledger_doc
    assert "`KnowledgeBaseSourceObjectWriteGuard`" in ledger_doc
    assert "expected current version" in ledger_doc
    assert "retention policy" in ledger_doc.lower()
    assert "Legal Hold state" in ledger_doc
