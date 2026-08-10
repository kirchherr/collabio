from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.platform.knowledge_base import KnowledgeBaseArticleService
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry
from suite.platform.source_object_details import build_source_object_metadata_detail_response
from suite.storage.source_objects import SourceObjectRepository, SourceObjectType

OFFICE_EDIT_ADAPTER_CONTRACT_VERSION = "office_edit_adapter.v1"
OFFICE_EDIT_EVALUATION_SCHEMA_VERSION = "office_edit_adapter_evaluation.v1"
GENOFFICE_EVALUATION_POLICY_SCHEMA_VERSION = "genoffice_evaluation_policy.v1"
GENOFFICE_DOCX_EVALUATION_ADAPTER_ID = "genoffice-docx-quick-edit-evaluation.v1"
GENOFFICE_UPSTREAM_REPOSITORY = "https://github.com/genspark-ai/genoffice"
GENOFFICE_UPSTREAM_COMMIT = "fd33934dab1fdf8666af3f88b9794e7b4e19474a"
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DEFAULT_GENOFFICE_EVALUATION_POLICY_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "operations" / "genoffice_evaluation_policy.json"
)
SHA256_REF_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
COMMIT_PATTERN = re.compile(r"^[a-f0-9]{40}$")

GENOFFICE_SELECTED_SOURCE_SCOPES = ("packages/docx-engine/**",)
GENOFFICE_REFERENCE_ONLY_SOURCE_SCOPES = (
    "packages/pptx-engine/**",
    "packages/pptx-render/**",
    "apps/sheets/native/xlsx-engine/**",
)
GENOFFICE_PROHIBITED_SOURCE_SCOPES = (
    "ee/**",
    "apps/shell/**",
    "packages/ai-provider/**",
    "packages/ai-search/**",
)
OFFICE_EDIT_REQUIRED_GATES = (
    "legal_notice_trademark_and_enterprise_tree_review",
    "exact_upstream_commit_and_source_scope_manifest",
    "dependency_lock_sbom_vulnerability_and_license_review",
    "reproducible_build_and_provenance",
    "malicious_ooxml_and_archive_expansion_corpus",
    "macro_ole_external_relationship_and_template_policy",
    "signed_document_preservation_and_derived_version_policy",
    "word_libreoffice_genoffice_fidelity_golden_corpus",
    "safe_export_and_high_fidelity_export_modes",
    "isolated_no_egress_non_root_worker",
    "cpu_memory_wallclock_input_output_and_part_limits",
    "source_blind_candidate_revalidation",
    "canonical_pdf_preview_before_commit",
    "authoritative_acl_and_tenant_revalidation_before_commit",
    "human_confirmed_new_source_object_version",
    "append_only_edit_receipt_and_engine_hash_binding",
    "draft_journal_candidate_version_and_receipt_recovery_drill",
    "wopi_collaboration_kept_outside_quick_edit_adapter",
    "local_llm_gateway_only_with_draft_only_typed_tools",
)

ModuleRegistryStore = InMemoryModuleRegistry | PgModuleRegistry


class OfficeEditAdapterEvaluationBlocked(ValueError):
    pass


class OfficeEditEvaluationRoute(StrEnum):
    DOCX_QUICK_EDIT_ISOLATED_SPIKE = "docx_quick_edit_isolated_spike"
    UNSUPPORTED = "unsupported"


class GenOfficeUpstreamPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_url: str
    commit: str
    root_license_spdx: str
    enterprise_tree: str
    enterprise_tree_included: bool
    trademark_use_allowed: bool
    mutable_ref_allowed: bool

    @model_validator(mode="after")
    def require_exact_upstream_boundary(self) -> GenOfficeUpstreamPolicy:
        if self.repository_url != GENOFFICE_UPSTREAM_REPOSITORY:
            raise ValueError("GenOffice repository URL is not the reviewed upstream")
        if self.commit != GENOFFICE_UPSTREAM_COMMIT or not COMMIT_PATTERN.fullmatch(self.commit):
            raise ValueError("GenOffice upstream must use the exact reviewed commit")
        if self.root_license_spdx != "Apache-2.0":
            raise ValueError("GenOffice root source scope must remain Apache-2.0")
        if self.enterprise_tree != "ee/**" or self.enterprise_tree_included:
            raise ValueError("GenOffice enterprise source tree must remain excluded")
        if self.trademark_use_allowed or self.mutable_ref_allowed:
            raise ValueError("GenOffice trademark use and mutable upstream refs remain forbidden")
        return self


class GenOfficeSourceScopePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_import_candidates: tuple[str, ...]
    reference_only_candidates: tuple[str, ...]
    prohibited_scopes: tuple[str, ...]
    source_import_allowed: bool

    @model_validator(mode="after")
    def require_narrow_deferred_source_scope(self) -> GenOfficeSourceScopePolicy:
        if self.selected_import_candidates != GENOFFICE_SELECTED_SOURCE_SCOPES:
            raise ValueError("only the reviewed DOCX engine may be an import candidate")
        if self.reference_only_candidates != GENOFFICE_REFERENCE_ONLY_SOURCE_SCOPES:
            raise ValueError("GenOffice reference-only source scopes changed")
        if self.prohibited_scopes != GENOFFICE_PROHIBITED_SOURCE_SCOPES:
            raise ValueError("GenOffice prohibited source scopes changed")
        if self.source_import_allowed:
            raise ValueError("GenOffice source import remains blocked during evaluation")
        return self


class OfficeEditSeparationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_adapter_id: str
    quick_edit_strategy: str
    full_collaboration_strategy: str
    ai_strategy: str

    @model_validator(mode="after")
    def require_separate_office_boundaries(self) -> OfficeEditSeparationPolicy:
        if self.preview_adapter_id != "canonical-pdf-libreoffice-pdfjs.v1":
            raise ValueError("office editing must retain the selected preview adapter")
        if self.quick_edit_strategy != "collabio_native_candidate_version":
            raise ValueError("quick edit must create a Collabio candidate version")
        if self.full_collaboration_strategy != "separate_wopi_adapter":
            raise ValueError("full collaboration must remain behind a separate WOPI adapter")
        if self.ai_strategy != "local_llm_gateway_draft_only":
            raise ValueError("office AI must remain draft-only behind the Local LLM Gateway")
        return self


class OfficeEditEvaluationExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata_only: bool
    content_access_allowed: bool
    engine_execution_allowed: bool
    editor_session_allowed: bool
    candidate_write_allowed: bool
    persistent_state_allowed: bool
    external_network_allowed: bool
    cloud_ai_allowed: bool
    production_use_allowed: bool
    legal_review_complete: bool
    supply_chain_review_complete: bool
    fidelity_review_complete: bool
    security_review_complete: bool
    recovery_review_complete: bool

    @model_validator(mode="after")
    def require_closed_evaluation_boundary(self) -> OfficeEditEvaluationExecutionPolicy:
        if not self.metadata_only:
            raise ValueError("office edit evaluation must remain metadata-only")
        if any(
            (
                self.content_access_allowed,
                self.engine_execution_allowed,
                self.editor_session_allowed,
                self.candidate_write_allowed,
                self.persistent_state_allowed,
                self.external_network_allowed,
                self.cloud_ai_allowed,
                self.production_use_allowed,
                self.legal_review_complete,
                self.supply_chain_review_complete,
                self.fidelity_review_complete,
                self.security_review_complete,
                self.recovery_review_complete,
            )
        ):
            raise ValueError("office edit evaluation opened an unreviewed boundary")
        return self


class GenOfficeEvaluationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    status: str
    adapter_id: str
    use_case: str
    upstream: GenOfficeUpstreamPolicy
    source_scope: GenOfficeSourceScopePolicy
    separation: OfficeEditSeparationPolicy
    execution: OfficeEditEvaluationExecutionPolicy
    required_gates: tuple[str, ...]

    @model_validator(mode="after")
    def require_reviewed_evaluation_policy(self) -> GenOfficeEvaluationPolicy:
        if self.schema_version != GENOFFICE_EVALUATION_POLICY_SCHEMA_VERSION:
            raise ValueError("GenOffice evaluation policy version mismatch")
        if self.status != "evaluation_only":
            raise ValueError("GenOffice policy must remain evaluation-only")
        if self.adapter_id != GENOFFICE_DOCX_EVALUATION_ADAPTER_ID:
            raise ValueError("GenOffice policy adapter ID mismatch")
        if self.use_case != "collabio_native_docx_quick_edit":
            raise ValueError("GenOffice policy use case is not reviewed")
        if self.required_gates != OFFICE_EDIT_REQUIRED_GATES:
            raise ValueError("office edit evaluation gates are incomplete or reordered")
        return self


class OfficeEditAdapterDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_id: str
    contract_version: str = OFFICE_EDIT_ADAPTER_CONTRACT_VERSION
    policy_schema_version: str
    policy_hash: str
    provider_family: str = "genoffice_selected_engine_source"
    capability: str = "docx_quick_edit_evaluation"
    supported_source_object_types: tuple[SourceObjectType, ...] = (SourceObjectType.DOCUMENT,)
    supported_mime_types: tuple[str, ...] = (DOCX_MIME_TYPE,)
    upstream_repository: str
    upstream_commit: str
    upstream_root_license_spdx: str
    selected_source_scopes: tuple[str, ...]
    reference_only_source_scopes: tuple[str, ...]
    prohibited_source_scopes: tuple[str, ...]
    preview_adapter_id: str
    full_collaboration_protocol: str = "wopi_separate_adapter"
    ai_boundary: str = "local_llm_gateway_draft_only"
    required_gates: tuple[str, ...]
    evaluation_only: bool = True
    source_imported: bool = False
    content_input_allowed: bool = False
    engine_execution_enabled: bool = False
    editor_session_enabled: bool = False
    candidate_write_enabled: bool = False
    persistent_state_enabled: bool = False
    external_network_allowed: bool = False
    cloud_ai_allowed: bool = False
    production_use_allowed: bool = False

    @model_validator(mode="after")
    def require_closed_adapter_contract(self) -> OfficeEditAdapterDescriptor:
        if self.adapter_id != GENOFFICE_DOCX_EVALUATION_ADAPTER_ID:
            raise ValueError("office edit adapter is not the selected evaluation architecture")
        if self.contract_version != OFFICE_EDIT_ADAPTER_CONTRACT_VERSION:
            raise ValueError("office edit adapter contract version mismatch")
        if self.provider_family != "genoffice_selected_engine_source":
            raise ValueError("office edit adapter provider family mismatch")
        if self.capability != "docx_quick_edit_evaluation":
            raise ValueError("office edit adapter capability mismatch")
        if self.supported_source_object_types != (SourceObjectType.DOCUMENT,):
            raise ValueError("office edit adapter source object types changed")
        if self.supported_mime_types != (DOCX_MIME_TYPE,):
            raise ValueError("office edit adapter MIME scope changed")
        if self.policy_schema_version != GENOFFICE_EVALUATION_POLICY_SCHEMA_VERSION:
            raise ValueError("office edit adapter policy version mismatch")
        if not SHA256_REF_PATTERN.fullmatch(self.policy_hash):
            raise ValueError("office edit adapter policy hash must be a sha256 reference")
        if self.upstream_repository != GENOFFICE_UPSTREAM_REPOSITORY:
            raise ValueError("office edit adapter repository mismatch")
        if self.upstream_commit != GENOFFICE_UPSTREAM_COMMIT:
            raise ValueError("office edit adapter upstream commit mismatch")
        if self.upstream_root_license_spdx != "Apache-2.0":
            raise ValueError("office edit adapter source license mismatch")
        if self.selected_source_scopes != GENOFFICE_SELECTED_SOURCE_SCOPES:
            raise ValueError("office edit adapter selected source scope mismatch")
        if self.reference_only_source_scopes != GENOFFICE_REFERENCE_ONLY_SOURCE_SCOPES:
            raise ValueError("office edit adapter reference-only source scope mismatch")
        if self.prohibited_source_scopes != GENOFFICE_PROHIBITED_SOURCE_SCOPES:
            raise ValueError("office edit adapter prohibited source scope mismatch")
        if self.preview_adapter_id != "canonical-pdf-libreoffice-pdfjs.v1":
            raise ValueError("office edit adapter must keep preview separate")
        if self.full_collaboration_protocol != "wopi_separate_adapter":
            raise ValueError("office edit adapter must keep WOPI collaboration separate")
        if self.ai_boundary != "local_llm_gateway_draft_only":
            raise ValueError("office edit adapter must keep AI behind the Local LLM Gateway")
        if self.required_gates != OFFICE_EDIT_REQUIRED_GATES:
            raise ValueError("office edit adapter gate contract is incomplete")
        if not self.evaluation_only or any(
            (
                self.source_imported,
                self.content_input_allowed,
                self.engine_execution_enabled,
                self.editor_session_enabled,
                self.candidate_write_enabled,
                self.persistent_state_enabled,
                self.external_network_allowed,
                self.cloud_ai_allowed,
                self.production_use_allowed,
            )
        ):
            raise ValueError("office edit adapter evaluation opened a content or execution boundary")
        return self


class OfficeEditAdapterEvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    source_mime_type: str
    source_manifest_hash: str
    source_content_hash: str
    source_acl_version: int = Field(ge=1)
    policy_hash: str

    @field_validator("source_manifest_hash", "source_content_hash", "policy_hash")
    @classmethod
    def require_sha256_reference(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("office edit adapter input hashes must be sha256 references")
        return value


class OfficeEditAdapterEvaluationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = OFFICE_EDIT_EVALUATION_SCHEMA_VERSION
    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    source_mime_type: str
    source_manifest_hash: str
    source_content_hash: str
    source_acl_version: int = Field(ge=1)
    adapter_id: str
    adapter_contract_version: str
    adapter_descriptor_hash: str
    policy_hash: str
    upstream_repository: str
    upstream_commit: str
    selected_source_scopes: tuple[str, ...]
    route: OfficeEditEvaluationRoute
    eligible_for_isolated_spike: bool
    blocking_reasons: tuple[str, ...]
    required_gates: tuple[str, ...]
    preview_adapter_id: str
    full_collaboration_protocol: str
    ai_boundary: str
    access_checked: bool = True
    policy_checked: bool = True
    source_imported: bool = False
    content_accessed: bool = False
    source_bytes_included: bool = False
    engine_invoked: bool = False
    editor_session_created: bool = False
    candidate_version_written: bool = False
    persistent_state_written: bool = False
    external_network_allowed: bool = False
    cloud_ai_invoked: bool = False
    wopi_session_created: bool = False
    production_editing_allowed: bool = False
    plan_hash: str

    @field_validator(
        "source_manifest_hash",
        "source_content_hash",
        "adapter_descriptor_hash",
        "policy_hash",
        "plan_hash",
    )
    @classmethod
    def require_plan_sha256_reference(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("office edit evaluation plan hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_metadata_only_plan(self) -> OfficeEditAdapterEvaluationPlan:
        if self.schema_version != OFFICE_EDIT_EVALUATION_SCHEMA_VERSION:
            raise ValueError("office edit evaluation plan version mismatch")
        if self.adapter_id != GENOFFICE_DOCX_EVALUATION_ADAPTER_ID:
            raise ValueError("office edit evaluation plan adapter mismatch")
        if self.adapter_contract_version != OFFICE_EDIT_ADAPTER_CONTRACT_VERSION:
            raise ValueError("office edit evaluation plan contract mismatch")
        if self.upstream_repository != GENOFFICE_UPSTREAM_REPOSITORY:
            raise ValueError("office edit evaluation plan repository mismatch")
        if self.upstream_commit != GENOFFICE_UPSTREAM_COMMIT:
            raise ValueError("office edit evaluation plan commit mismatch")
        if self.selected_source_scopes != GENOFFICE_SELECTED_SOURCE_SCOPES:
            raise ValueError("office edit evaluation plan source scope mismatch")
        expected_eligibility = self.route == OfficeEditEvaluationRoute.DOCX_QUICK_EDIT_ISOLATED_SPIKE
        if self.eligible_for_isolated_spike != expected_eligibility:
            raise ValueError("office edit route and isolated-spike eligibility are inconsistent")
        if self.eligible_for_isolated_spike and self.blocking_reasons:
            raise ValueError("eligible office edit evaluation cannot contain blocking reasons")
        if not self.eligible_for_isolated_spike and not self.blocking_reasons:
            raise ValueError("ineligible office edit evaluation requires blocking reasons")
        if self.required_gates != OFFICE_EDIT_REQUIRED_GATES:
            raise ValueError("office edit evaluation plan gates are incomplete")
        if self.preview_adapter_id != "canonical-pdf-libreoffice-pdfjs.v1":
            raise ValueError("office edit evaluation plan preview boundary mismatch")
        if self.full_collaboration_protocol != "wopi_separate_adapter":
            raise ValueError("office edit evaluation plan WOPI boundary mismatch")
        if self.ai_boundary != "local_llm_gateway_draft_only":
            raise ValueError("office edit evaluation plan AI boundary mismatch")
        if not self.access_checked or not self.policy_checked:
            raise ValueError("office edit evaluation requires access and policy checks")
        if any(
            (
                self.source_imported,
                self.content_accessed,
                self.source_bytes_included,
                self.engine_invoked,
                self.editor_session_created,
                self.candidate_version_written,
                self.persistent_state_written,
                self.external_network_allowed,
                self.cloud_ai_invoked,
                self.wopi_session_created,
                self.production_editing_allowed,
            )
        ):
            raise ValueError("office edit evaluation plan opened a content or execution boundary")
        return self


class OfficeEditAdapterEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_id: str = GENOFFICE_DOCX_EVALUATION_ADAPTER_ID
    expected_policy_hash: str
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("adapter_id", "reason")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("office edit adapter request value must not be empty")
        return stripped

    @field_validator("expected_policy_hash")
    @classmethod
    def require_policy_hash(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("office edit adapter expected policy hash must be a sha256 reference")
        return value


class OfficeEditAdapterEvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = OFFICE_EDIT_EVALUATION_SCHEMA_VERSION
    result_contract: str = "metadata_only_office_edit_adapter_evaluation"
    plan: OfficeEditAdapterEvaluationPlan
    source_detail_audit_event_id: str
    audit_event_id: str
    reason_hash: str
    content_included: bool = False
    source_import_performed: bool = False
    execution_performed: bool = False
    editor_session_created: bool = False
    candidate_version_written: bool = False
    evidence_persisted_outside_audit: bool = False

    @model_validator(mode="after")
    def require_closed_response(self) -> OfficeEditAdapterEvaluationResponse:
        if self.schema_version != OFFICE_EDIT_EVALUATION_SCHEMA_VERSION:
            raise ValueError("office edit evaluation response version mismatch")
        if self.result_contract != "metadata_only_office_edit_adapter_evaluation":
            raise ValueError("office edit evaluation response contract mismatch")
        if any(
            (
                self.content_included,
                self.source_import_performed,
                self.execution_performed,
                self.editor_session_created,
                self.candidate_version_written,
                self.evidence_persisted_outside_audit,
            )
        ):
            raise ValueError("office edit evaluation response opened a content or execution boundary")
        return self


class OfficeEditAdapter(Protocol):
    @property
    def descriptor(self) -> OfficeEditAdapterDescriptor: ...

    def evaluate(self, input_data: OfficeEditAdapterEvaluationInput) -> OfficeEditAdapterEvaluationPlan: ...


class GenOfficeDocxQuickEditEvaluationAdapter:
    def __init__(self, *, policy: GenOfficeEvaluationPolicy) -> None:
        policy_hash = build_genoffice_evaluation_policy_hash(policy)
        self._descriptor = OfficeEditAdapterDescriptor(
            adapter_id=policy.adapter_id,
            policy_schema_version=policy.schema_version,
            policy_hash=policy_hash,
            upstream_repository=policy.upstream.repository_url,
            upstream_commit=policy.upstream.commit,
            upstream_root_license_spdx=policy.upstream.root_license_spdx,
            selected_source_scopes=policy.source_scope.selected_import_candidates,
            reference_only_source_scopes=policy.source_scope.reference_only_candidates,
            prohibited_source_scopes=policy.source_scope.prohibited_scopes,
            preview_adapter_id=policy.separation.preview_adapter_id,
            required_gates=policy.required_gates,
        )

    @property
    def descriptor(self) -> OfficeEditAdapterDescriptor:
        return self._descriptor

    def evaluate(self, input_data: OfficeEditAdapterEvaluationInput) -> OfficeEditAdapterEvaluationPlan:
        if input_data.policy_hash != self.descriptor.policy_hash:
            raise OfficeEditAdapterEvaluationBlocked("office edit adapter policy hash mismatch")
        route, blocking_reasons = self._route(input_data)
        descriptor_hash = build_office_edit_adapter_descriptor_hash(self.descriptor)
        draft = OfficeEditAdapterEvaluationPlan(
            tenant_id=input_data.tenant_id,
            source_object_id=input_data.source_object_id,
            source_version_id=input_data.source_version_id,
            source_object_type=input_data.source_object_type,
            source_mime_type=input_data.source_mime_type,
            source_manifest_hash=input_data.source_manifest_hash,
            source_content_hash=input_data.source_content_hash,
            source_acl_version=input_data.source_acl_version,
            adapter_id=self.descriptor.adapter_id,
            adapter_contract_version=self.descriptor.contract_version,
            adapter_descriptor_hash=descriptor_hash,
            policy_hash=self.descriptor.policy_hash,
            upstream_repository=self.descriptor.upstream_repository,
            upstream_commit=self.descriptor.upstream_commit,
            selected_source_scopes=self.descriptor.selected_source_scopes,
            route=route,
            eligible_for_isolated_spike=route == OfficeEditEvaluationRoute.DOCX_QUICK_EDIT_ISOLATED_SPIKE,
            blocking_reasons=blocking_reasons,
            required_gates=self.descriptor.required_gates,
            preview_adapter_id=self.descriptor.preview_adapter_id,
            full_collaboration_protocol=self.descriptor.full_collaboration_protocol,
            ai_boundary=self.descriptor.ai_boundary,
            plan_hash="sha256:" + ("0" * 64),
        )
        return draft.model_copy(update={"plan_hash": build_office_edit_adapter_plan_hash(draft)})

    def _route(
        self,
        input_data: OfficeEditAdapterEvaluationInput,
    ) -> tuple[OfficeEditEvaluationRoute, tuple[str, ...]]:
        if input_data.source_object_type not in self.descriptor.supported_source_object_types:
            return OfficeEditEvaluationRoute.UNSUPPORTED, ("source_object_type_not_supported",)
        if input_data.source_mime_type.lower() not in self.descriptor.supported_mime_types:
            return OfficeEditEvaluationRoute.UNSUPPORTED, ("source_mime_type_not_supported",)
        return OfficeEditEvaluationRoute.DOCX_QUICK_EDIT_ISOLATED_SPIKE, ()


class OfficeEditAdapterRegistry:
    def __init__(
        self,
        *,
        adapters: tuple[OfficeEditAdapter, ...],
        selected_adapter_id: str,
    ) -> None:
        self._adapters: dict[str, OfficeEditAdapter] = {}
        for adapter in adapters:
            adapter_id = adapter.descriptor.adapter_id
            if adapter_id in self._adapters:
                raise ValueError(f"duplicate office edit adapter: {adapter_id}")
            self._adapters[adapter_id] = adapter
        if selected_adapter_id not in self._adapters:
            raise ValueError("selected office edit adapter is not registered")
        self.selected_adapter_id = selected_adapter_id

    @property
    def policy_hash(self) -> str:
        return self._adapters[self.selected_adapter_id].descriptor.policy_hash

    def selected(self, *, requested_adapter_id: str) -> OfficeEditAdapter:
        if requested_adapter_id != self.selected_adapter_id:
            raise OfficeEditAdapterEvaluationBlocked("requested office edit adapter is not selected")
        return self._adapters[requested_adapter_id]

    def descriptors(self) -> tuple[OfficeEditAdapterDescriptor, ...]:
        return tuple(adapter.descriptor for adapter in self._adapters.values())


def load_genoffice_evaluation_policy(path: Path) -> GenOfficeEvaluationPolicy:
    return GenOfficeEvaluationPolicy.model_validate(json.loads(path.read_text(encoding="utf-8")))


def build_default_office_edit_adapter_registry(
    environ: Mapping[str, str] | None = None,
) -> OfficeEditAdapterRegistry:
    env = os.environ if environ is None else environ
    policy_path_value = env.get(
        "SUITE_GENOFFICE_EVALUATION_POLICY_PATH",
        str(DEFAULT_GENOFFICE_EVALUATION_POLICY_PATH),
    ).strip()
    if not policy_path_value:
        raise ValueError("GenOffice evaluation policy path must not be empty")
    policy = load_genoffice_evaluation_policy(Path(policy_path_value))
    selected_adapter_id = env.get(
        "SUITE_OFFICE_EDIT_ADAPTER_ID",
        GENOFFICE_DOCX_EVALUATION_ADAPTER_ID,
    ).strip()
    return OfficeEditAdapterRegistry(
        adapters=(GenOfficeDocxQuickEditEvaluationAdapter(policy=policy),),
        selected_adapter_id=selected_adapter_id,
    )


def build_office_edit_adapter_evaluation(
    *,
    user_context: UserContext,
    workspace_source_repository: SourceObjectRepository,
    module_registry: ModuleRegistryStore,
    knowledge_base_article_service: KnowledgeBaseArticleService,
    audit_logger: InMemoryAuditLogger,
    adapter_registry: OfficeEditAdapterRegistry,
    source_object_id: str,
    source_version_id: str,
    request: OfficeEditAdapterEvaluationRequest,
) -> OfficeEditAdapterEvaluationResponse:
    detail = build_source_object_metadata_detail_response(
        user_context=user_context,
        workspace_source_repository=workspace_source_repository,
        module_registry=module_registry,
        knowledge_base_article_service=knowledge_base_article_service,
        audit_logger=audit_logger,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
    )
    if detail.content_accessed:
        _audit_evaluation_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=detail.source_object_id,
            source_version_id=detail.source_version_id,
            request=request,
            rejection_reason="metadata_only_repository_required",
            source_detail_audit_event_id=detail.audit_event_id,
        )
        raise OfficeEditAdapterEvaluationBlocked(
            "office edit adapter evaluation requires a metadata-only source repository"
        )
    try:
        adapter = adapter_registry.selected(requested_adapter_id=request.adapter_id)
    except OfficeEditAdapterEvaluationBlocked:
        _audit_evaluation_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=detail.source_object_id,
            source_version_id=detail.source_version_id,
            request=request,
            rejection_reason="adapter_not_selected",
            source_detail_audit_event_id=detail.audit_event_id,
        )
        raise
    if request.expected_policy_hash != adapter.descriptor.policy_hash:
        _audit_evaluation_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=detail.source_object_id,
            source_version_id=detail.source_version_id,
            request=request,
            rejection_reason="policy_hash_mismatch",
            source_detail_audit_event_id=detail.audit_event_id,
        )
        raise OfficeEditAdapterEvaluationBlocked("office edit adapter policy hash mismatch")

    plan = adapter.evaluate(
        OfficeEditAdapterEvaluationInput(
            tenant_id=detail.tenant_id,
            source_object_id=detail.source_object_id,
            source_version_id=detail.source_version_id,
            source_object_type=detail.source_object_type,
            source_mime_type=detail.mime_type,
            source_manifest_hash=detail.manifest_hash,
            source_content_hash=detail.content_hash,
            source_acl_version=detail.acl_version,
            policy_hash=adapter.descriptor.policy_hash,
        )
    )
    reason_hash = stable_hash(request.reason)
    event = audit_logger.record(
        user_context=user_context,
        event_type="source_object.office_edit_adapter_evaluation.recorded",
        source_object_ids=[detail.source_object_id],
        metadata={
            "source_object_id": detail.source_object_id,
            "source_version_id": detail.source_version_id,
            "source_object_type": detail.source_object_type.value,
            "source_mime_type": detail.mime_type,
            "source_manifest_hash": detail.manifest_hash,
            "source_content_hash": detail.content_hash,
            "source_acl_version": detail.acl_version,
            "adapter_id": plan.adapter_id,
            "adapter_descriptor_hash": plan.adapter_descriptor_hash,
            "policy_hash": plan.policy_hash,
            "upstream_commit": plan.upstream_commit,
            "route": plan.route.value,
            "eligible_for_isolated_spike": plan.eligible_for_isolated_spike,
            "blocking_reasons": list(plan.blocking_reasons),
            "plan_hash": plan.plan_hash,
            "source_detail_audit_event_id": detail.audit_event_id,
            "result_contract": "metadata_only_office_edit_adapter_evaluation",
            "access_checked": True,
            "policy_checked": True,
            "source_imported": False,
            "content_accessed": False,
            "content_included": False,
            "engine_invoked": False,
            "editor_session_created": False,
            "candidate_version_written": False,
            "persistent_state_written": False,
            "external_network_allowed": False,
            "cloud_ai_invoked": False,
            "wopi_session_created": False,
            "production_editing_allowed": False,
            "reason_hash": reason_hash,
        },
    )
    return OfficeEditAdapterEvaluationResponse(
        plan=plan,
        source_detail_audit_event_id=detail.audit_event_id,
        audit_event_id=event.event_id,
        reason_hash=reason_hash,
    )


def build_genoffice_evaluation_policy_hash(policy: GenOfficeEvaluationPolicy) -> str:
    return stable_hash(canonical_json(policy.model_dump(mode="json")))


def build_office_edit_adapter_descriptor_hash(descriptor: OfficeEditAdapterDescriptor) -> str:
    return stable_hash(canonical_json(descriptor.model_dump(mode="json")))


def build_office_edit_adapter_plan_hash(plan: OfficeEditAdapterEvaluationPlan) -> str:
    return stable_hash(canonical_json(plan.model_dump(mode="json", exclude={"plan_hash"})))


def _audit_evaluation_rejection(
    *,
    audit_logger: InMemoryAuditLogger,
    user_context: UserContext,
    source_object_id: str,
    source_version_id: str,
    request: OfficeEditAdapterEvaluationRequest,
    rejection_reason: str,
    source_detail_audit_event_id: str,
) -> None:
    audit_logger.record(
        user_context=user_context,
        event_type="source_object.office_edit_adapter_evaluation.rejected",
        source_object_ids=[source_object_id],
        metadata={
            "source_object_id": source_object_id,
            "source_version_id": source_version_id,
            "adapter_id": request.adapter_id,
            "expected_policy_hash": request.expected_policy_hash,
            "rejection_reason": rejection_reason,
            "source_detail_audit_event_id": source_detail_audit_event_id,
            "result_contract": "metadata_only_office_edit_adapter_evaluation_rejection",
            "source_imported": False,
            "content_accessed": False,
            "content_included": False,
            "execution_performed": False,
            "candidate_version_written": False,
            "persistent_state_written": False,
            "reason_hash": stable_hash(request.reason),
        },
    )
