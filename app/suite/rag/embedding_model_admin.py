from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from suite.ai_control_plane.models import AuditEvent, DataClass, UserContext
from suite.rag.source_indexing import (
    DEFAULT_EMBEDDING_MODEL_DATA_CLASSES,
    NAMESPACED_REF_PATTERN,
    EmbeddingModelVersion,
    InMemoryEmbeddingModelVersionRegistry,
    utc_now_iso,
)

SOURCE_INDEXABLE_DATA_CLASSES = DEFAULT_EMBEDDING_MODEL_DATA_CLASSES
SUPPORTED_DISTANCE_METRICS = frozenset({"cosine", "l2", "inner_product"})


class AuditEventRecorder(Protocol):
    def record(
        self,
        *,
        user_context: UserContext,
        event_type: str,
        model_id: str | None = None,
        prompt_template_id: str | None = None,
        source_object_ids: list[str] | None = None,
        input_text: str | None = None,
        output_text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent: ...


class EmbeddingModelVersionAdminRepository(Protocol):
    def get(
        self,
        *,
        embedding_model_id: str,
        embedding_model_version: str,
    ) -> EmbeddingModelVersion: ...

    def list_model_versions(self) -> tuple[EmbeddingModelVersion, ...]: ...

    def upsert(self, model_version: EmbeddingModelVersion) -> EmbeddingModelVersion: ...


class EmbeddingModelVersionView(BaseModel):
    embedding_model_id: str
    embedding_model_version: str
    provider: str
    deployment: str
    dimensions: int
    distance_metric: str
    checksum: str
    approved_for_data_classes: set[DataClass]
    approved_at_utc: str | None = None
    retired_at_utc: str | None = None

    @classmethod
    def from_domain(cls, model_version: EmbeddingModelVersion) -> Self:
        return cls(
            embedding_model_id=model_version.embedding_model_id,
            embedding_model_version=model_version.embedding_model_version,
            provider=model_version.provider,
            deployment=model_version.deployment,
            dimensions=model_version.dimensions,
            distance_metric=model_version.distance_metric,
            checksum=model_version.checksum,
            approved_for_data_classes=set(model_version.approved_for_data_classes),
            approved_at_utc=model_version.approved_at_utc,
            retired_at_utc=model_version.retired_at_utc,
        )


class EmbeddingModelVersionRegistrationRequest(BaseModel):
    embedding_model_id: str = Field(min_length=1)
    embedding_model_version: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    deployment: str = Field(min_length=1)
    dimensions: int = Field(ge=1, le=16000)
    distance_metric: str = "cosine"
    checksum: str = Field(min_length=1)
    approved_for_data_classes: set[DataClass] = Field(min_length=1)
    change_reference: str = Field(min_length=1)

    @field_validator(
        "embedding_model_id",
        "embedding_model_version",
        "provider",
        "deployment",
        "distance_metric",
        "checksum",
        "change_reference",
    )
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_registry_payload(self) -> Self:
        _validate_checksum(self.checksum)
        _validate_distance_metric(self.distance_metric)
        _validate_source_indexable_data_classes(self.approved_for_data_classes)
        return self

    def to_domain(self) -> EmbeddingModelVersion:
        return EmbeddingModelVersion(
            embedding_model_id=self.embedding_model_id,
            embedding_model_version=self.embedding_model_version,
            provider=self.provider,
            deployment=self.deployment,
            dimensions=self.dimensions,
            distance_metric=self.distance_metric,
            checksum=self.checksum,
            approved_for_data_classes=frozenset(self.approved_for_data_classes),
        )


class EmbeddingModelVersionApprovalRequest(BaseModel):
    approval_reference: str = Field(min_length=1)
    approved_for_data_classes: set[DataClass] | None = None

    @field_validator("approval_reference")
    @classmethod
    def strip_approval_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("approval_reference must not be empty")
        return normalized

    @field_validator("approved_for_data_classes")
    @classmethod
    def validate_optional_data_classes(cls, value: set[DataClass] | None) -> set[DataClass] | None:
        if value is not None:
            _validate_source_indexable_data_classes(value)
        return value


class EmbeddingModelVersionRetirementRequest(BaseModel):
    retirement_reference: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @field_validator("retirement_reference", "reason")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized


class JsonFileEmbeddingModelVersionRegistry(InMemoryEmbeddingModelVersionRegistry):
    def __init__(self, path: Path, model_versions: Sequence[EmbeddingModelVersion]) -> None:
        super().__init__(model_versions)
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load_or_seed(
        cls,
        path: Path,
        seed: InMemoryEmbeddingModelVersionRegistry,
    ) -> JsonFileEmbeddingModelVersionRegistry:
        if not path.exists():
            _write_embedding_model_version_rows(path, seed.list_model_versions())
        rows = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            path=path,
            model_versions=tuple(_embedding_model_version_from_row(row) for row in rows),
        )

    def upsert(self, model_version: EmbeddingModelVersion) -> EmbeddingModelVersion:
        saved = super().upsert(model_version)
        _write_embedding_model_version_rows(self.path, self.list_model_versions())
        return saved


@dataclass(frozen=True)
class EmbeddingModelVersionAdminService:
    repository: EmbeddingModelVersionAdminRepository
    audit_logger: AuditEventRecorder
    clock: Callable[[], str] = utc_now_iso

    def list_model_versions(self) -> tuple[EmbeddingModelVersionView, ...]:
        return tuple(EmbeddingModelVersionView.from_domain(model) for model in self.repository.list_model_versions())

    def register(
        self,
        request: EmbeddingModelVersionRegistrationRequest,
        *,
        user_context: UserContext,
    ) -> EmbeddingModelVersionView:
        try:
            self.repository.get(
                embedding_model_id=request.embedding_model_id,
                embedding_model_version=request.embedding_model_version,
            )
        except LookupError:
            pass
        else:
            raise ValueError("embedding model version already exists")

        model_version = self.repository.upsert(request.to_domain())
        self._record_event(
            user_context=user_context,
            event_type="embedding_model_version.registered",
            model_version=model_version,
            metadata={
                "change_reference": request.change_reference,
                "approved": False,
                "retired": False,
            },
        )
        return EmbeddingModelVersionView.from_domain(model_version)

    def approve(
        self,
        *,
        embedding_model_id: str,
        embedding_model_version: str,
        request: EmbeddingModelVersionApprovalRequest,
        user_context: UserContext,
    ) -> EmbeddingModelVersionView:
        current = self.repository.get(
            embedding_model_id=embedding_model_id,
            embedding_model_version=embedding_model_version,
        )
        if current.approved_at_utc is not None:
            raise ValueError("embedding model version is already approved")
        if current.retired_at_utc is not None:
            raise ValueError("retired embedding model versions cannot be approved")

        approved_data_classes = (
            frozenset(request.approved_for_data_classes)
            if request.approved_for_data_classes is not None
            else current.approved_for_data_classes
        )
        _validate_source_indexable_data_classes(approved_data_classes)
        approved = replace(
            current,
            approved_for_data_classes=approved_data_classes,
            approved_at_utc=self.clock(),
        )
        saved = self.repository.upsert(approved)
        self._record_event(
            user_context=user_context,
            event_type="embedding_model_version.approved",
            model_version=saved,
            metadata={
                "approval_reference": request.approval_reference,
                "approved": True,
                "retired": False,
            },
        )
        return EmbeddingModelVersionView.from_domain(saved)

    def retire(
        self,
        *,
        embedding_model_id: str,
        embedding_model_version: str,
        request: EmbeddingModelVersionRetirementRequest,
        user_context: UserContext,
    ) -> EmbeddingModelVersionView:
        current = self.repository.get(
            embedding_model_id=embedding_model_id,
            embedding_model_version=embedding_model_version,
        )
        if current.retired_at_utc is not None:
            raise ValueError("embedding model version is already retired")

        retired = replace(current, retired_at_utc=self.clock())
        saved = self.repository.upsert(retired)
        self._record_event(
            user_context=user_context,
            event_type="embedding_model_version.retired",
            model_version=saved,
            metadata={
                "retirement_reference": request.retirement_reference,
                "reason": request.reason,
                "approved": saved.approved_at_utc is not None,
                "retired": True,
            },
        )
        return EmbeddingModelVersionView.from_domain(saved)

    def _record_event(
        self,
        *,
        user_context: UserContext,
        event_type: str,
        model_version: EmbeddingModelVersion,
        metadata: dict[str, Any],
    ) -> None:
        self.audit_logger.record(
            user_context=user_context,
            event_type=event_type,
            source_object_ids=[_model_version_audit_ref(model_version)],
            metadata={
                **_embedding_model_version_audit_metadata(model_version),
                **metadata,
            },
        )


def _embedding_model_version_audit_metadata(model_version: EmbeddingModelVersion) -> dict[str, Any]:
    return {
        "embedding_model_id": model_version.embedding_model_id,
        "embedding_model_version": model_version.embedding_model_version,
        "provider": model_version.provider,
        "deployment": model_version.deployment,
        "dimensions": model_version.dimensions,
        "distance_metric": model_version.distance_metric,
        "checksum": model_version.checksum,
        "approved_for_data_classes": sorted(data_class.value for data_class in model_version.approved_for_data_classes),
        "approved_at_utc": model_version.approved_at_utc,
        "retired_at_utc": model_version.retired_at_utc,
    }


def _embedding_model_version_to_row(model_version: EmbeddingModelVersion) -> dict[str, Any]:
    return _embedding_model_version_audit_metadata(model_version)


def _embedding_model_version_from_row(row: dict[str, Any]) -> EmbeddingModelVersion:
    return EmbeddingModelVersion(
        embedding_model_id=str(row["embedding_model_id"]),
        embedding_model_version=str(row["embedding_model_version"]),
        provider=str(row["provider"]),
        deployment=str(row["deployment"]),
        dimensions=int(row["dimensions"]),
        distance_metric=str(row.get("distance_metric", "cosine")),
        checksum=str(row["checksum"]),
        approved_for_data_classes=frozenset(DataClass(value) for value in row["approved_for_data_classes"]),
        approved_at_utc=row.get("approved_at_utc"),
        retired_at_utc=row.get("retired_at_utc"),
    )


def _write_embedding_model_version_rows(path: Path, model_versions: Sequence[EmbeddingModelVersion]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    rows = [_embedding_model_version_to_row(model_version) for model_version in model_versions]
    temp_path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _model_version_audit_ref(model_version: EmbeddingModelVersion) -> str:
    return f"embedding_model:{model_version.embedding_model_id}:{model_version.embedding_model_version}"


def _validate_checksum(value: str) -> None:
    if not NAMESPACED_REF_PATTERN.fullmatch(value.strip()):
        raise ValueError("checksum must be a namespaced reference")


def _validate_distance_metric(value: str) -> None:
    if value not in SUPPORTED_DISTANCE_METRICS:
        raise ValueError("distance_metric must be cosine, l2, or inner_product")


def _validate_source_indexable_data_classes(values: set[DataClass] | frozenset[DataClass]) -> None:
    if not values:
        raise ValueError("approved_for_data_classes must not be empty")
    unsupported = values - SOURCE_INDEXABLE_DATA_CLASSES
    if unsupported:
        unsupported_values = ", ".join(sorted(data_class.value for data_class in unsupported))
        raise ValueError(f"approved_for_data_classes contains non-indexable data classes: {unsupported_values}")
