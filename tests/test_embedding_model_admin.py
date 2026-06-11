from pathlib import Path

import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.rag.embedding_model_admin import (
    EmbeddingModelVersionAdminService,
    EmbeddingModelVersionApprovalRequest,
    EmbeddingModelVersionRegistrationRequest,
    EmbeddingModelVersionRetirementRequest,
    JsonFileEmbeddingModelVersionRegistry,
)
from suite.rag.source_indexing import EmbeddingModelVersion, InMemoryEmbeddingModelVersionRegistry


def security_admin() -> UserContext:
    return UserContext(user_id="security-admin-1", tenant_id="tenant-demo", role_ids={"security-admin"})


def registration_request(*, model_id: str = "embedding-admin-test") -> EmbeddingModelVersionRegistrationRequest:
    return EmbeddingModelVersionRegistrationRequest(
        embedding_model_id=model_id,
        embedding_model_version="2026-06-11",
        provider="local",
        deployment="deterministic-hash",
        dimensions=3,
        distance_metric="cosine",
        checksum="sha256:model-admin-test",
        approved_for_data_classes={DataClass.INTERNAL, DataClass.PERSONAL},
        change_reference="change:embedding-admin-test",
    )


def test_embedding_model_admin_registers_approves_and_retires_with_audit_chain() -> None:
    repository = InMemoryEmbeddingModelVersionRegistry(model_versions=())
    audit_logger = InMemoryAuditLogger()
    service = EmbeddingModelVersionAdminService(
        repository=repository,
        audit_logger=audit_logger,
        clock=lambda: "2026-06-11T00:00:00Z",
    )

    registered = service.register(registration_request(), user_context=security_admin())
    approved = service.approve(
        embedding_model_id=registered.embedding_model_id,
        embedding_model_version=registered.embedding_model_version,
        request=EmbeddingModelVersionApprovalRequest(approval_reference="approval:embedding-admin-test"),
        user_context=security_admin(),
    )
    retired = service.retire(
        embedding_model_id=registered.embedding_model_id,
        embedding_model_version=registered.embedding_model_version,
        request=EmbeddingModelVersionRetirementRequest(
            retirement_reference="approval:embedding-retire-test",
            reason="superseded by new benchmarked model",
        ),
        user_context=security_admin(),
    )

    assert registered.approved_at_utc is None
    assert approved.approved_at_utc == "2026-06-11T00:00:00Z"
    assert retired.retired_at_utc == "2026-06-11T00:00:00Z"
    assert audit_logger.verify().ok
    assert [event.event_type for event in audit_logger.events] == [
        "embedding_model_version.registered",
        "embedding_model_version.approved",
        "embedding_model_version.retired",
    ]
    assert all(event.input_hash is None and event.output_hash is None for event in audit_logger.events)
    assert audit_logger.events[1].metadata["approval_reference"] == "approval:embedding-admin-test"
    assert audit_logger.events[2].metadata["reason"] == "superseded by new benchmarked model"


def test_embedding_model_admin_rejects_duplicate_or_invalid_transitions() -> None:
    repository = InMemoryEmbeddingModelVersionRegistry(model_versions=())
    audit_logger = InMemoryAuditLogger()
    service = EmbeddingModelVersionAdminService(
        repository=repository,
        audit_logger=audit_logger,
        clock=lambda: "2026-06-11T00:00:00Z",
    )
    request = registration_request(model_id="embedding-duplicate-test")
    service.register(request, user_context=security_admin())

    with pytest.raises(ValueError, match="already exists"):
        service.register(request, user_context=security_admin())

    service.approve(
        embedding_model_id=request.embedding_model_id,
        embedding_model_version=request.embedding_model_version,
        request=EmbeddingModelVersionApprovalRequest(approval_reference="approval:first"),
        user_context=security_admin(),
    )

    with pytest.raises(ValueError, match="already approved"):
        service.approve(
            embedding_model_id=request.embedding_model_id,
            embedding_model_version=request.embedding_model_version,
            request=EmbeddingModelVersionApprovalRequest(approval_reference="approval:second"),
            user_context=security_admin(),
        )


def test_embedding_model_admin_rejects_non_indexable_data_classes() -> None:
    with pytest.raises(ValidationError, match="non-indexable data classes"):
        EmbeddingModelVersionRegistrationRequest(
            embedding_model_id="embedding-invalid-class-test",
            embedding_model_version="1",
            provider="local",
            deployment="deterministic-hash",
            dimensions=3,
            checksum="sha256:model",
            approved_for_data_classes={DataClass.AI_PROMPT},
            change_reference="change:invalid-class",
        )


def test_json_embedding_model_registry_persists_admin_changes(tmp_path: Path) -> None:
    registry_path = tmp_path / "registries" / "embedding_models.json"
    registry = JsonFileEmbeddingModelVersionRegistry.load_or_seed(
        registry_path,
        seed=InMemoryEmbeddingModelVersionRegistry(model_versions=()),
    )
    model_version = EmbeddingModelVersion(
        embedding_model_id="embedding-json-test",
        embedding_model_version="1",
        provider="local",
        deployment="deterministic-hash",
        dimensions=3,
        checksum="sha256:model-json-test",
        approved_for_data_classes=frozenset({DataClass.INTERNAL}),
        approved_at_utc="2026-06-11T00:00:00Z",
    )

    registry.upsert(model_version)
    reloaded = JsonFileEmbeddingModelVersionRegistry.load_or_seed(
        registry_path,
        seed=InMemoryEmbeddingModelVersionRegistry(model_versions=()),
    )

    assert reloaded.get(embedding_model_id="embedding-json-test", embedding_model_version="1") == model_version
