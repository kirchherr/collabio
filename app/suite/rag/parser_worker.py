from __future__ import annotations

from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from hashlib import sha256
from typing import Protocol

from suite.rag.source_indexing import ExtractedText, ResolvedSource


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{sha256(value).hexdigest()}"


def normalize_extracted_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()


class ParserWorkerError(ValueError):
    pass


class ParserInputTooLargeError(ParserWorkerError):
    pass


class UnsupportedParserInputError(ParserWorkerError):
    pass


class ParserWorker(Protocol):
    def parse(self, request: ParserWorkerRequest) -> ParsedTextArtifact: ...


@dataclass(frozen=True)
class ParserSandboxPolicy:
    max_input_bytes: int = 5_000_000
    max_extracted_characters: int = 1_000_000
    allowed_source_object_types: frozenset[str] = field(
        default_factory=lambda: frozenset({"document", "mail", "attachment", "comment", "wiki", "procedure_doc"})
    )
    allowed_mime_types: frozenset[str] = field(
        default_factory=lambda: frozenset({"text/plain", "text/markdown", "message/rfc822"})
    )
    network_access_allowed: bool = False
    external_processes_allowed: bool = False

    def validate(self, request: ParserWorkerRequest) -> str:
        if self.max_input_bytes < 1:
            raise ValueError("max_input_bytes must be greater than or equal to 1")
        if self.max_extracted_characters < 1:
            raise ValueError("max_extracted_characters must be greater than or equal to 1")
        if not request.tenant_id:
            raise ValueError("tenant_id must not be empty")
        if not request.source_object_id:
            raise ValueError("source_object_id must not be empty")
        if not request.source_version_id:
            raise ValueError("source_version_id must not be empty")
        if request.source_object_type not in self.allowed_source_object_types:
            raise UnsupportedParserInputError(f"unsupported source object type: {request.source_object_type}")
        if len(request.content) > self.max_input_bytes:
            raise ParserInputTooLargeError("parser input exceeds configured byte limit")
        if not request.content:
            raise ParserWorkerError("parser input must not be empty")

        mime_type = request.mime_type.partition(";")[0].strip().lower()
        if mime_type not in self.allowed_mime_types:
            raise UnsupportedParserInputError(f"unsupported mime type: {mime_type}")
        return mime_type


@dataclass(frozen=True)
class ParserWorkerRequest:
    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_object_type: str
    mime_type: str
    content: bytes
    filename: str | None = None


@dataclass(frozen=True)
class ParsedTextArtifact:
    text: str
    parser_name: str
    parser_version: str
    source_object_type: str
    mime_type: str
    input_hash: str
    text_hash: str
    text_byte_length: int
    warnings: tuple[str, ...] = ()


class PolicyEnforcedParserWorker:
    def __init__(
        self,
        *,
        policy: ParserSandboxPolicy | None = None,
        parser_name: str = "policy-enforced-parser-worker",
        parser_version: str = "1",
    ) -> None:
        self.policy = policy or ParserSandboxPolicy()
        self.parser_name = parser_name
        self.parser_version = parser_version

    def parse(self, request: ParserWorkerRequest) -> ParsedTextArtifact:
        mime_type = self.policy.validate(request)
        if mime_type in {"text/plain", "text/markdown"}:
            text = self._parse_utf8_text(request.content)
            warnings: tuple[str, ...] = ()
        elif mime_type == "message/rfc822":
            text, warnings = self._parse_rfc822_message(request.content)
        else:
            raise UnsupportedParserInputError(f"unsupported mime type: {mime_type}")

        normalized = normalize_extracted_text(text)
        if not normalized:
            raise ParserWorkerError("parser output is empty after extraction")
        if len(normalized) > self.policy.max_extracted_characters:
            raise ParserInputTooLargeError("parser output exceeds configured character limit")

        return ParsedTextArtifact(
            text=normalized,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            source_object_type=request.source_object_type,
            mime_type=mime_type,
            input_hash=sha256_bytes(request.content),
            text_hash=sha256_bytes(normalized.encode("utf-8")),
            text_byte_length=len(normalized.encode("utf-8")),
            warnings=warnings,
        )

    def _parse_utf8_text(self, content: bytes) -> str:
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParserWorkerError("text parser requires valid utf-8 input") from exc

    def _parse_rfc822_message(self, content: bytes) -> tuple[str, tuple[str, ...]]:
        try:
            message = BytesParser(policy=policy.default).parsebytes(content)
        except Exception as exc:
            raise ParserWorkerError("failed to parse RFC822 message") from exc

        lines = self._safe_mail_headers(message)
        warnings: list[str] = []
        plain_parts = self._plain_text_mail_parts(message, warnings)
        if plain_parts:
            lines.extend(["", *plain_parts])
        return "\n".join(lines), tuple(warnings)

    def _safe_mail_headers(self, message: EmailMessage) -> list[str]:
        lines: list[str] = []
        for header in ("Subject", "From", "To", "Cc", "Date", "Message-ID"):
            value = message.get(header)
            if value:
                lines.append(f"{header}: {value}")
        return lines

    def _plain_text_mail_parts(self, message: EmailMessage, warnings: list[str]) -> list[str]:
        if not message.is_multipart():
            return self._single_mail_part_text(message, warnings)

        parts: list[str] = []
        for part in message.walk():
            if part.is_multipart():
                continue
            parts.extend(self._single_mail_part_text(part, warnings))
        return parts

    def _single_mail_part_text(self, message: EmailMessage, warnings: list[str]) -> list[str]:
        disposition = message.get_content_disposition()
        content_type = message.get_content_type()
        if disposition == "attachment":
            filename = message.get_filename() or "unnamed"
            warnings.append(f"attachment skipped: {filename}")
            return []
        if content_type == "text/plain":
            content = message.get_content()
            if not isinstance(content, str):
                raise ParserWorkerError("text/plain mail part did not decode to text")
            return [content]
        if content_type == "text/html":
            warnings.append("text/html part skipped")
        else:
            warnings.append(f"unsupported mail part skipped: {content_type}")
        return []


class ParserWorkerTextExtractor:
    def __init__(self, worker: ParserWorker) -> None:
        self.worker = worker

    def extract_text(self, source: ResolvedSource) -> ExtractedText:
        content = source.content_bytes if source.content_bytes is not None else source.text.encode("utf-8")
        artifact = self.worker.parse(
            ParserWorkerRequest(
                tenant_id=source.tenant_id,
                source_object_id=source.object_id,
                source_version_id=source.version_id,
                source_object_type=source.source_object_type,
                mime_type=source.mime_type,
                content=content,
            )
        )
        return ExtractedText(text=artifact.text)
