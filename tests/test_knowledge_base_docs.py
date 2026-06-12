from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def read_doc(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_knowledge_base_docs_follow_module_implementation_contract() -> None:
    charter = read_doc("docs/modules/KNOWLEDGE_BASE_MODULE_CHARTER.md")
    slice_doc = read_doc("docs/modules/KNOWLEDGE_BASE_ARTICLES_VERTICAL_SLICE.md")
    evidence_doc = read_doc("docs/modules/KNOWLEDGE_BASE_SOURCE_RESTORE_EVIDENCE.md")

    for doc in (charter, slice_doc, evidence_doc):
        assert "tenant context" in doc.lower()
        assert "legal hold" in doc.lower()
        assert "restore" in doc.lower()
        assert "candidate" in doc.lower()
        assert "local llm gateway" in doc.lower()
        assert "metadata-only" in doc.lower()

    for doc in (charter, slice_doc):
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
    assert "Article bodies are not stored in the first slice" in charter
    assert "0022_knowledge_base_source_restore_evidence.sql" in charter
    assert "current `kb.article_version`" in slice_doc
    assert "`GET /v1/admin/kb/evidence`" in slice_doc
    assert "`POST /v1/admin/kb/articles/write-dry-run`" in slice_doc
    assert "source-version evidence hash" in slice_doc.lower()
    assert "`GET /v1/admin/kb/evidence`" in evidence_doc
    assert "`POST /v1/admin/kb/articles/write-dry-run`" in evidence_doc
    assert "`knowledge_base.source_version_evidence`" in evidence_doc
    assert "`knowledge_base.restore_evidence`" in evidence_doc
    assert "Drift blocks the evidence build" in evidence_doc
