from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, field_validator, model_validator

from suite.storage.retention import RetentionManifest, RetentionManifestPolicy, build_retention_manifest
from suite.storage.source_objects import (
    LegalHoldState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectRepository,
    build_source_object_manifest_hash,
)

NAMESPACED_REF_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*:.+")


class LegalHoldTransitionError(ValueError):
    pass


class LegalHoldAction(StrEnum):
    PLACED = "placed"
    RELEASED = "released"


class LegalHoldCommandBase(BaseModel):
    tenant_id: str
    object_id: str
    source_version_id: str
    new_version_id: str
    hold_id: str
    matter_id: str
    requested_by: str
    approved_by: str
    audit_chain_ref: str
    occurred_at_utc: str

    @field_validator(
        "tenant_id",
        "object_id",
        "source_version_id",
        "new_version_id",
        "hold_id",
        "matter_id",
        "requested_by",
        "approved_by",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("audit_chain_ref")
    @classmethod
    def require_audit_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            raise ValueError("audit_chain_ref must be a namespaced reference")
        return normalized

    @field_validator("occurred_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        normalized = value.strip()
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
            raise ValueError("occurred_at_utc must be UTC")
        return normalized

    @model_validator(mode="after")
    def require_new_version(self) -> Self:
        if self.new_version_id == self.source_version_id:
            raise ValueError("new_version_id must differ from source_version_id")
        return self


class PlaceLegalHoldCommand(LegalHoldCommandBase):
    reason: str

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason must not be empty")
        return normalized


class ReleaseLegalHoldCommand(LegalHoldCommandBase):
    release_reason: str
    next_retention_policy_id: str

    @field_validator("release_reason", "next_retention_policy_id")
    @classmethod
    def require_release_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized


class LegalHoldDecision(BaseModel):
    action: LegalHoldAction
    tenant_id: str
    object_id: str
    hold_id: str
    matter_id: str
    previous_version_id: str
    new_version_id: str
    audit_chain_ref: str
    record: SourceObjectRecord
    retention_manifest: RetentionManifest


class LegalHoldSourceRepository(SourceObjectRepository, Protocol):
    pass


class LegalHoldService:
    def __init__(self, repository: LegalHoldSourceRepository, retention_policy: RetentionManifestPolicy) -> None:
        self.repository = repository
        self.retention_policy = retention_policy

    def place_hold(self, command: PlaceLegalHoldCommand) -> LegalHoldDecision:
        record = self.repository.get(
            tenant_id=command.tenant_id,
            object_id=command.object_id,
            version_id=command.source_version_id,
        )
        if record.metadata.legal_hold_state == LegalHoldState.ACTIVE:
            raise LegalHoldTransitionError("source object is already under active legal hold")

        held_record = self._copy_with_metadata(
            record,
            command=command,
            legal_hold_state=LegalHoldState.ACTIVE,
            retention_policy_id=record.metadata.retention_policy_id,
        )
        self.repository.add(held_record)
        manifest = build_retention_manifest(held_record, self.retention_policy)
        return self._decision(
            action=LegalHoldAction.PLACED,
            command=command,
            record=held_record,
            retention_manifest=manifest,
        )

    def release_hold(self, command: ReleaseLegalHoldCommand) -> LegalHoldDecision:
        record = self.repository.get(
            tenant_id=command.tenant_id,
            object_id=command.object_id,
            version_id=command.source_version_id,
        )
        if record.metadata.legal_hold_state != LegalHoldState.ACTIVE:
            raise LegalHoldTransitionError("source object must be under active legal hold before release")

        released_record = self._copy_with_metadata(
            record,
            command=command,
            legal_hold_state=LegalHoldState.NONE,
            retention_policy_id=command.next_retention_policy_id,
        )
        self.repository.add(released_record)
        manifest = build_retention_manifest(released_record, self.retention_policy)
        return self._decision(
            action=LegalHoldAction.RELEASED,
            command=command,
            record=released_record,
            retention_manifest=manifest,
        )

    def _copy_with_metadata(
        self,
        record: SourceObjectRecord,
        *,
        command: LegalHoldCommandBase,
        legal_hold_state: LegalHoldState,
        retention_policy_id: str,
    ) -> SourceObjectRecord:
        draft = SourceObjectMetadata.model_validate(
            {
                **record.metadata.model_dump(mode="python"),
                "version_id": command.new_version_id,
                "updated_at_utc": command.occurred_at_utc,
                "retention_policy_id": retention_policy_id,
                "legal_hold_state": legal_hold_state,
                "audit_chain_ref": command.audit_chain_ref,
                "manifest_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
            }
        )
        metadata = draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)})
        return SourceObjectRecord(metadata=metadata, text=record.text, content_bytes=record.content_bytes)

    def _decision(
        self,
        *,
        action: LegalHoldAction,
        command: LegalHoldCommandBase,
        record: SourceObjectRecord,
        retention_manifest: RetentionManifest,
    ) -> LegalHoldDecision:
        return LegalHoldDecision(
            action=action,
            tenant_id=command.tenant_id,
            object_id=command.object_id,
            hold_id=command.hold_id,
            matter_id=command.matter_id,
            previous_version_id=command.source_version_id,
            new_version_id=command.new_version_id,
            audit_chain_ref=command.audit_chain_ref,
            record=record,
            retention_manifest=retention_manifest,
        )
