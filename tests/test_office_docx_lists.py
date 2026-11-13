from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from docx_list_fixture import LIST_BODY, NUMBERING, item, list_docx
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import DOCX_MIME_TYPE, RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_import_preview import command, source_record, user
from test_rich_document_parser import request_for


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


def test_docx_list_nesting_restart_and_continuation_preserve_body_order() -> None:
    content = list_docx()
    artifact = _artifact(content)
    assert artifact.text.splitlines() == [
        "Erster Hauptpunkt",
        "Ein Unterpunkt",
        "Dritter Tiefenpunkt",
        "Vierter Tiefenpunkt",
        "Neuer Unterpunkt",
        "Tiefenpunkt neu",
        "Zweiter Hauptpunkt",
        "Zwischentext",
        "Fortsetzung",
        "Neuer Start",
        "Alte Folge",
    ]
    changed = _artifact(list_docx(numbering=NUMBERING.replace('w:val="9"', 'w:val="11"')))
    assert changed.text_hash == artifact.text_hash
    assert changed.document_blocks_hash != artifact.document_blocks_hash
    first, divider, continuation, restart, resumed = _preview(content)["content"]
    assert divider["type"] == "paragraph"
    assert [node["attrs"]["start"] for node in (first, continuation, restart, resumed)] == [4, 6, 9, 7]
    children = first["content"][0]["content"][1]
    assert children["type"] == "bulletList"
    nested = [entry["content"][1] for entry in children["content"]]
    assert [node["attrs"]["start"] for node in nested] == [3, 3]
    assert [len(node["content"]) for node in nested] == [2, 1]


def test_explicit_zero_removes_numbering_and_preserves_continuation() -> None:
    content = list_docx(item("Vorher", 0) + item("Ohne", 0, 0) + item("Nachher", 0))
    before, divider, after = _preview(content)["content"]
    assert divider["type"] == "paragraph"
    assert (before["attrs"]["start"], after["attrs"]["start"]) == (4, 5)


@pytest.mark.parametrize(
    ("body", "numbering"),
    [
        (LIST_BODY, None),
        (item("Text", 0, 99), NUMBERING),
        (item("Text", 3), NUMBERING),
        (item("Text", 1), NUMBERING),
        (item("Text", 0) + item("Kind", 2), NUMBERING),
        (item("Text", 0) + item("Kind", 1, 6), NUMBERING),
        (item("Text", 0) + item("", 0), NUMBERING),
        (item("Text", 0), NUMBERING.replace("%1.", "%1.%2.")),
        (item("Text", 0), NUMBERING.replace('w:val="decimal"', 'w:val="upperRoman"')),
        (
            item("Text", 0) + item("Kind", 1),
            NUMBERING.replace('<w:lvl w:ilvl="1">', '<w:lvl w:ilvl="1"><w:lvlRestart w:val="0"/>'),
        ),
        (item("Text", 0, 6), NUMBERING.replace('<w:startOverride w:val="9"/>', '<w:lvl w:ilvl="0"/>')),
        (item("Text", 0), NUMBERING.replace('w:val="4"', 'w:val="0"')),
        (item("Text", 0), NUMBERING.replace('w:numId="6"', 'w:numId="5"')),
    ],
)
def test_unsupported_docx_lists_refuse_preview_but_preserve_body_text(body: str, numbering: str | None) -> None:
    content = list_docx(body, numbering)
    artifact = _artifact(content)
    assert artifact.text
    assert artifact.document_blocks[0] == {"kind": "unsupported_list_layout"}
    with pytest.raises(OfficeImportPreviewInvalid, match="unsupported block"):
        _preview(content)


@pytest.mark.parametrize("start", [True, 0, 1_000_000])
def test_import_independently_rejects_forged_list_starts(start: Any) -> None:
    content = list_docx()

    def parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = RichDocumentParserWorker().parse(request)
        first, *rest = artifact.document_blocks
        blocks = ({**first, "list": {**first["list"], "start": start}}, *rest)
        return replace(artifact, document_blocks=blocks, document_blocks_hash=hash_document_blocks(blocks))

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(content),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="nested list"):
        service.preview(user_context=user(), command=command())
