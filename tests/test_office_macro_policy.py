from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from suite.platform.office_macro_policy import build_office_macro_policy
from suite.rag.office_active_content import (
    DOCM_MIME_TYPE,
    OfficeActiveContentBlockedError,
    inspect_office_active_content,
)
from suite.rag.parser_worker import ParserWorkerRequest
from suite.rag.rich_document_parser import DOCX_MIME_TYPE, ODT_MIME_TYPE, PDF_MIME_TYPE, RichDocumentParserWorker


def archive_bytes(parts: list[tuple[str, bytes | str]]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, value in parts:
            archive.writestr(name, value)
    return buffer.getvalue()


def docx_parts(*extra: tuple[str, bytes | str]) -> bytes:
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Safe body</w:t></w:r></w:p></w:body></w:document>"
    )
    return archive_bytes([("word/document.xml", document), *extra])


def parser_request(mime_type: str, content: bytes) -> ParserWorkerRequest:
    return ParserWorkerRequest(
        tenant_id="tenant-macro",
        source_object_id="source-macro",
        source_version_id="version-macro",
        source_object_type="document",
        mime_type=mime_type,
        content=content,
    )


def test_macro_policy_is_metadata_only_and_keeps_execution_dispatch_and_stripping_closed() -> None:
    policy = build_office_macro_policy(tenant_id="tenant-macro")

    assert policy.schema_version == "office_macro_policy.v1"
    assert policy.policy_state == "enforced_execution_disabled"
    assert policy.active_content_detection_enforced_by_parser
    assert policy.blocked_mime_types == (DOCM_MIME_TYPE,)
    assert not policy.active_content_execution_allowed
    assert not policy.automatic_active_content_removal_allowed
    assert not policy.blocked_input_extraction_allowed
    assert policy.marked_input_extraction_allowed and policy.marked_input_requires_visible_review
    assert not policy.content_accepted_by_policy_endpoint and not policy.parser_dispatch_allowed
    assert not policy.policy_receipt_persisted and not policy.normal_logs_may_contain_content_or_indicator_paths


@pytest.mark.parametrize(
    ("mime_type", "content", "indicator"),
    [
        (DOCX_MIME_TYPE, docx_parts(("word/vbaProject.bin", b"synthetic")), "docx_vba_project"),
        (DOCM_MIME_TYPE, docx_parts(), "docx_macro_enabled_mime"),
        (DOCX_MIME_TYPE, docx_parts(("word/embeddings/oleObject1.bin", b"synthetic")), "docx_embedded_object"),
        (
            ODT_MIME_TYPE,
            archive_bytes(
                [
                    (
                        "content.xml",
                        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0">'
                        "<office:scripts/></office:document-content>",
                    )
                ]
            ),
            "odf_macro_or_event_script",
        ),
        (PDF_MIME_TYPE, b"%PDF-1.4\n1 0 obj << /OpenAction 2 0 R /JavaScript 3 0 R >>\n%%EOF", "pdf_active_action"),
        (DOCX_MIME_TYPE, docx_parts(("../word/vbaProject.bin", b"synthetic")), "unsafe_archive_structure"),
    ],
)
def test_active_content_is_detected_and_parser_blocks_before_extraction(
    mime_type: str,
    content: bytes,
    indicator: str,
) -> None:
    inspection = inspect_office_active_content(mime_type=mime_type, content=content)

    assert inspection.decision == "block"
    assert indicator in inspection.blocking_indicators
    assert not inspection.extraction_allowed and not inspection.execution_allowed
    with pytest.raises(OfficeActiveContentBlockedError, match="active-content policy blocked"):
        RichDocumentParserWorker().parse(parser_request(mime_type, content))


def test_nonexecuting_signature_is_marked_and_text_extraction_remains_visible_for_review() -> None:
    content = docx_parts(("_xmlsignatures/sig1.xml", "<Signature />"))

    inspection = inspect_office_active_content(mime_type=DOCX_MIME_TYPE, content=content)
    artifact = RichDocumentParserWorker().parse(parser_request(DOCX_MIME_TYPE, content))

    assert inspection.decision == "allow_marked"
    assert inspection.review_markings == ("digital_signature_present",)
    assert inspection.extraction_allowed and not inspection.execution_allowed
    assert artifact.text == "Safe body"
    assert artifact.warnings == ("non-executable security markers require review",)
