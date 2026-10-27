from pathlib import Path

from suite.platform.office_parser_worker_plan import build_office_parser_worker_plan
from suite.rag.rich_document_parser import RichDocumentParserWorker

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_office_parser_worker_plan_matches_existing_bounded_development_parser() -> None:
    plan = build_office_parser_worker_plan(tenant_id="tenant-demo")
    worker = RichDocumentParserWorker()

    assert plan.schema_version == "office_parser_worker_plan.v1"
    assert plan.plan_state == "planned_dispatch_closed"
    assert plan.worker_profile_id == f"{worker.parser_name}:{worker.parser_version}"
    assert tuple(sorted(worker.policy.allowed_mime_types)) == plan.supported_mime_types
    assert worker.policy.max_input_bytes == plan.max_input_bytes
    assert worker.max_archive_uncompressed_bytes == plan.max_archive_uncompressed_bytes
    assert worker.policy.max_extracted_characters == plan.max_extracted_characters
    assert not worker.policy.network_access_allowed and not worker.policy.external_processes_allowed
    assert not plan.dispatch_allowed and not plan.production_admitted
    assert not plan.content_accepted_by_plan_endpoint and not plan.output_trusted_without_validation
    assert "malicious_document_corpus_not_verified" in plan.blockers


def test_office_parser_worker_compose_profile_is_no_network_non_root_read_only_and_bounded() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    service = compose.split("\n  rich-document-parser:\n", maxsplit=1)[1]
    service = service.split("\n  legacy-sql-metadata-worker:\n", maxsplit=1)[0]

    assert 'network_mode: "none"' in service
    assert 'user: "1000:1000"' in service
    assert "read_only: true" in service
    assert "cap_drop:\n      - ALL" in service
    assert "no-new-privileges:true" in service
    assert "/tmp:size=64m,noexec,nosuid,nodev" in service
    assert "mem_limit: 256m" in service
    assert "pids_limit: 64" in service
    assert "cpus: 1" in service
    assert "./app:/workspace/app:ro" in service
    assert "ports:" not in service
    assert "depends_on:" in service
    assert "rich-document-parser-socket-init:" in service
    assert "condition: service_completed_successfully" in service
    assert "DATABASE_DSN" not in service and "S3_" not in service and "API_KEY" not in service
