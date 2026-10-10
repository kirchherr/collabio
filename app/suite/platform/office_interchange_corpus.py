from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from pydantic import BaseModel, ConfigDict

from suite.rag.parser_worker import sha256_bytes
from suite.rag.rich_document_parser import DOCX_MIME_TYPE, ODT_MIME_TYPE, PDF_MIME_TYPE

OfficeCorpusFormat = Literal["ooxml_docx", "odf_odt", "pdf"]
OfficeCorpusScenario = Literal["safe_text", "marked_indicator", "blocked_active_content"]
OfficeCorpusPolicyDecision = Literal["allow", "allow_marked", "block"]
OfficeCorpusParserOutcome = Literal["parsed", "blocked"]


class OfficeInterchangeCorpusFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: str
    format_id: OfficeCorpusFormat
    mime_type: str
    filename: str
    scenario: OfficeCorpusScenario
    source_sha256: str
    source_byte_length: int
    expected_policy_decision: OfficeCorpusPolicyDecision
    expected_parser_outcome: OfficeCorpusParserOutcome
    expected_text_sha256: str | None = None
    expected_warning_count: int = 0
    synthetic_repository_fixture: Literal[True] = True
    export_expected: Literal["blocked_no_engine"] = "blocked_no_engine"
    round_trip_fidelity_expected: Literal[False] = False


class OfficeInterchangeCorpusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    schema_version: Literal["office_interchange_corpus_manifest.v1"] = "office_interchange_corpus_manifest.v1"
    corpus_state: Literal["deterministic_fixtures_export_closed"] = "deterministic_fixtures_export_closed"
    fixtures: tuple[OfficeInterchangeCorpusFixture, ...]
    manifest_sha256: str
    fixture_bytes_returned: Literal[False] = False
    import_dispatch_allowed: Literal[False] = False
    export_engine_available: Literal[False] = False
    round_trip_fidelity_claimed: Literal[False] = False
    production_admitted: Literal[False] = False
    audit_event_id: str = ""


def _zip_bytes(parts: tuple[tuple[str, bytes], ...]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in parts:
            info = ZipInfo(filename=name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def _docx_bytes(*, marker: str | None = None) -> bytes:
    document = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body><w:p><w:r><w:t>Corpus DOCX text</w:t></w:r></w:p></w:body></w:document>"
    )
    parts: list[tuple[str, bytes]] = [("word/document.xml", document)]
    if marker == "signature":
        parts.append(("_xmlsignatures/sig1.xml", b"<Signature />"))
    elif marker == "vba":
        parts.append(("word/vbaProject.bin", b"synthetic blocked fixture"))
    return _zip_bytes(tuple(parts))


def _odt_bytes(*, marker: str | None = None) -> bytes:
    document = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        b'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        b"<office:body><office:text><text:p>Corpus ODT text</text:p></office:text></office:body>"
        b"</office:document-content>"
    )
    parts: list[tuple[str, bytes]] = [("content.xml", document)]
    if marker == "signature":
        parts.append(("META-INF/documentsignatures.xml", b"<Signature />"))
    elif marker == "script":
        parts.append(("Basic/Module1.xml", b"<script />"))
    return _zip_bytes(tuple(parts))


def _pdf_bytes(*, marker: str | None = None) -> bytes:
    stream = b"BT /F1 12 Tf 72 712 Td (Corpus PDF text) Tj ET"
    suffix = b""
    if marker == "signature":
        suffix = b"\n2 0 obj << /Type /Sig >> endobj"
    elif marker == "javascript":
        suffix = b"\n2 0 obj << /OpenAction 3 0 R /JavaScript 4 0 R >> endobj"
    return (
        b"%PDF-1.4\n1 0 obj\n"
        + f"<< /Length {len(stream)} >>\n".encode()
        + b"stream\n"
        + stream
        + b"\nendstream\nendobj"
        + suffix
        + b"\n%%EOF"
    )


def build_office_interchange_corpus_bytes() -> dict[str, bytes]:
    return {
        "docx-safe-text.docx": _docx_bytes(),
        "docx-marked-signature.docx": _docx_bytes(marker="signature"),
        "docx-blocked-vba.docx": _docx_bytes(marker="vba"),
        "odt-safe-text.odt": _odt_bytes(),
        "odt-marked-signature.odt": _odt_bytes(marker="signature"),
        "odt-blocked-script.odt": _odt_bytes(marker="script"),
        "pdf-safe-text.pdf": _pdf_bytes(),
        "pdf-marked-signature.pdf": _pdf_bytes(marker="signature"),
        "pdf-blocked-javascript.pdf": _pdf_bytes(marker="javascript"),
    }


def _fixture(
    *,
    fixture_id: str,
    format_id: OfficeCorpusFormat,
    mime_type: str,
    filename: str,
    scenario: OfficeCorpusScenario,
    decision: OfficeCorpusPolicyDecision,
    expected_text: str | None,
    warning_count: int,
    corpus: dict[str, bytes],
) -> OfficeInterchangeCorpusFixture:
    content = corpus[filename]
    return OfficeInterchangeCorpusFixture(
        fixture_id=fixture_id,
        format_id=format_id,
        mime_type=mime_type,
        filename=filename,
        scenario=scenario,
        source_sha256=sha256_bytes(content),
        source_byte_length=len(content),
        expected_policy_decision=decision,
        expected_parser_outcome="blocked" if decision == "block" else "parsed",
        expected_text_sha256=sha256_bytes(expected_text.encode()) if expected_text is not None else None,
        expected_warning_count=warning_count,
    )


def build_office_interchange_corpus(*, tenant_id: str) -> OfficeInterchangeCorpusResponse:
    corpus = build_office_interchange_corpus_bytes()
    fixtures = (
        _fixture(
            fixture_id="docx-safe-text",
            format_id="ooxml_docx",
            mime_type=DOCX_MIME_TYPE,
            filename="docx-safe-text.docx",
            scenario="safe_text",
            decision="allow",
            expected_text="Corpus DOCX text",
            warning_count=0,
            corpus=corpus,
        ),
        _fixture(
            fixture_id="docx-marked-signature",
            format_id="ooxml_docx",
            mime_type=DOCX_MIME_TYPE,
            filename="docx-marked-signature.docx",
            scenario="marked_indicator",
            decision="allow_marked",
            expected_text="Corpus DOCX text",
            warning_count=1,
            corpus=corpus,
        ),
        _fixture(
            fixture_id="docx-blocked-vba",
            format_id="ooxml_docx",
            mime_type=DOCX_MIME_TYPE,
            filename="docx-blocked-vba.docx",
            scenario="blocked_active_content",
            decision="block",
            expected_text=None,
            warning_count=0,
            corpus=corpus,
        ),
        _fixture(
            fixture_id="odt-safe-text",
            format_id="odf_odt",
            mime_type=ODT_MIME_TYPE,
            filename="odt-safe-text.odt",
            scenario="safe_text",
            decision="allow",
            expected_text="Corpus ODT text",
            warning_count=0,
            corpus=corpus,
        ),
        _fixture(
            fixture_id="odt-marked-signature",
            format_id="odf_odt",
            mime_type=ODT_MIME_TYPE,
            filename="odt-marked-signature.odt",
            scenario="marked_indicator",
            decision="allow_marked",
            expected_text="Corpus ODT text",
            warning_count=1,
            corpus=corpus,
        ),
        _fixture(
            fixture_id="odt-blocked-script",
            format_id="odf_odt",
            mime_type=ODT_MIME_TYPE,
            filename="odt-blocked-script.odt",
            scenario="blocked_active_content",
            decision="block",
            expected_text=None,
            warning_count=0,
            corpus=corpus,
        ),
        _fixture(
            fixture_id="pdf-safe-text",
            format_id="pdf",
            mime_type=PDF_MIME_TYPE,
            filename="pdf-safe-text.pdf",
            scenario="safe_text",
            decision="allow",
            expected_text="Corpus PDF text",
            warning_count=1,
            corpus=corpus,
        ),
        _fixture(
            fixture_id="pdf-marked-signature",
            format_id="pdf",
            mime_type=PDF_MIME_TYPE,
            filename="pdf-marked-signature.pdf",
            scenario="marked_indicator",
            decision="allow_marked",
            expected_text="Corpus PDF text",
            warning_count=2,
            corpus=corpus,
        ),
        _fixture(
            fixture_id="pdf-blocked-javascript",
            format_id="pdf",
            mime_type=PDF_MIME_TYPE,
            filename="pdf-blocked-javascript.pdf",
            scenario="blocked_active_content",
            decision="block",
            expected_text=None,
            warning_count=0,
            corpus=corpus,
        ),
    )
    digest = hashlib.sha256(
        "\n".join(
            "|".join(
                (
                    fixture.fixture_id,
                    fixture.source_sha256,
                    fixture.expected_policy_decision,
                    fixture.expected_text_sha256 or "-",
                )
            )
            for fixture in fixtures
        ).encode()
    ).hexdigest()
    return OfficeInterchangeCorpusResponse(
        tenant_id=tenant_id,
        fixtures=fixtures,
        manifest_sha256=f"sha256:{digest}",
    )
