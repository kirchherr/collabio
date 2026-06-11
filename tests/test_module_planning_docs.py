from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def read_doc(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_platform_module_docs_define_lifecycle_and_compliance_gates() -> None:
    adr = read_doc("ARCHITECTURE_DECISIONS/ADR-0058-platform-module-system.md")
    template = read_doc("docs/modules/MODULE_CHARTER_TEMPLATE.md")
    charter = read_doc("docs/modules/CRM_ERP_MODULE_CHARTER.md")

    for doc in (adr, template, charter):
        assert "enabled" in doc
        assert "disabled" in doc
        assert "decommission" in doc
        assert "Tenant Context" in doc
        assert "Legal Hold" in doc
        assert "retention" in doc
        assert "backup" in doc.lower()
        assert "candidate" in doc.lower()

    assert "`crm_erp`" in charter
    assert "SQL Server" in charter
    assert "GoBD" in charter
    assert "Local LLM Gateway" in charter
    assert "UI hiding is never authorization" in template


def test_compliance_matrix_covers_platform_module_controls() -> None:
    matrix = read_doc("COMPLIANCE_MATRIX.md")

    for control_id in ("CM-016", "CM-017", "CM-018", "CM-019", "CM-020"):
        assert control_id in matrix

    assert "Module lifecycle" in matrix
    assert "Module decommission" in matrix
