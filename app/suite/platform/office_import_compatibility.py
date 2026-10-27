from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

OfficeImportFormat = Literal["ooxml_docx", "odf_odt", "pdf"]
OfficeImportFeatureState = Literal[
    "text_supported",
    "text_flattened",
    "blocked_active_content",
    "visible_review_marker",
    "unsupported",
]


class OfficeImportCompatibilityEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_id: OfficeImportFormat
    mime_type: str
    feature_id: str
    state: OfficeImportFeatureState
    fidelity_preserved: bool = False
    reason: str


OFFICE_IMPORT_COMPATIBILITY_ENTRIES: tuple[OfficeImportCompatibilityEntry, ...] = (
    OfficeImportCompatibilityEntry(
        format_id="ooxml_docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        feature_id="main_document_paragraph_text",
        state="text_supported",
        reason="word/document.xml paragraphs are extracted in document order",
    ),
    OfficeImportCompatibilityEntry(
        format_id="ooxml_docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        feature_id="headings_lists_and_table_cell_text",
        state="text_flattened",
        reason="paragraph text is retained without OOXML structure or styling",
    ),
    OfficeImportCompatibilityEntry(
        format_id="ooxml_docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        feature_id="headers_footers_notes_comments_drawings_and_revisions",
        state="unsupported",
        reason="only the main document part is extracted by the development parser",
    ),
    OfficeImportCompatibilityEntry(
        format_id="ooxml_docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        feature_id="vba_activex_ole_and_external_templates",
        state="blocked_active_content",
        reason="active or embedded content is rejected before extraction",
    ),
    OfficeImportCompatibilityEntry(
        format_id="ooxml_docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        feature_id="digital_signatures_and_external_hyperlinks",
        state="visible_review_marker",
        reason="nonexecuting indicators require visible review and are never executed",
    ),
    OfficeImportCompatibilityEntry(
        format_id="odf_odt",
        mime_type="application/vnd.oasis.opendocument.text",
        feature_id="paragraph_and_heading_text",
        state="text_supported",
        reason="content.xml paragraph and heading text is extracted in document order",
    ),
    OfficeImportCompatibilityEntry(
        format_id="odf_odt",
        mime_type="application/vnd.oasis.opendocument.text",
        feature_id="lists_tables_styles_fields_and_annotations",
        state="text_flattened",
        reason="nested paragraph text may remain while ODF structure and styling are not preserved",
    ),
    OfficeImportCompatibilityEntry(
        format_id="odf_odt",
        mime_type="application/vnd.oasis.opendocument.text",
        feature_id="basic_scripts_event_listeners_and_script_uris",
        state="blocked_active_content",
        reason="ODF active content is rejected before extraction",
    ),
    OfficeImportCompatibilityEntry(
        format_id="odf_odt",
        mime_type="application/vnd.oasis.opendocument.text",
        feature_id="digital_signatures_and_external_hyperlinks",
        state="visible_review_marker",
        reason="nonexecuting indicators require visible review and are never executed",
    ),
    OfficeImportCompatibilityEntry(
        format_id="pdf",
        mime_type="application/pdf",
        feature_id="basic_literal_text_strings",
        state="text_flattened",
        reason="the development parser handles only bounded literal strings from basic content streams",
    ),
    OfficeImportCompatibilityEntry(
        format_id="pdf",
        mime_type="application/pdf",
        feature_id="scans_complex_fonts_layout_forms_and_accessibility_structure",
        state="unsupported",
        reason="a dedicated admitted PDF engine is required",
    ),
    OfficeImportCompatibilityEntry(
        format_id="pdf",
        mime_type="application/pdf",
        feature_id="javascript_launch_actions_and_embedded_files",
        state="blocked_active_content",
        reason="active PDF actions and embedded files are rejected before extraction",
    ),
    OfficeImportCompatibilityEntry(
        format_id="pdf",
        mime_type="application/pdf",
        feature_id="digital_signatures_and_external_links",
        state="visible_review_marker",
        reason="nonexecuting indicators require visible review and are never executed",
    ),
)


class OfficeImportCompatibilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    schema_version: Literal["office_import_compatibility_matrix.v1"] = "office_import_compatibility_matrix.v1"
    matrix_state: Literal["development_contract_dispatch_closed"] = "development_contract_dispatch_closed"
    parser_profile_id: Literal["rich-document-parser-worker:1"] = "rich-document-parser-worker:1"
    entries: tuple[OfficeImportCompatibilityEntry, ...] = OFFICE_IMPORT_COMPATIBILITY_ENTRIES
    content_accepted_by_matrix_endpoint: bool = False
    import_dispatch_allowed: bool = False
    export_allowed: bool = False
    round_trip_fidelity_claimed: bool = False
    production_admitted: bool = False
    audit_event_id: str = ""


def build_office_import_compatibility_matrix(*, tenant_id: str) -> OfficeImportCompatibilityResponse:
    return OfficeImportCompatibilityResponse(tenant_id=tenant_id)
