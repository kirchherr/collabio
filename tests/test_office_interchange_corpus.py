from collections import Counter

import pytest

from suite.platform.office_interchange_corpus import (
    build_office_interchange_corpus,
    build_office_interchange_corpus_bytes,
)
from suite.rag.office_active_content import OfficeActiveContentBlockedError, inspect_office_active_content
from suite.rag.parser_worker import ParserWorkerRequest, sha256_bytes
from suite.rag.rich_document_parser import RichDocumentParserWorker


def test_interchange_corpus_is_deterministic_exact_and_exercises_real_parser_boundary() -> None:
    first = build_office_interchange_corpus(tenant_id="tenant-corpus")
    second = build_office_interchange_corpus(tenant_id="tenant-corpus")
    corpus = build_office_interchange_corpus_bytes()

    assert first == second
    assert len(first.fixtures) == 9 and len(corpus) == 9
    assert Counter(item.format_id for item in first.fixtures) == {"ooxml_docx": 3, "odf_odt": 3, "pdf": 3}
    assert Counter(item.expected_policy_decision for item in first.fixtures) == {
        "allow": 3,
        "allow_marked": 3,
        "block": 3,
    }
    assert first.manifest_sha256.startswith("sha256:")
    assert not first.fixture_bytes_returned and not first.import_dispatch_allowed
    assert not first.export_engine_available and not first.round_trip_fidelity_claimed

    worker = RichDocumentParserWorker()
    for fixture in first.fixtures:
        content = corpus[fixture.filename]
        assert fixture.source_sha256 == sha256_bytes(content)
        assert fixture.source_byte_length == len(content)
        decision = inspect_office_active_content(mime_type=fixture.mime_type, content=content)
        assert decision.decision == fixture.expected_policy_decision
        request = ParserWorkerRequest(
            tenant_id="tenant-corpus",
            source_object_id=fixture.fixture_id,
            source_version_id="v1",
            source_object_type="document",
            mime_type=fixture.mime_type,
            content=content,
        )
        if fixture.expected_parser_outcome == "blocked":
            with pytest.raises(OfficeActiveContentBlockedError):
                worker.parse(request)
            continue
        artifact = worker.parse(request)
        assert artifact.text_hash == fixture.expected_text_sha256
        assert len(artifact.warnings) == fixture.expected_warning_count
        assert fixture.export_expected == "blocked_no_engine"
        assert not fixture.round_trip_fidelity_expected
