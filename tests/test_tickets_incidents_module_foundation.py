from pathlib import Path

from suite.ai_control_plane.models import DataClass
from suite.platform.tickets_incidents_module import (
    TICKETS_AI_ASSIST_FEATURE_ID,
    TICKETS_COMPLIANCE_EVIDENCE_FEATURE_ID,
    TICKETS_EVENTS_READ_FEATURE_ID,
    TICKETS_INCIDENTS_CONTINUITY_DOMAIN,
    TICKETS_INCIDENTS_REQUIRED_OBJECT_METADATA_FIELDS,
    TICKETS_ITEMS_READ_FEATURE_ID,
    TICKETS_RAG_INDEXING_FEATURE_ID,
    TicketsIncidentsSubfeatureArea,
    build_default_tickets_incidents_object_rule_manifest,
    build_default_tickets_incidents_subfeature_registry,
    default_tickets_incidents_enabled_features,
    tickets_incidents_object_rule_registry_summary,
    tickets_incidents_subfeature_registry_summary,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_tickets_incidents_subfeature_registry_declares_first_safe_feature_set() -> None:
    registry = build_default_tickets_incidents_subfeature_registry()
    summary = tickets_incidents_subfeature_registry_summary(registry)

    assert registry.feature_ids == (
        TICKETS_ITEMS_READ_FEATURE_ID,
        TICKETS_EVENTS_READ_FEATURE_ID,
        TICKETS_COMPLIANCE_EVIDENCE_FEATURE_ID,
        TICKETS_RAG_INDEXING_FEATURE_ID,
        TICKETS_AI_ASSIST_FEATURE_ID,
    )
    assert summary == {
        "module_id": "tickets_incidents",
        "registry_version": "tickets_incidents_subfeatures.v1",
        "feature_count": 5,
        "default_enabled_count": 2,
        "approval_required_count": 3,
        "compliance_relevant_count": 1,
        "manifest_hash": registry.manifest_hash,
    }
    assert registry.manifest_hash.startswith("sha256:")
    assert registry.enabled_feature_defaults == default_tickets_incidents_enabled_features()

    ticket_read = registry.feature(TICKETS_ITEMS_READ_FEATURE_ID)
    compliance = registry.feature(TICKETS_COMPLIANCE_EVIDENCE_FEATURE_ID)
    rag = registry.feature(TICKETS_RAG_INDEXING_FEATURE_ID)
    ai_assist = registry.feature(TICKETS_AI_ASSIST_FEATURE_ID)

    assert ticket_read.area == TicketsIncidentsSubfeatureArea.TICKETS
    assert "SLA" in ticket_read.display_name

    assert compliance.area == TicketsIncidentsSubfeatureArea.COMPLIANCE
    assert compliance.requires_approval
    assert compliance.compliance_relevant
    assert "compliance_worker" in compliance.worker_surfaces
    assert "legal_hold_check" in compliance.evidence_required

    assert rag.requires_approval
    assert rag.dependency_feature_ids == (TICKETS_ITEMS_READ_FEATURE_ID, TICKETS_EVENTS_READ_FEATURE_ID)
    assert "authoritative_acl_validation" in rag.evidence_required

    assert ai_assist.requires_approval
    assert ai_assist.dependency_feature_ids == (TICKETS_RAG_INDEXING_FEATURE_ID,)
    assert "local_llm_gateway_audit" in ai_assist.evidence_required


def test_tickets_incidents_object_rules_enforce_module_contract_before_tables_or_api() -> None:
    registry = build_default_tickets_incidents_subfeature_registry()
    manifest = build_default_tickets_incidents_object_rule_manifest()
    summary = tickets_incidents_object_rule_registry_summary(manifest)

    assert tuple(rule.object_type for rule in manifest.object_rules) == ("ticket.ticket", "ticket.event")
    assert summary == {
        "module_id": "tickets_incidents",
        "registry_version": "tickets_incidents_object_rules.v1",
        "object_type_count": 2,
        "personal_object_type_count": 2,
        "manifest_hash": manifest.manifest_hash,
    }
    assert manifest.manifest_hash.startswith("sha256:")
    manifest.validate_subfeature_registry(registry)

    for rule in manifest.object_rules:
        assert set(TICKETS_INCIDENTS_REQUIRED_OBJECT_METADATA_FIELDS).issubset(rule.required_metadata_fields)
        assert rule.rls_required
        assert rule.audit_required
        assert rule.kms_key_ref_required
        assert rule.legal_hold_supported
        assert rule.search_candidate_only
        assert not rule.rag_indexing_default_enabled
        assert rule.destructive_actions_require_approval
        assert rule.backup_domain_id == TICKETS_INCIDENTS_CONTINUITY_DOMAIN

    assert manifest.rule("ticket.ticket").classification == DataClass.PERSONAL
    assert manifest.rule("ticket.event").classification == DataClass.PERSONAL


def test_tickets_incidents_module_charter_documents_contract_gates_and_deferred_scope() -> None:
    charter = (REPO_ROOT / "docs/modules/TICKETS_INCIDENTS_MODULE_CHARTER.md").read_text(encoding="utf-8")

    for expected in (
        "`tickets_incidents`",
        "Tenant Context",
        "feature permission",
        "object authorization",
        "Legal Hold",
        "retention",
        "backup",
        "restore",
        "candidate IDs only",
        "Local LLM Gateway",
        "No Tickets & Incidents business API route is enabled by this charter",
        "No platform catalog-readiness endpoint is enabled by this charter",
        "ticket_incident_records",
        "ticket.ticket",
        "ticket.event",
        "SLA",
        "escalation workflow",
    ):
        assert expected in charter
