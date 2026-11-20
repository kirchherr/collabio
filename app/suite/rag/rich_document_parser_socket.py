"""Bounded Unix-socket transport for the isolated rich-document parser."""

from __future__ import annotations

import json
import os
import socket
import struct
from dataclasses import asdict
from pathlib import Path
from typing import Any

from suite.rag.office_active_content import OfficeActiveContentBlockedError
from suite.rag.parser_worker import (
    ParsedTextArtifact,
    ParserInputTooLargeError,
    ParserWorkerError,
    ParserWorkerRequest,
    UnsupportedParserInputError,
)
from suite.rag.rich_document_parser import RichDocumentParserWorker

RICH_DOCUMENT_PARSER_SOCKET = "/run/rich-document-parser/parser.sock"
MAX_PARSER_METADATA_BYTES = 64 * 1024
MAX_PARSER_INPUT_BYTES = 25_000_000
MAX_PARSER_RESPONSE_BYTES = 4 * 1024 * 1024
_REQUEST_HEADER = struct.Struct(">II")
_RESPONSE_HEADER = struct.Struct(">cI")
_REQUEST_FIELDS = {
    "tenant_id",
    "source_object_id",
    "source_version_id",
    "source_object_type",
    "mime_type",
    "filename",
}


class RichDocumentParserUnavailable(RuntimeError):
    """Raised when the isolated worker cannot be reached or violates its protocol."""


def _receive_exact(connection: socket.socket, length: int) -> bytes:
    value = bytearray()
    while len(value) < length:
        part = connection.recv(min(65_536, length - len(value)))
        if not part:
            raise RichDocumentParserUnavailable("rich document parser response is incomplete")
        value.extend(part)
    return bytes(value)


def _request_metadata(request: ParserWorkerRequest) -> bytes:
    return json.dumps(
        {
            "tenant_id": request.tenant_id,
            "source_object_id": request.source_object_id,
            "source_version_id": request.source_version_id,
            "source_object_type": request.source_object_type,
            "mime_type": request.mime_type,
            "filename": request.filename,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def parse_rich_document(
    request: ParserWorkerRequest,
    *,
    socket_path: str = RICH_DOCUMENT_PARSER_SOCKET,
    timeout_seconds: float = 15,
) -> ParsedTextArtifact:
    metadata = _request_metadata(request)
    if len(metadata) > MAX_PARSER_METADATA_BYTES or not 1 <= len(request.content) <= MAX_PARSER_INPUT_BYTES:
        raise ParserInputTooLargeError("rich document parser request exceeds its transport limits")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout_seconds)
            connection.connect(socket_path)
            connection.sendall(_REQUEST_HEADER.pack(len(metadata), len(request.content)) + metadata + request.content)
            status, response_length = _RESPONSE_HEADER.unpack(_receive_exact(connection, _RESPONSE_HEADER.size))
            if not 1 <= response_length <= MAX_PARSER_RESPONSE_BYTES:
                raise RichDocumentParserUnavailable("rich document parser returned an invalid response length")
            payload = json.loads(_receive_exact(connection, response_length))
    except (OSError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
        raise RichDocumentParserUnavailable("rich document parser is unavailable") from exc
    if not isinstance(payload, dict):
        raise RichDocumentParserUnavailable("rich document parser returned an invalid response")
    if status == b"E":
        code = payload.get("code")
        if code == "active_content_blocked":
            raise OfficeActiveContentBlockedError("active document content is blocked")
        if code == "input_too_large":
            raise ParserInputTooLargeError("rich document input exceeds admitted limits")
        if code == "unsupported_input":
            raise UnsupportedParserInputError("rich document input is unsupported")
        raise ParserWorkerError("rich document parsing failed")
    if status != b"O":
        raise RichDocumentParserUnavailable("rich document parser returned an invalid status")
    expected_fields = {
        "text",
        "parser_name",
        "parser_version",
        "source_object_type",
        "mime_type",
        "input_hash",
        "text_hash",
        "text_byte_length",
        "warnings",
        "document_blocks",
        "document_blocks_hash",
    }
    try:
        if set(payload) != expected_fields:
            raise ValueError
        text_fields = (
            "text",
            "parser_name",
            "parser_version",
            "source_object_type",
            "mime_type",
            "input_hash",
            "text_hash",
            "document_blocks_hash",
        )
        if any(not isinstance(payload[field], str) for field in text_fields):
            raise ValueError
        if type(payload["text_byte_length"]) is not int or payload["text_byte_length"] < 1:
            raise ValueError
        if not isinstance(payload["warnings"], list) or any(
            not isinstance(value, str) for value in payload["warnings"]
        ):
            raise ValueError
        if not isinstance(payload["document_blocks"], list) or any(
            not isinstance(value, dict) for value in payload["document_blocks"]
        ):
            raise ValueError
        return ParsedTextArtifact(
            text=payload["text"],
            parser_name=payload["parser_name"],
            parser_version=payload["parser_version"],
            source_object_type=payload["source_object_type"],
            mime_type=payload["mime_type"],
            input_hash=payload["input_hash"],
            text_hash=payload["text_hash"],
            text_byte_length=payload["text_byte_length"],
            warnings=tuple(payload["warnings"]),
            document_blocks=tuple(payload["document_blocks"]),
            document_blocks_hash=payload["document_blocks_hash"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RichDocumentParserUnavailable("rich document parser returned an invalid artifact") from exc


def _request_from_connection(connection: socket.socket) -> ParserWorkerRequest:
    metadata_length, content_length = _REQUEST_HEADER.unpack(_receive_exact(connection, _REQUEST_HEADER.size))
    if not 1 <= metadata_length <= MAX_PARSER_METADATA_BYTES:
        raise ParserWorkerError("parser metadata exceeds its transport limit")
    if not 1 <= content_length <= MAX_PARSER_INPUT_BYTES:
        raise ParserInputTooLargeError("parser input exceeds its transport limit")
    metadata: Any = json.loads(_receive_exact(connection, metadata_length))
    if not isinstance(metadata, dict) or set(metadata) != _REQUEST_FIELDS:
        raise ParserWorkerError("parser metadata is invalid")
    string_fields = _REQUEST_FIELDS - {"filename"}
    if any(not isinstance(metadata[field], str) or not metadata[field] for field in string_fields):
        raise ParserWorkerError("parser metadata is invalid")
    filename = metadata["filename"]
    if filename is not None and not isinstance(filename, str):
        raise ParserWorkerError("parser filename is invalid")
    return ParserWorkerRequest(
        tenant_id=metadata["tenant_id"],
        source_object_id=metadata["source_object_id"],
        source_version_id=metadata["source_version_id"],
        source_object_type=metadata["source_object_type"],
        mime_type=metadata["mime_type"],
        content=_receive_exact(connection, content_length),
        filename=filename,
    )


def _error_code(error: Exception) -> str:
    if isinstance(error, OfficeActiveContentBlockedError):
        return "active_content_blocked"
    if isinstance(error, ParserInputTooLargeError):
        return "input_too_large"
    if isinstance(error, UnsupportedParserInputError):
        return "unsupported_input"
    return "parse_failed"


def _send_payload(connection: socket.socket, status: bytes, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_PARSER_RESPONSE_BYTES:
        status = b"E"
        encoded = b'{"code":"parse_failed"}'
    connection.sendall(_RESPONSE_HEADER.pack(status, len(encoded)) + encoded)


def handle_rich_document_parser_connection(
    connection: socket.socket,
    *,
    worker: RichDocumentParserWorker,
) -> None:
    connection.settimeout(20)
    try:
        artifact = worker.parse(_request_from_connection(connection))
        _send_payload(connection, b"O", asdict(artifact))
    except (
        ParserWorkerError,
        RichDocumentParserUnavailable,
        ValueError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        try:
            _send_payload(connection, b"E", {"code": _error_code(exc)})
        except OSError:
            return


def serve_rich_document_parser(
    *,
    socket_path: str = RICH_DOCUMENT_PARSER_SOCKET,
    worker: RichDocumentParserWorker | None = None,
) -> None:
    parser = worker or RichDocumentParserWorker()
    target = Path(socket_path)
    target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(socket_path)
        os.chmod(socket_path, 0o666)
        server.listen(8)
        while True:
            connection, _ = server.accept()
            with connection:
                handle_rich_document_parser_connection(connection, worker=parser)
