from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from docx_running_fixture import (
    FOOTER,
    HEADER,
    RELATIONSHIPS,
    RUNNING_BODY,
    SECOND_FOOTER,
    WORD,
    running_docx,
    running_part,
)
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import DOCX_MIME_TYPE, RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_import_preview import command, source_record, user
from test_rich_document_parser import request_for

BODY_TEXT = "DOCX Body One\nDOCX Body Two\nDOCX Body Three"
PROFILES = (
    {"header": HEADER, "footer": FOOTER},
    {"header": HEADER, "footer": SECOND_FOOTER},
    {"header": "", "footer": SECOND_FOOTER},
)


def _artifact(content: bytes) -> ParsedTextArtifact:
    return RichDocumentParserWorker().parse(request_for(mime_type=DOCX_MIME_TYPE, content=content))


def _preview(content: bytes) -> dict[str, Any]:
    return (
        OfficeImportPreviewService(
            source_repository=InMemorySourceObjectRepository((source_record(content),)),
            audit=InMemoryAuditLogger(),
            parser_dispatch=RichDocumentParserWorker().parse,
        )
        .preview(user_context=user(), command=command())
        .document
    )


def test_docx_resolves_default_running_text_in_section_order() -> None:
    content = running_docx()
    artifact = _artifact(content)
    assert artifact.text == BODY_TEXT
    assert tuple(block["running"] for block in artifact.document_blocks if "running" in block) == PROFILES
    assert artifact.document_blocks_hash == hash_document_blocks(artifact.document_blocks)
    changed = _artifact(running_docx(extra={"word/header1.xml": running_part("hdr", "Another literal")}))
    assert changed.text_hash == artifact.text_hash
    assert changed.document_blocks_hash != artifact.document_blocks_hash
    native = _preview(content)
    profiles = (native["attrs"], native["content"][1]["attrs"], native["content"][3]["attrs"])
    assert tuple(profile["running"] for profile in profiles) == tuple(
        {**literal, "numbering": "none"} for literal in PROFILES
    )


def test_docx_running_text_preserves_literal_spaces_and_accepts_explicitly_disabled_even_odd_mode() -> None:
    content = running_docx(
        extra={
            "word/settings.xml": f'<w:settings xmlns:w="{WORD}"><w:evenAndOddHeaders w:val="0"/></w:settings>',
            "word/header1.xml": (
                f'<w:hdr xmlns:w="{WORD}"><w:p><w:r><w:t xml:space="preserve">  First </w:t></w:r>'
                "<w:r><w:t>Second</w:t></w:r></w:p></w:hdr>"
            ),
        }
    )
    assert _preview(content)["attrs"]["running"]["header"] == "  First Second"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"body": RUNNING_BODY.replace('w:type="default"', 'w:type="even"', 1)},
        {"body": RUNNING_BODY.replace('w:type="default"', 'w:type="first"', 1)},
        {"body": RUNNING_BODY.replace("<w:sectPr>", "<w:sectPr><w:titlePg/>", 1)},
        {"body": RUNNING_BODY.replace('r:id="header1"', 'r:id="footer1"', 1)},
        {"relationships": RELATIONSHIPS.replace('Target="header1.xml"', 'Target="../header1.xml"')},
        {"relationships": RELATIONSHIPS.replace('Target="header1.xml"', 'Target="head%65r1.xml"')},
        {
            "relationships": RELATIONSHIPS.replace(
                'Target="header1.xml"', 'TargetMode="External" Target="https://example.invalid/header1.xml"'
            )
        },
        {"relationships": RELATIONSHIPS.replace('Id="header2"', 'Id="header1"')},
        {"overrides": ""},
        {"extra": {"word/header1.xml": None}},
        {"extra": {"word/header1.xml": running_part("ftr", HEADER)}},
        {"extra": {"word/header1.xml": running_part("hdr", "x" * 65)}},
        {"extra": {"word/header1.xml": running_part("hdr", "First&#x9;Second")}},
        {"extra": {"word/header1.xml": running_part("hdr", "{{field:case-number}}")}},
        {"extra": {"word/header1.xml": running_part("hdr", HEADER).replace("</w:hdr>", "<w:p/></w:hdr>")}},
        {
            "extra": {
                "word/header1.xml": running_part("hdr", HEADER)
                .replace("<w:t>", "<w:instrText>")
                .replace("</w:t>", "</w:instrText>")
            }
        },
        {
            "extra": {
                "word/header1.xml": running_part("hdr", HEADER).replace("<w:r>", "<w:r><w:rPr><w:vanish/></w:rPr>")
            }
        },
        {
            "extra": {
                "word/header1.xml": running_part("hdr", HEADER)
                .replace("<w:r>", "<w:hyperlink><w:r>")
                .replace("</w:r>", "</w:r></w:hyperlink>")
            }
        },
        {"extra": {"word/header1.xml": ("<!DOCTYPE w:hdr []>" + running_part("hdr", HEADER)).encode("utf-16")}},
        {"extra": {"word/header1.xml": (" " * 16384) + running_part("hdr", HEADER)}},
        {"extra": {"word/_rels/HEADER1.xml.rels": "<Relationships/>"}},
        {"extra": {"word/settings.xml": f'<w:settings xmlns:w="{WORD}"><w:evenAndOddHeaders/></w:settings>'}},
    ],
)
def test_unsupported_docx_running_text_preserves_body_extraction_and_refuses_preview(kwargs: dict[str, Any]) -> None:
    content = running_docx(**kwargs)
    artifact = _artifact(content)
    assert artifact.text == BODY_TEXT
    assert artifact.document_blocks[0] == {"kind": "unsupported_section_layout"}
    with pytest.raises(OfficeImportPreviewInvalid, match="unsupported block"):
        _preview(content)


def test_docx_running_text_requires_native_margin_clearance() -> None:
    content = running_docx(body=RUNNING_BODY.replace('w:top="1134"', 'w:top="680"', 1))
    assert _artifact(content).text == BODY_TEXT
    with pytest.raises(OfficeImportPreviewInvalid, match="represented as a native preview"):
        _preview(content)


@pytest.mark.parametrize("changes", [{"numbering": "page"}, {"header": "{{field:case-number}}"}])
def test_preview_rejects_forged_running_text_fields_even_when_rehashed(changes: dict[str, str]) -> None:
    content = running_docx()

    def parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = RichDocumentParserWorker().parse(request)
        first, *rest = artifact.document_blocks
        blocks = ({**first, "running": {**PROFILES[0], **changes}}, *rest)
        return replace(artifact, document_blocks=blocks, document_blocks_hash=hash_document_blocks(blocks))

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(content),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="running-text profile"):
        service.preview(user_context=user(), command=command())
