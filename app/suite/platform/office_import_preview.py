"""ACL-checked, non-persisting native Office import previews."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_schema import MAX_DOCUMENT_CHARACTERS, validate_office_document
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks, sha256_bytes
from suite.rag.repositories import ReadableObjectAclAuthorizer
from suite.rag.rich_document_parser import DOCX_MIME_TYPE
from suite.rag.rich_document_parser_socket import parse_rich_document
from suite.storage.source_objects import (
    SourceObjectMetadata,
    SourceObjectRepository,
    build_source_object_manifest_hash,
    source_object_content_bytes,
)

OfficeInformationClassification = Literal["public", "internal", "confidential", "restricted"]
ParserDispatch = Callable[[ParserWorkerRequest], ParsedTextArtifact]
IMPORT_SOURCE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")


class OfficeImportSourceRepository(Protocol):
    def list_latest_metadata(self, *, tenant_id: str, limit: int = 100) -> tuple[SourceObjectMetadata, ...]: ...


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

    schema_version: Literal["office_import_preview.v2"] = "office_import_preview.v2"
    tenant_id: str
    source_object_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
    source_version_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
    source_title: str = Field(min_length=1, max_length=200)
    source_content_hash: str
    source_acl_version: int = Field(ge=1)
    information_classification: OfficeInformationClassification
    parser_profile_id: Literal["rich-document-parser-worker:1"] = "rich-document-parser-worker:1"
    parser_text_hash: str
    parser_structure_hash: str
    warnings: tuple[str, ...]
    document: dict[str, Any]
    content_persisted: Literal[False] = False
    save_requires_explicit_confirmation: Literal[True] = True
    fidelity_preserved: Literal[False] = False
    import_scope: Literal["bounded_structured_docx_preview"] = "bounded_structured_docx_preview"
    audit_event_id: str


class OfficeImportSourceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_object_id: str
    source_version_id: str
    source_title: str
    updated_at_utc: str
    information_classification: OfficeInformationClassification
    content_byte_length: int = Field(ge=1)


class OfficeImportSourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["office_import_sources.v1"] = "office_import_sources.v1"
    tenant_id: str
    items: tuple[OfficeImportSourceItem, ...]
    content_returned: Literal[False] = False
    current_acl_validated: Literal[True] = True
    audit_event_id: str


def _text_content(text: str) -> list[dict[str, str]]:
    return [] if not text else [{"type": "text", "text": text}]


def _structured_blocks(values: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    if len(values) > 2_000:
        raise OfficeImportPreviewInvalid("parsed document exceeds structured preview limits")
    blocks: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
            raise OfficeImportPreviewInvalid("parser structure is invalid")
        kind = value["kind"]
        if kind == "paragraph" and set(value) == {"kind", "text"} and isinstance(value["text"], str):
            blocks.append({"type": "paragraph", "content": _text_content(value["text"])})
        elif (
            kind == "heading"
            and set(value) == {"kind", "level", "text"}
            and type(value["level"]) is int
            and value["level"] in {1, 2, 3}
            and isinstance(value["text"], str)
        ):
            blocks.append(
                {"type": "heading", "attrs": {"level": value["level"]}, "content": _text_content(value["text"])}
            )
        elif kind in {"bullet_list", "ordered_list"} and set(value) == {"kind", "items"}:
            items = value["items"]
            if (
                not isinstance(items, list)
                or not 1 <= len(items) <= 1_000
                or any(not isinstance(item, str) for item in items)
            ):
                raise OfficeImportPreviewInvalid("parser list structure is invalid")
            node: dict[str, Any] = {
                "type": "bulletList" if kind == "bullet_list" else "orderedList",
                "content": [
                    {"type": "listItem", "content": [{"type": "paragraph", "content": _text_content(item)}]}
                    for item in items
                ],
            }
            if kind == "ordered_list":
                node["attrs"] = {"start": 1}
            blocks.append(node)
        elif kind == "table" and set(value) == {"kind", "rows"}:
            rows = value["rows"]
            if (
                not isinstance(rows, list)
                or not 1 <= len(rows) <= 200
                or not isinstance(rows[0], list)
                or not 1 <= len(rows[0]) <= 20
                or any(not isinstance(row, list) or len(row) != len(rows[0]) for row in rows)
                or any(not isinstance(cell, str) for row in rows for cell in row)
            ):
                raise OfficeImportPreviewInvalid("parser table structure is invalid")
            blocks.append(
                {
                    "type": "table",
                    "content": [
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableCell",
                                    "content": [{"type": "paragraph", "content": _text_content(cell)}],
                                }
                                for cell in row
                            ],
                        }
                        for row in rows
                    ],
                }
            )
        else:
            raise OfficeImportPreviewInvalid("parser structure contains an unsupported block")
    return blocks


def _native_document(
    text: str,
    *,
    document_blocks: tuple[dict[str, Any], ...],
    source_object_id: str,
    source_version_id: str,
    source_content_hash: str,
    source_acl_version: int,
    parser_text_hash: str,
    parser_structure_hash: str,
) -> dict[str, Any]:
    if len(text) > MAX_DOCUMENT_CHARACTERS:
        raise OfficeImportPreviewInvalid("parsed document exceeds native preview limits")
    blocks = (
        _structured_blocks(document_blocks)
        if document_blocks
        else [{"type": "paragraph", "content": _text_content(line)} for line in text.splitlines()]
    )
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
                        "parserStructureHash": parser_structure_hash,
                        "importScope": "bounded_structured_docx_preview",
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

    def discover_sources(
        self,
        *,
        user_context: UserContext,
        query: str = "",
        limit: int = 25,
    ) -> OfficeImportSourceResponse:
        normalized_query = query.strip().casefold()
        if len(normalized_query) > 100 or not 1 <= limit <= 50:
            raise OfficeImportPreviewInvalid("import source discovery request is invalid")
        items: list[OfficeImportSourceItem] = []
        repository = cast(OfficeImportSourceRepository, self._source_repository)
        for metadata in repository.list_latest_metadata(
            tenant_id=user_context.tenant_id,
            limit=500,
        ):
            if metadata.mime_type.partition(";")[0].strip().lower() != DOCX_MIME_TYPE:
                continue
            if not self._acl.can_read(
                user_context=user_context,
                object_id=metadata.object_id,
                acl_version=metadata.acl_version,
            ):
                continue
            if normalized_query and normalized_query not in f"{metadata.title}\n{metadata.object_id}".casefold():
                continue
            if (
                IMPORT_SOURCE_IDENTIFIER.fullmatch(metadata.object_id) is None
                or IMPORT_SOURCE_IDENTIFIER.fullmatch(metadata.version_id) is None
                or not 1 <= len(metadata.title) <= 200
                or metadata.title != metadata.title.strip()
                or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in metadata.title)
            ):
                continue
            classification = metadata.classification.value
            if classification not in {"public", "internal", "confidential", "restricted"}:
                continue
            items.append(
                OfficeImportSourceItem(
                    source_object_id=metadata.object_id,
                    source_version_id=metadata.version_id,
                    source_title=metadata.title,
                    updated_at_utc=metadata.updated_at_utc,
                    information_classification=classification,  # type: ignore[arg-type]
                    content_byte_length=metadata.content_byte_length,
                )
            )
            if len(items) == limit:
                break
        event_id = self._audit.record(
            user_context=user_context,
            event_type="office.documents.import_sources.read",
            source_object_ids=[item.source_object_id for item in items],
            metadata={
                "module_id": "office_documents",
                "surface": "api",
                "result_count": len(items),
                "query_supplied": bool(normalized_query),
                "content_returned": False,
                "current_acl_validated": True,
            },
        ).event_id
        return OfficeImportSourceResponse(
            tenant_id=user_context.tenant_id,
            items=tuple(items),
            audit_event_id=event_id,
        )

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
            or artifact.document_blocks_hash != hash_document_blocks(artifact.document_blocks)
            or len(artifact.warnings) > 20
            or any(not warning or len(warning) > 200 for warning in artifact.warnings)
        ):
            raise OfficeImportPreviewInvalid("parser evidence does not match the authorized source")
        document = _native_document(
            artifact.text,
            document_blocks=artifact.document_blocks,
            source_object_id=metadata.object_id,
            source_version_id=metadata.version_id,
            source_content_hash=metadata.content_hash,
            source_acl_version=current_metadata.acl_version,
            parser_text_hash=artifact.text_hash,
            parser_structure_hash=artifact.document_blocks_hash,
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
                "parser_structure_hash": artifact.document_blocks_hash,
                "warning_count": len(artifact.warnings),
                "content_persisted": False,
                "fidelity_preserved": False,
                "structured_block_count": len(artifact.document_blocks),
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
            parser_structure_hash=artifact.document_blocks_hash,
            warnings=artifact.warnings,
            document=document,
            audit_event_id=audit_event_id,
        )
