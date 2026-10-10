from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

OfficeParserMimeType = Literal[
    "application/pdf",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]
OfficeParserSourceRequirement = Literal[
    "authoritative_tenant_and_object_acl",
    "exact_source_version_and_manifest_hash",
    "classification_retention_legal_hold_and_acl_version",
    "malware_and_active_content_decision",
]
OfficeParserPipelineStep = Literal[
    "authorize_before_source_read",
    "materialize_exact_content_addressed_input",
    "parse_in_no_network_one_shot_worker",
    "validate_bounded_result_schema_and_hashes",
    "reauthorize_before_result_use",
    "erase_worker_scratch",
]
OfficeParserIsolationRequirement = Literal[
    "network_mode_none",
    "read_only_root_filesystem",
    "non_root_uid_1000",
    "all_linux_capabilities_dropped",
    "no_new_privileges",
    "noexec_nosuid_nodev_tmpfs_only",
    "no_database_object_storage_or_provider_credentials",
    "no_direct_storage_or_vector_writes",
    "bounded_cpu_memory_pids_and_wall_clock",
]
OfficeParserPlanBlocker = Literal[
    "content_addressed_input_materializer_not_implemented",
    "write_only_result_handoff_not_implemented",
    "job_scheduler_and_timeout_enforcement_not_implemented",
    "malicious_document_corpus_not_verified",
    "sandbox_escape_fuzzing_not_verified",
    "non_empty_parser_recovery_not_verified",
    "production_worker_image_admission_not_verified",
]

OFFICE_PARSER_SUPPORTED_MIME_TYPES: tuple[OfficeParserMimeType, ...] = (
    "application/pdf",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)
OFFICE_PARSER_SOURCE_REQUIREMENTS: tuple[OfficeParserSourceRequirement, ...] = (
    "authoritative_tenant_and_object_acl",
    "exact_source_version_and_manifest_hash",
    "classification_retention_legal_hold_and_acl_version",
    "malware_and_active_content_decision",
)
OFFICE_PARSER_PIPELINE: tuple[OfficeParserPipelineStep, ...] = (
    "authorize_before_source_read",
    "materialize_exact_content_addressed_input",
    "parse_in_no_network_one_shot_worker",
    "validate_bounded_result_schema_and_hashes",
    "reauthorize_before_result_use",
    "erase_worker_scratch",
)
OFFICE_PARSER_ISOLATION_REQUIREMENTS: tuple[OfficeParserIsolationRequirement, ...] = (
    "network_mode_none",
    "read_only_root_filesystem",
    "non_root_uid_1000",
    "all_linux_capabilities_dropped",
    "no_new_privileges",
    "noexec_nosuid_nodev_tmpfs_only",
    "no_database_object_storage_or_provider_credentials",
    "no_direct_storage_or_vector_writes",
    "bounded_cpu_memory_pids_and_wall_clock",
)
OFFICE_PARSER_PLAN_BLOCKERS: tuple[OfficeParserPlanBlocker, ...] = (
    "content_addressed_input_materializer_not_implemented",
    "write_only_result_handoff_not_implemented",
    "job_scheduler_and_timeout_enforcement_not_implemented",
    "malicious_document_corpus_not_verified",
    "sandbox_escape_fuzzing_not_verified",
    "non_empty_parser_recovery_not_verified",
    "production_worker_image_admission_not_verified",
)


class OfficeParserWorkerPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    schema_version: Literal["office_parser_worker_plan.v1"] = "office_parser_worker_plan.v1"
    plan_state: Literal["planned_dispatch_closed"] = "planned_dispatch_closed"
    worker_profile_id: Literal["rich-document-parser-worker:1"] = "rich-document-parser-worker:1"
    development_manifest_present: bool = True
    supported_mime_types: tuple[OfficeParserMimeType, ...] = OFFICE_PARSER_SUPPORTED_MIME_TYPES
    source_requirements: tuple[OfficeParserSourceRequirement, ...] = OFFICE_PARSER_SOURCE_REQUIREMENTS
    pipeline: tuple[OfficeParserPipelineStep, ...] = OFFICE_PARSER_PIPELINE
    isolation_requirements: tuple[OfficeParserIsolationRequirement, ...] = OFFICE_PARSER_ISOLATION_REQUIREMENTS
    max_input_bytes: int = 25_000_000
    max_archive_uncompressed_bytes: int = 20_000_000
    max_extracted_characters: int = 2_000_000
    memory_limit_bytes: int = 268_435_456
    pids_limit: int = 64
    cpu_limit: float = 1.0
    dispatch_allowed: bool = False
    production_admitted: bool = False
    content_accepted_by_plan_endpoint: bool = False
    direct_storage_mutation_allowed: bool = False
    direct_vector_writes_allowed: bool = False
    normal_logs_may_contain_content: bool = False
    output_trusted_without_validation: bool = False
    blockers: tuple[OfficeParserPlanBlocker, ...] = OFFICE_PARSER_PLAN_BLOCKERS
    audit_event_id: str = ""


def build_office_parser_worker_plan(*, tenant_id: str) -> OfficeParserWorkerPlanResponse:
    return OfficeParserWorkerPlanResponse(tenant_id=tenant_id)
