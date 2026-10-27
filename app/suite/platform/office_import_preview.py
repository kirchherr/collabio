"""ACL-checked, non-persisting native Office import previews."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_schema import MAX_DOCUMENT_CHARACTERS, validate_office_document
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, sha256_bytes
from suite.rag.repositories import ReadableObjectAclAuthorizer
from suite.rag.rich_document_parser import DOCX_MIME_TYPE
from suite.rag.rich_document_parser_socket import parse_rich_document
from suite.storage.source_objects import (
    SourceObjectRepository,
    build_source_object_manifest_hash,
    source_object_content_bytes,
)

OfficeInformationClassification = Literal["public", "internal", "confidential", "restricted"]
ParserDispatch = Callable[[ParserWorkerRequest], ParsedTextArtifact]


class OfficeImportPreviewNotFound(LookupError):
    pass


class OfficeImportPreviewDenied(PermissionError):
    pass


class OfficeImportPreviewInvalid(ValueError):
    pass


class OfficeImportPreviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_object_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    source_version_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


class OfficeImportPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["office_import_preview.v1"] = "office_import_preview.v1"
    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_title: str
    source_content_hash: str
    source_acl_version: int = Field(ge=1)
    information_classification: OfficeInformationClassification
    parser_profile_id: Literal["rich-document-parser-worker:1"] = "rich-document-parser-worker:1"
    parser_text_hash: str
    warnings: tuple[str, ...]
    document: dict[str, Any]
    content_persisted: Literal[False] = False
    save_requires_explicit_confirmation: Literal[True] = True
    fidelity_preserved: Literal[False] = False
    import_scope: Literal["bounded_flattened_text_preview"] = "bounded_flattened_text_preview"
    audit_event_id: str


def _native_document(
    text: str,
    *,
    source_object_id: str,
    source_version_id: str,
    source_content_hash: str,
    source_acl_version: int,
    parser_text_hash: str,
) -> dict[str, Any]:
    if len(text) > MAX_DOCUMENT_CHARACTERS:
        raise OfficeImportPreviewInvalid("parsed document exceeds native preview limits")
    blocks: list[dict[str, Any]] = []
    for line in text.splitlines():
        content = [] if not line else [{"type": "text", "text": line}]
        blocks.append({"type": "paragraph", "content": content})
    if not blocks:
        blocks.append({"type": "paragraph", "content": []})
    try:
        return validate_office_document(
            {
                "type": "doc",
                "attrs": {
                    "importProvenance": {
                        "sourceObjectId": source_object_id,
                        "sourceVersionId": source_version_id,
                        "sourceContentHash": source_content_hash,
                        "sourceAclVersion": source_acl_version,
                        "parserProfileId": "rich-document-parser-worker:1",
                        "parserTextHash": parser_text_hash,
                        "importScope": "bounded_flattened_text_preview",
                    }
                },
                "content": blocks,
            }
        )
    except ValueError as exc:
        raise OfficeImportPreviewInvalid("parsed document cannot be represented as a native preview") from exc


class OfficeImportPreviewService:
    def __init__(
        self,
        *,
        source_repository: SourceObjectRepository,
        audit: InMemoryAuditLogger,
        parser_dispatch: ParserDispatch = parse_rich_document,
    ) -> None:
        self._source_repository = source_repository
        self._audit = audit
        self._parser_dispatch = parser_dispatch
        self._acl = ReadableObjectAclAuthorizer()

    def preview(
        self,
        *,
        user_context: UserContext,
        command: OfficeImportPreviewCommand,
    ) -> OfficeImportPreviewResponse:
        try:
            record = self._source_repository.get(
                tenant_id=user_context.tenant_id,
                object_id=command.source_object_id,
                version_id=command.source_version_id,
            )
        except KeyError as exc:
            raise OfficeImportPreviewNotFound("source version was not found") from exc
        metadata = record.metadata
        if (
            metadata.tenant_id != user_context.tenant_id
            or metadata.object_id != command.source_object_id
            or metadata.version_id != command.source_version_id
        ):
            raise OfficeImportPreviewNotFound("source version was not found")
        try:
            current_metadata = self._source_repository.latest(
                tenant_id=user_context.tenant_id,
                object_id=command.source_object_id,
            ).metadata
        except KeyError as exc:
            raise OfficeImportPreviewNotFound("source version was not found") from exc
        if not self._acl.can_read(
            user_context=user_context,
            object_id=metadata.object_id,
            acl_version=current_metadata.acl_version,
        ):
            raise OfficeImportPreviewDenied("source version is not readable")
        if metadata.mime_type.partition(";")[0].strip().lower() != DOCX_MIME_TYPE:
            raise OfficeImportPreviewInvalid("source version is not a DOCX document")
        content = source_object_content_bytes(record)
        if (
            sha256_bytes(content) != metadata.content_hash
            or build_source_object_manifest_hash(metadata) != metadata.manifest_hash
        ):
            raise OfficeImportPreviewInvalid("source evidence does not match stored content")
        artifact = self._parser_dispatch(
            ParserWorkerRequest(
                tenant_id=metadata.tenant_id,
                source_object_id=metadata.object_id,
                source_version_id=metadata.version_id,
                source_object_type=metadata.object_type.value,
                mime_type=metadata.mime_type,
                content=content,
                filename=metadata.title,
            )
        )
        if (
            artifact.parser_name != "rich-document-parser-worker"
            or artifact.parser_version != "1"
            or artifact.source_object_type != metadata.object_type.value
            or artifact.mime_type != metadata.mime_type.partition(";")[0].strip().lower()
            or artifact.input_hash != metadata.content_hash
            or artifact.text_hash != sha256_bytes(artifact.text.encode("utf-8"))
            or artifact.text_byte_length != len(artifact.text.encode("utf-8"))
            or len(artifact.warnings) > 20
            or any(not warning or len(warning) > 200 for warning in artifact.warnings)
        ):
            raise OfficeImportPreviewInvalid("parser evidence does not match the authorized source")
        document = _native_document(
            artifact.text,
            source_object_id=metadata.object_id,
            source_version_id=metadata.version_id,
            source_content_hash=metadata.content_hash,
            source_acl_version=current_metadata.acl_version,
            parser_text_hash=artifact.text_hash,
        )
        audit_event_id = self._audit.record(
            user_context=user_context,
            event_type="office.documents.import_preview.read",
            source_object_ids=[metadata.object_id],
            metadata={
                "module_id": "office_documents",
                "surface": "api",
                "source_version_id": metadata.version_id,
                "source_content_hash": metadata.content_hash,
                "source_acl_version": current_metadata.acl_version,
                "parser_profile_id": f"{artifact.parser_name}:{artifact.parser_version}",
                "parser_text_hash": artifact.text_hash,
                "warning_count": len(artifact.warnings),
                "content_persisted": False,
                "fidelity_preserved": False,
                "rag_indexing_allowed": False,
                "search_indexing_allowed": False,
            },
        ).event_id
        classification = metadata.classification.value
        if classification not in {"public", "internal", "confidential", "restricted"}:
            raise OfficeImportPreviewInvalid("source classification cannot be represented by native Office")
        return OfficeImportPreviewResponse(
            tenant_id=metadata.tenant_id,
            source_object_id=metadata.object_id,
            source_version_id=metadata.version_id,
            source_title=metadata.title,
            source_content_hash=metadata.content_hash,
            source_acl_version=current_metadata.acl_version,
            information_classification=classification,  # type: ignore[arg-type]
            parser_text_hash=artifact.text_hash,
            warnings=artifact.warnings,
            document=document,
            audit_event_id=audit_event_id,
        )
