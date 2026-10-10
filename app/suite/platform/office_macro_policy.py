from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from suite.platform.office_parser_worker_plan import OFFICE_PARSER_SUPPORTED_MIME_TYPES, OfficeParserMimeType

OfficeMacroBlockingIndicator = Literal[
    "docx_vba_activex_ole_or_external_template",
    "odf_basic_script_or_event_listener",
    "pdf_javascript_launch_action_or_embedded_file",
    "ambiguous_encrypted_or_unsupported_package",
]
OfficeMacroReviewMarking = Literal[
    "digital_signature_present",
    "external_hyperlink_present",
]
OfficeMacroBlockedMimeType = Literal["application/vnd.ms-word.document.macroenabled.12"]
OfficeMacroPolicyBlocker = Literal[
    "complete_ooxml_odf_pdf_active_content_corpus_not_verified",
    "quarantine_and_operator_review_workflow_not_implemented",
    "policy_receipt_persistence_and_restore_not_implemented",
    "production_parser_image_admission_not_verified",
]

OFFICE_MACRO_BLOCKING_INDICATORS: tuple[OfficeMacroBlockingIndicator, ...] = (
    "docx_vba_activex_ole_or_external_template",
    "odf_basic_script_or_event_listener",
    "pdf_javascript_launch_action_or_embedded_file",
    "ambiguous_encrypted_or_unsupported_package",
)
OFFICE_MACRO_REVIEW_MARKINGS: tuple[OfficeMacroReviewMarking, ...] = (
    "digital_signature_present",
    "external_hyperlink_present",
)
OFFICE_MACRO_BLOCKED_MIME_TYPES: tuple[OfficeMacroBlockedMimeType, ...] = (
    "application/vnd.ms-word.document.macroenabled.12",
)
OFFICE_MACRO_POLICY_BLOCKERS: tuple[OfficeMacroPolicyBlocker, ...] = (
    "complete_ooxml_odf_pdf_active_content_corpus_not_verified",
    "quarantine_and_operator_review_workflow_not_implemented",
    "policy_receipt_persistence_and_restore_not_implemented",
    "production_parser_image_admission_not_verified",
)


class OfficeMacroPolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    schema_version: Literal["office_macro_policy.v1"] = "office_macro_policy.v1"
    policy_state: Literal["enforced_execution_disabled"] = "enforced_execution_disabled"
    supported_mime_types: tuple[OfficeParserMimeType, ...] = OFFICE_PARSER_SUPPORTED_MIME_TYPES
    blocked_mime_types: tuple[OfficeMacroBlockedMimeType, ...] = OFFICE_MACRO_BLOCKED_MIME_TYPES
    blocking_indicators: tuple[OfficeMacroBlockingIndicator, ...] = OFFICE_MACRO_BLOCKING_INDICATORS
    review_markings: tuple[OfficeMacroReviewMarking, ...] = OFFICE_MACRO_REVIEW_MARKINGS
    active_content_detection_enforced_by_parser: bool = True
    active_content_execution_allowed: bool = False
    automatic_active_content_removal_allowed: bool = False
    blocked_input_extraction_allowed: bool = False
    marked_input_extraction_allowed: bool = True
    marked_input_requires_visible_review: bool = True
    content_accepted_by_policy_endpoint: bool = False
    parser_dispatch_allowed: bool = False
    policy_receipt_persisted: bool = False
    normal_logs_may_contain_content_or_indicator_paths: bool = False
    blockers: tuple[OfficeMacroPolicyBlocker, ...] = OFFICE_MACRO_POLICY_BLOCKERS
    audit_event_id: str = ""


def build_office_macro_policy(*, tenant_id: str) -> OfficeMacroPolicyResponse:
    return OfficeMacroPolicyResponse(tenant_id=tenant_id)
