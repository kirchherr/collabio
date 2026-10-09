from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import warnings
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash

ZERO_HASH = "sha256:" + "0" * 64
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
DOCX_QUICK_EDIT_FIXTURE_IDS = (
    "formatting-table-fidelity",
    "headers-comments-footnotes-fidelity",
    "unknown-markup-passthrough",
    "external-hyperlink-relationship",
    "external-template-relationship",
    "macro-enabled-vba-project",
    "ole-embedded-object",
    "path-traversal-part",
    "duplicate-part-name",
    "case-colliding-part-name",
    "high-compression-ratio",
    "xml-doctype-entity",
    "xml-depth-limit",
    "malformed-xml",
    "signed-package-unverified",
    "encrypted-entry-flag",
    "unsupported-compression-method",
    "oversized-declared-part",
    "too-many-parts",
)
HARNESS_BLOCKING_REASONS = (
    "two_person_runtime_authorization_absent",
    "attested_executable_proof_harness_image_absent",
    "worker_entrypoint_status_only",
)

FixtureCategory = Literal[
    "fidelity",
    "external_relationship",
    "active_content",
    "embedded_object",
    "package_structure",
    "resource_exhaustion",
    "xml_parser",
    "digital_signature",
]
PreflightDecision = Literal["allow_future_engine_evaluation", "reject_before_engine"]
SignatureState = Literal["absent", "present_unverified"]
DerivedSignatureState = Literal["not_applicable", "invalidated_by_edit"]


class GenOfficeDocxQuickEditPreflightError(ValueError):
    pass


class GenOfficeDocxQuickEditPreflightPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_quick_edit_preflight_policy.v1"] = (
        "genoffice_docx_quick_edit_preflight_policy.v1"
    )
    policy_id: Literal["genoffice-docx-quick-edit-preflight-v1"] = "genoffice-docx-quick-edit-preflight-v1"
    max_archive_bytes: Literal[8_388_608] = 8_388_608
    max_parts: Literal[128] = 128
    max_part_uncompressed_bytes: Literal[16_777_216] = 16_777_216
    max_total_uncompressed_bytes: Literal[67_108_864] = 67_108_864
    max_compression_ratio: Literal[100] = 100
    max_xml_bytes: Literal[8_388_608] = 8_388_608
    max_xml_depth: Literal[64] = 64
    max_relationships: Literal[128] = 128
    allowed_compression_methods: tuple[Literal[0, 8], ...] = (0, 8)
    fidelity_comparison_targets: tuple[
        Literal["microsoft_word", "libreoffice", "genoffice", "collabio_revalidator"], ...
    ] = ("microsoft_word", "libreoffice", "genoffice", "collabio_revalidator")
    safe_export_rules: tuple[str, ...] = (
        "remove_external_relationships",
        "remove_active_content_and_embedded_objects",
        "remove_invalidated_package_signatures",
        "require_source_blind_revalidation",
        "require_independent_cdr_preview",
    )
    high_fidelity_export_rules: tuple[str, ...] = (
        "preserve_safe_unknown_parts_only",
        "never_preserve_active_or_external_content",
        "require_explicit_human_confirmation",
        "require_source_blind_revalidation",
        "require_independent_cdr_preview",
    )
    external_relationships_allowed: Literal[False] = False
    active_content_allowed: Literal[False] = False
    embedded_objects_allowed: Literal[False] = False
    signed_packages_engine_eligible: Literal[False] = False
    authoritative_signature_validation_available: Literal[False] = False
    original_bytes_retention_required_for_signed_packages: Literal[True] = True
    source_blind_revalidation_required: Literal[True] = True
    engine_execution_enabled: Literal[False] = False
    tenant_content_allowed: Literal[False] = False
    network_allowed: Literal[False] = False
    persistent_document_writes_allowed: Literal[False] = False
    fidelity_claims_allowed: Literal[False] = False
    policy_hash: str

    @model_validator(mode="after")
    def require_closed_policy(self) -> GenOfficeDocxQuickEditPreflightPolicy:
        _require_sha256(self.policy_hash, field="quick-edit preflight policy hash")
        if len(set(self.safe_export_rules)) != len(self.safe_export_rules):
            raise ValueError("GenOffice safe-export rules are not unique")
        if len(set(self.high_fidelity_export_rules)) != len(self.high_fidelity_export_rules):
            raise ValueError("GenOffice high-fidelity export rules are not unique")
        return self


class GenOfficeDocxQuickEditCorpusArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: str
    filename: str
    category: FixtureCategory
    expected_decision: PreflightDecision
    expected_findings: tuple[str, ...]
    fidelity_features: tuple[str, ...] = ()
    expected_signature_state: SignatureState = "absent"
    original_retention_required: bool = False
    future_engine_evaluation_eligible: bool
    engine_invocation_authorized: Literal[False] = False
    content_sha256: str
    size_bytes: int

    @model_validator(mode="after")
    def require_consistent_artifact(self) -> GenOfficeDocxQuickEditCorpusArtifact:
        if not self.fixture_id.strip() or PurePosixPath(self.filename).name != self.filename:
            raise ValueError("GenOffice quick-edit fixture identity is invalid")
        if not self.filename.endswith((".docx", ".docm")) or self.size_bytes <= 0:
            raise ValueError("GenOffice quick-edit fixture filename or size is invalid")
        if tuple(sorted(set(self.expected_findings))) != self.expected_findings:
            raise ValueError("GenOffice quick-edit expected findings are not canonical")
        expected_eligible = self.expected_decision == "allow_future_engine_evaluation"
        if self.future_engine_evaluation_eligible != expected_eligible:
            raise ValueError("GenOffice quick-edit future engine eligibility is inconsistent")
        if expected_eligible == bool(self.expected_findings):
            raise ValueError("GenOffice quick-edit expected decision and findings are inconsistent")
        if (self.expected_signature_state == "present_unverified") != self.original_retention_required:
            raise ValueError("GenOffice quick-edit signature retention contract is inconsistent")
        _require_sha256(self.content_sha256, field="quick-edit fixture hash")
        return self


class GenOfficeDocxQuickEditCorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_quick_edit_corpus_manifest.v1"] = (
        "genoffice_docx_quick_edit_corpus_manifest.v1"
    )
    source_date_epoch: Literal[0] = 0
    classification: Literal["synthetic_public_non_personal"] = "synthetic_public_non_personal"
    preflight_policy_hash: str
    artifacts: tuple[GenOfficeDocxQuickEditCorpusArtifact, ...]
    total_size_bytes: int
    tenant_content_included: Literal[False] = False
    personal_data_included: Literal[False] = False
    customer_content_included: Literal[False] = False
    engine_executed: Literal[False] = False
    external_network_used: Literal[False] = False
    manifest_hash: str

    @model_validator(mode="after")
    def require_exact_manifest(self) -> GenOfficeDocxQuickEditCorpusManifest:
        if tuple(item.fixture_id for item in self.artifacts) != DOCX_QUICK_EDIT_FIXTURE_IDS:
            raise ValueError("GenOffice quick-edit corpus fixture inventory is not exact")
        if len({item.filename for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("GenOffice quick-edit corpus filenames are not unique")
        if self.total_size_bytes != sum(item.size_bytes for item in self.artifacts):
            raise ValueError("GenOffice quick-edit corpus size is inconsistent")
        _require_sha256(self.preflight_policy_hash, field="quick-edit manifest policy hash")
        _require_sha256(self.manifest_hash, field="quick-edit corpus manifest hash")
        return self


class GenOfficeDocxQuickEditPreflightReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_quick_edit_preflight_report.v1"] = (
        "genoffice_docx_quick_edit_preflight_report.v1"
    )
    input_sha256: str
    input_size_bytes: int
    preflight_policy_hash: str
    archive_part_count: int
    declared_total_uncompressed_bytes: int
    relationship_count: int
    external_relationship_count: int
    active_content_marker_count: int
    embedded_object_marker_count: int
    signature_part_count: int
    signature_state: SignatureState
    derived_signature_state: DerivedSignatureState
    original_bytes_retention_required: bool
    decision: PreflightDecision
    findings: tuple[str, ...]
    future_engine_evaluation_eligible: bool
    engine_invocation_authorized: Literal[False] = False
    archive_extracted_to_filesystem: Literal[False] = False
    document_content_included_in_report: Literal[False] = False
    tenant_content_processed: Literal[False] = False
    external_network_used: Literal[False] = False
    persistent_document_write_performed: Literal[False] = False
    engine_executed: Literal[False] = False
    report_hash: str

    @model_validator(mode="after")
    def require_consistent_report(self) -> GenOfficeDocxQuickEditPreflightReport:
        for value, field in (
            (self.input_sha256, "quick-edit input hash"),
            (self.preflight_policy_hash, "quick-edit report policy hash"),
            (self.report_hash, "quick-edit preflight report hash"),
        ):
            _require_sha256(value, field=field)
        if (
            self.input_size_bytes <= 0
            or min(
                self.archive_part_count,
                self.declared_total_uncompressed_bytes,
                self.relationship_count,
                self.external_relationship_count,
                self.active_content_marker_count,
                self.embedded_object_marker_count,
                self.signature_part_count,
            )
            < 0
        ):
            raise ValueError("GenOffice quick-edit preflight counters are invalid")
        if tuple(sorted(set(self.findings))) != self.findings:
            raise ValueError("GenOffice quick-edit preflight findings are not canonical")
        expected_eligible = self.decision == "allow_future_engine_evaluation"
        if self.future_engine_evaluation_eligible != expected_eligible or expected_eligible == bool(self.findings):
            raise ValueError("GenOffice quick-edit preflight decision is inconsistent")
        signed = self.signature_state == "present_unverified"
        if signed != self.original_bytes_retention_required:
            raise ValueError("GenOffice quick-edit signed-original retention result is inconsistent")
        expected_derived = "invalidated_by_edit" if signed else "not_applicable"
        if self.derived_signature_state != expected_derived:
            raise ValueError("GenOffice quick-edit derived signature state is inconsistent")
        return self


class GenOfficeDocxQuickEditCorpusEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_quick_edit_corpus_evaluation_report.v1"] = (
        "genoffice_docx_quick_edit_corpus_evaluation_report.v1"
    )
    corpus_manifest_hash: str
    preflight_policy_hash: str
    fixture_reports: tuple[GenOfficeDocxQuickEditPreflightReport, ...]
    allowed_fixture_count: int
    rejected_fixture_count: int
    expected_outcomes_matched: Literal[True] = True
    document_content_included_in_report: Literal[False] = False
    tenant_content_processed: Literal[False] = False
    external_network_used: Literal[False] = False
    engine_executed: Literal[False] = False
    report_hash: str

    @model_validator(mode="after")
    def require_complete_evaluation(self) -> GenOfficeDocxQuickEditCorpusEvaluationReport:
        if len(self.fixture_reports) != len(DOCX_QUICK_EDIT_FIXTURE_IDS):
            raise ValueError("GenOffice quick-edit corpus evaluation is incomplete")
        allowed = sum(report.future_engine_evaluation_eligible for report in self.fixture_reports)
        if self.allowed_fixture_count != allowed or self.rejected_fixture_count != len(self.fixture_reports) - allowed:
            raise ValueError("GenOffice quick-edit corpus decision counts are inconsistent")
        for value, field in (
            (self.corpus_manifest_hash, "quick-edit evaluation manifest hash"),
            (self.preflight_policy_hash, "quick-edit evaluation policy hash"),
            (self.report_hash, "quick-edit corpus evaluation report hash"),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeDocxSourceBlindRevalidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_source_blind_revalidation_report.v1"] = (
        "genoffice_docx_source_blind_revalidation_report.v1"
    )
    candidate_origin: Literal["synthetic_policy_fixture"] = "synthetic_policy_fixture"
    candidate_sha256: str
    candidate_size_bytes: int
    preflight_policy_hash: str
    preflight_report_hash: str
    source_bytes_available: Literal[False] = False
    source_object_accessed: Literal[False] = False
    candidate_only_validation: Literal[True] = True
    independent_preflight_passed: Literal[True] = True
    external_relationships_absent: Literal[True] = True
    active_content_absent: Literal[True] = True
    embedded_objects_absent: Literal[True] = True
    package_signatures_absent: Literal[True] = True
    document_content_included_in_report: Literal[False] = False
    tenant_content_processed: Literal[False] = False
    external_network_used: Literal[False] = False
    persistent_document_write_performed: Literal[False] = False
    engine_executed: Literal[False] = False
    report_hash: str

    @model_validator(mode="after")
    def require_source_blind_result(self) -> GenOfficeDocxSourceBlindRevalidationReport:
        if self.candidate_size_bytes <= 0:
            raise ValueError("GenOffice source-blind candidate size is invalid")
        for value, field in (
            (self.candidate_sha256, "source-blind candidate hash"),
            (self.preflight_policy_hash, "source-blind policy hash"),
            (self.preflight_report_hash, "source-blind preflight report hash"),
            (self.report_hash, "source-blind revalidation report hash"),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeDocxQuickEditHarnessAdmissionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_quick_edit_harness_admission_report.v1"] = (
        "genoffice_docx_quick_edit_harness_admission_report.v1"
    )
    preflight_policy_hash: str
    corpus_evaluation_report_hash: str
    source_blind_revalidation_report_hash: str
    corpus_contract_verified: Literal[True] = True
    source_blind_revalidator_verified: Literal[True] = True
    two_person_runtime_authorization_present: Literal[False] = False
    attested_executable_proof_harness_image_present: Literal[False] = False
    status_only_worker_entrypoint_verified: Literal[True] = True
    tenant_content_mounted: Literal[False] = False
    engine_executed: Literal[False] = False
    harness_execution_allowed: Literal[False] = False
    blocking_reasons: tuple[str, ...] = HARNESS_BLOCKING_REASONS
    report_hash: str

    @model_validator(mode="after")
    def require_hard_closed_admission(self) -> GenOfficeDocxQuickEditHarnessAdmissionReport:
        if self.blocking_reasons != HARNESS_BLOCKING_REASONS:
            raise ValueError("GenOffice quick-edit harness blocking reasons drifted")
        for value, field in (
            (self.preflight_policy_hash, "quick-edit harness policy hash"),
            (self.corpus_evaluation_report_hash, "quick-edit harness corpus report hash"),
            (self.source_blind_revalidation_report_hash, "quick-edit harness revalidation report hash"),
            (self.report_hash, "quick-edit harness admission report hash"),
        ):
            _require_sha256(value, field=field)
        return self


@dataclass(frozen=True)
class _FixtureDefinition:
    fixture_id: str
    filename: str
    category: FixtureCategory
    expected_findings: tuple[str, ...]
    fidelity_features: tuple[str, ...] = ()
    signature_state: SignatureState = "absent"


def _require_sha256(value: str, *, field: str) -> None:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise ValueError(f"GenOffice {field} is invalid")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ValueError(f"GenOffice {field} is invalid") from exc


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _json_bytes(value: BaseModel | Mapping[str, Any]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def _hash_model(model: BaseModel, *, hash_field: str) -> str:
    return stable_hash(canonical_json(model.model_dump(mode="json", exclude={hash_field})))


def _write_new_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise GenOfficeDocxQuickEditPreflightError(
            f"GenOffice quick-edit output cannot be persisted: {path.name}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _zip_entries(entries: Sequence[tuple[str, bytes]]) -> bytes:
    output = BytesIO()
    with (
        warnings.catch_warnings(),
        zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive,
    ):
        warnings.simplefilter("ignore", UserWarning)
        for name, content in entries:
            info = zipfile.ZipInfo(name, ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, content)
    return output.getvalue()


def _zip_parts(parts: Mapping[str, bytes]) -> bytes:
    return _zip_entries(tuple((name, parts[name]) for name in sorted(parts)))


def _relationship_xml(relationships: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{relationships}</Relationships>"
    ).encode()


def _document_xml(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:c="urn:collabio:synthetic">'
        f"<w:body>{body}<w:sectPr/></w:body></w:document>"
    ).encode()


def _base_parts(
    body: str,
    *,
    document_xml: bytes | None = None,
    document_relationships: str = "",
    root_relationships: str = "",
    extra_parts: Mapping[str, bytes] | None = None,
    extra_content_type_overrides: Sequence[tuple[str, str]] = (),
    macro_enabled: bool = False,
) -> dict[str, bytes]:
    document_content_type = (
        "application/vnd.ms-word.document.macroEnabled.main+xml"
        if macro_enabled
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    )
    overrides = [
        ("/word/document.xml", document_content_type),
        (
            "/word/styles.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
        ),
        *extra_content_type_overrides,
    ]
    override_xml = "".join(
        f'<Override PartName="{part_name}" ContentType="{content_type}"/>' for part_name, content_type in overrides
    )
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f"{override_xml}</Types>"
        ).encode(),
        "_rels/.rels": _relationship_xml(
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>' + root_relationships
        ),
        "word/document.xml": document_xml if document_xml is not None else _document_xml(body),
        "word/styles.xml": (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b'<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
            b'<w:name w:val="Normal"/></w:style></w:styles>'
        ),
    }
    if document_relationships:
        parts["word/_rels/document.xml.rels"] = _relationship_xml(document_relationships)
    if extra_parts:
        parts.update(extra_parts)
    return parts


def _patch_first_zip_entry(
    content: bytes, *, flag_bits: int | None = None, compression_method: int | None = None
) -> bytes:
    patched = bytearray(content)
    local = patched.find(b"PK\x03\x04")
    central = patched.find(b"PK\x01\x02")
    if local < 0 or central < 0:
        raise GenOfficeDocxQuickEditPreflightError("GenOffice quick-edit synthetic ZIP has no entry headers")
    if flag_bits is not None:
        struct.pack_into("<H", patched, local + 6, flag_bits)
        struct.pack_into("<H", patched, central + 8, flag_bits)
    if compression_method is not None:
        struct.pack_into("<H", patched, local + 8, compression_method)
        struct.pack_into("<H", patched, central + 10, compression_method)
    return bytes(patched)


def _patch_first_declared_size(content: bytes, declared_size: int) -> bytes:
    patched = bytearray(content)
    central = patched.find(b"PK\x01\x02")
    if central < 0:
        raise GenOfficeDocxQuickEditPreflightError("GenOffice quick-edit synthetic ZIP has no central directory")
    struct.pack_into("<I", patched, central + 24, declared_size)
    return bytes(patched)


def _build_fixture_files() -> tuple[dict[str, bytes], tuple[_FixtureDefinition, ...]]:
    formatting_body = (
        "<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Collabio synthetic bold</w:t></w:r>"
        '<w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve"> and italic</w:t></w:r></w:p>'
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    )
    structural_relationships = (
        '<Relationship Id="rIdHeader" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" '
        'Target="header1.xml"/>'
        '<Relationship Id="rIdComments" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" '
        'Target="comments.xml"/>'
        '<Relationship Id="rIdFootnotes" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" '
        'Target="footnotes.xml"/>'
    )
    structural_parts = {
        "word/header1.xml": (
            b'<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b"<w:p><w:r><w:t>Synthetic header</w:t></w:r></w:p></w:hdr>"
        ),
        "word/comments.xml": (
            b'<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b'<w:comment w:id="0" w:author="Collabio"><w:p><w:r><w:t>Synthetic comment</w:t>'
            b"</w:r></w:p></w:comment></w:comments>"
        ),
        "word/footnotes.xml": (
            b'<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b'<w:footnote w:id="1"><w:p><w:r><w:t>Synthetic footnote</w:t></w:r></w:p>'
            b"</w:footnote></w:footnotes>"
        ),
    }
    structural_overrides = (
        (
            "/word/header1.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
        ),
        (
            "/word/comments.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
        ),
        (
            "/word/footnotes.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
        ),
    )
    external_hyperlink = (
        '<Relationship Id="rIdRemote" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        'Target="https://example.invalid/collabio-synthetic" TargetMode="External"/>'
    )
    external_template = (
        '<Relationship Id="rIdTemplate" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" '
        'Target="file:///synthetic/template.dotm" TargetMode="External"/>'
    )
    ole_relationship = (
        '<Relationship Id="rIdOle" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" '
        'Target="embeddings/oleObject1.bin"/>'
    )
    signature_root_relationship = (
        '<Relationship Id="rIdSignatureOrigin" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/digital-signature/origin" '
        'Target="_xmlsignatures/origin.sigs"/>'
    )
    common_plain = _base_parts("<w:p><w:r><w:t>Synthetic safe text</w:t></w:r></w:p>")
    duplicate_parts = common_plain.copy()
    duplicate_entries = [(name, duplicate_parts[name]) for name in sorted(duplicate_parts)]
    duplicate_entries.append(("word/styles.xml", duplicate_parts["word/styles.xml"]))
    too_many_extra = {
        f"customXml/item{index:03d}.xml": f'<synthetic index="{index}"/>'.encode() for index in range(129)
    }
    files = {
        "formatting-table-fidelity.docx": _zip_parts(_base_parts(formatting_body)),
        "headers-comments-footnotes-fidelity.docx": _zip_parts(
            _base_parts(
                "<w:p><w:r><w:t>Synthetic structure</w:t></w:r></w:p>",
                document_relationships=structural_relationships,
                extra_parts=structural_parts,
                extra_content_type_overrides=structural_overrides,
            )
        ),
        "unknown-markup-passthrough.docx": _zip_parts(
            _base_parts(
                '<w:p><mc:AlternateContent><mc:Choice Requires="c"><w:r><w:t>Known-safe synthetic '
                "extension</w:t></w:r></mc:Choice><mc:Fallback><w:r><w:t>Fallback</w:t></w:r></mc:Fallback>"
                "</mc:AlternateContent></w:p>",
                extra_parts={"customXml/item1.xml": b'<c:metadata xmlns:c="urn:collabio:synthetic" value="1"/>'},
            )
        ),
        "external-hyperlink-relationship.docx": _zip_parts(
            _base_parts(
                '<w:p><w:hyperlink r:id="rIdRemote"><w:r><w:t>Remote</w:t></w:r></w:hyperlink></w:p>',
                document_relationships=external_hyperlink,
            )
        ),
        "external-template-relationship.docx": _zip_parts(
            _base_parts(
                "<w:p><w:r><w:t>External template</w:t></w:r></w:p>",
                document_relationships=external_template,
            )
        ),
        "macro-enabled-vba-project.docm": _zip_parts(
            _base_parts(
                "<w:p><w:r><w:t>Macro marker</w:t></w:r></w:p>",
                extra_parts={"word/vbaProject.bin": b"COLLABIO-SYNTHETIC-NONEXECUTABLE-VBA\x00"},
                extra_content_type_overrides=(("/word/vbaProject.bin", "application/vnd.ms-office.vbaProject"),),
                macro_enabled=True,
            )
        ),
        "ole-embedded-object.docx": _zip_parts(
            _base_parts(
                "<w:p><w:r><w:t>OLE marker</w:t></w:r></w:p>",
                document_relationships=ole_relationship,
                extra_parts={"word/embeddings/oleObject1.bin": b"COLLABIO-SYNTHETIC-NONEXECUTABLE-OLE\x00"},
                extra_content_type_overrides=(
                    ("/word/embeddings/oleObject1.bin", "application/vnd.ms-office.oleObject"),
                ),
            )
        ),
        "path-traversal-part.docx": _zip_parts({**common_plain, "../escape.xml": b"<synthetic/>"}),
        "duplicate-part-name.docx": _zip_entries(duplicate_entries),
        "case-colliding-part-name.docx": _zip_parts(
            {**common_plain, "word/Styles.xml": b'<synthetic xmlns="urn:collabio:synthetic"/>'}
        ),
        "high-compression-ratio.docx": _zip_parts(
            {**common_plain, "word/media/synthetic-padding.bin": b"0" * (512 * 1024)}
        ),
        "xml-doctype-entity.docx": _zip_parts(
            _base_parts(
                "",
                document_xml=(
                    b'<?xml version="1.0"?><!DOCTYPE w:document [<!ENTITY synthetic "blocked">]>'
                    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    b"<w:body><w:p><w:r><w:t>&synthetic;</w:t></w:r></w:p></w:body></w:document>"
                ),
            )
        ),
        "xml-depth-limit.docx": _zip_parts(
            _base_parts("<w:p>" + "<w:smartTag>" * 80 + "<w:r><w:t>deep</w:t></w:r>" + "</w:smartTag>" * 80 + "</w:p>")
        ),
        "malformed-xml.docx": _zip_parts(
            _base_parts(
                "",
                document_xml=(
                    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    b"<w:body><w:p></w:body></w:document>"
                ),
            )
        ),
        "signed-package-unverified.docx": _zip_parts(
            _base_parts(
                "<w:p><w:r><w:t>Signed marker</w:t></w:r></w:p>",
                root_relationships=signature_root_relationship,
                extra_parts={
                    "_xmlsignatures/origin.sigs": _relationship_xml(
                        '<Relationship Id="rIdSignature" '
                        'Type="http://schemas.openxmlformats.org/package/2006/relationships/'
                        'digital-signature/signature" '
                        'Target="sig1.xml"/>'
                    ),
                    "_xmlsignatures/sig1.xml": (
                        b'<Signature xmlns="http://www.w3.org/2000/09/xmldsig#">'
                        b"<SignatureValue>U1lOVEhFVElDLVVOVkVSSUZJRUQ=</SignatureValue></Signature>"
                    ),
                },
            )
        ),
        "encrypted-entry-flag.docx": _patch_first_zip_entry(_zip_parts(common_plain), flag_bits=1),
        "unsupported-compression-method.docx": _patch_first_zip_entry(_zip_parts(common_plain), compression_method=99),
        "oversized-declared-part.docx": _patch_first_declared_size(_zip_parts(common_plain), 80 * 1024 * 1024),
        "too-many-parts.docx": _zip_parts({**common_plain, **too_many_extra}),
    }
    definitions = (
        _FixtureDefinition(
            "formatting-table-fidelity",
            "formatting-table-fidelity.docx",
            "fidelity",
            (),
            ("bold", "italic", "table", "section_properties"),
        ),
        _FixtureDefinition(
            "headers-comments-footnotes-fidelity",
            "headers-comments-footnotes-fidelity.docx",
            "fidelity",
            (),
            ("header", "comments", "footnotes", "internal_relationships"),
        ),
        _FixtureDefinition(
            "unknown-markup-passthrough",
            "unknown-markup-passthrough.docx",
            "fidelity",
            (),
            ("markup_compatibility", "fallback", "safe_unknown_part"),
        ),
        _FixtureDefinition(
            "external-hyperlink-relationship",
            "external-hyperlink-relationship.docx",
            "external_relationship",
            ("external_relationship",),
        ),
        _FixtureDefinition(
            "external-template-relationship",
            "external-template-relationship.docx",
            "external_relationship",
            ("attached_template_relationship", "external_relationship"),
        ),
        _FixtureDefinition(
            "macro-enabled-vba-project",
            "macro-enabled-vba-project.docm",
            "active_content",
            ("active_content",),
        ),
        _FixtureDefinition(
            "ole-embedded-object",
            "ole-embedded-object.docx",
            "embedded_object",
            ("embedded_object",),
        ),
        _FixtureDefinition(
            "path-traversal-part",
            "path-traversal-part.docx",
            "package_structure",
            ("unsafe_part_name",),
        ),
        _FixtureDefinition(
            "duplicate-part-name",
            "duplicate-part-name.docx",
            "package_structure",
            ("duplicate_part_name",),
        ),
        _FixtureDefinition(
            "case-colliding-part-name",
            "case-colliding-part-name.docx",
            "package_structure",
            ("case_colliding_part_name",),
        ),
        _FixtureDefinition(
            "high-compression-ratio",
            "high-compression-ratio.docx",
            "resource_exhaustion",
            ("compression_ratio_limit",),
        ),
        _FixtureDefinition(
            "xml-doctype-entity",
            "xml-doctype-entity.docx",
            "xml_parser",
            ("xml_dtd_or_entity",),
        ),
        _FixtureDefinition("xml-depth-limit", "xml-depth-limit.docx", "xml_parser", ("xml_depth_limit",)),
        _FixtureDefinition("malformed-xml", "malformed-xml.docx", "xml_parser", ("malformed_xml",)),
        _FixtureDefinition(
            "signed-package-unverified",
            "signed-package-unverified.docx",
            "digital_signature",
            ("signature_validation_required",),
            signature_state="present_unverified",
        ),
        _FixtureDefinition(
            "encrypted-entry-flag",
            "encrypted-entry-flag.docx",
            "package_structure",
            ("encrypted_zip_entry",),
        ),
        _FixtureDefinition(
            "unsupported-compression-method",
            "unsupported-compression-method.docx",
            "package_structure",
            ("unsupported_compression_method",),
        ),
        _FixtureDefinition(
            "oversized-declared-part",
            "oversized-declared-part.docx",
            "resource_exhaustion",
            ("part_size_limit", "total_uncompressed_size_limit"),
        ),
        _FixtureDefinition(
            "too-many-parts",
            "too-many-parts.docx",
            "resource_exhaustion",
            ("part_count_limit",),
        ),
    )
    return files, definitions


def build_genoffice_docx_quick_edit_preflight_policy() -> GenOfficeDocxQuickEditPreflightPolicy:
    draft = GenOfficeDocxQuickEditPreflightPolicy(policy_hash=ZERO_HASH)
    return draft.model_copy(update={"policy_hash": _hash_model(draft, hash_field="policy_hash")})


def build_genoffice_docx_quick_edit_corpus_manifest_hash(
    manifest: GenOfficeDocxQuickEditCorpusManifest,
) -> str:
    return _hash_model(manifest, hash_field="manifest_hash")


def build_genoffice_docx_quick_edit_corpus(
    *,
    policy: GenOfficeDocxQuickEditPreflightPolicy | None = None,
) -> tuple[dict[str, bytes], GenOfficeDocxQuickEditCorpusManifest]:
    selected_policy = policy or build_genoffice_docx_quick_edit_preflight_policy()
    if selected_policy != build_genoffice_docx_quick_edit_preflight_policy():
        raise GenOfficeDocxQuickEditPreflightError("GenOffice quick-edit preflight policy is not canonical")
    files, definitions = _build_fixture_files()
    artifacts = tuple(
        GenOfficeDocxQuickEditCorpusArtifact(
            fixture_id=definition.fixture_id,
            filename=definition.filename,
            category=definition.category,
            expected_decision=(
                "reject_before_engine" if definition.expected_findings else "allow_future_engine_evaluation"
            ),
            expected_findings=definition.expected_findings,
            fidelity_features=definition.fidelity_features,
            expected_signature_state=definition.signature_state,
            original_retention_required=definition.signature_state == "present_unverified",
            future_engine_evaluation_eligible=not definition.expected_findings,
            content_sha256=_sha256_bytes(files[definition.filename]),
            size_bytes=len(files[definition.filename]),
        )
        for definition in definitions
    )
    draft = GenOfficeDocxQuickEditCorpusManifest(
        preflight_policy_hash=selected_policy.policy_hash,
        artifacts=artifacts,
        total_size_bytes=sum(len(content) for content in files.values()),
        manifest_hash=ZERO_HASH,
    )
    return files, draft.model_copy(
        update={"manifest_hash": build_genoffice_docx_quick_edit_corpus_manifest_hash(draft)}
    )


def _safe_part_name(name: str) -> bool:
    if not name or "\\" in name or "\x00" in name or name.startswith("/") or name.endswith("/"):
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False
    return not (path.parts and ":" in path.parts[0])


def _read_xml_part(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    policy: GenOfficeDocxQuickEditPreflightPolicy,
) -> tuple[ElementTree.Element | None, str | None]:
    try:
        with archive.open(info, "r") as handle:
            content = handle.read(policy.max_xml_bytes + 1)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, OSError, NotImplementedError):
        return None, "zip_entry_read_error"
    if len(content) > policy.max_xml_bytes:
        return None, "xml_size_limit"
    lowered = content.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        return None, "xml_dtd_or_entity"
    parser: ElementTree.XMLPullParser[ElementTree.Element] = ElementTree.XMLPullParser(events=("start", "end"))
    depth = 0
    try:
        for offset in range(0, len(content), 4096):
            parser.feed(content[offset : offset + 4096])
            events = cast(Iterator[tuple[str, ElementTree.Element]], parser.read_events())
            for event, _ in events:
                depth += 1 if event == "start" else -1
                if depth > policy.max_xml_depth:
                    return None, "xml_depth_limit"
        parser.close()
        return ElementTree.fromstring(content), None
    except ElementTree.ParseError:
        return None, "malformed_xml"


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def build_genoffice_docx_quick_edit_preflight_report_hash(
    report: GenOfficeDocxQuickEditPreflightReport,
) -> str:
    return _hash_model(report, hash_field="report_hash")


def inspect_genoffice_docx_quick_edit_candidate(
    content: bytes,
    *,
    policy: GenOfficeDocxQuickEditPreflightPolicy | None = None,
) -> GenOfficeDocxQuickEditPreflightReport:
    selected_policy = policy or build_genoffice_docx_quick_edit_preflight_policy()
    if selected_policy != build_genoffice_docx_quick_edit_preflight_policy():
        raise GenOfficeDocxQuickEditPreflightError("GenOffice quick-edit preflight policy is not canonical")
    findings: set[str] = set()
    archive_part_count = 0
    declared_total = 0
    relationship_count = 0
    external_relationship_count = 0
    active_content_markers: set[str] = set()
    embedded_object_markers: set[str] = set()
    signature_parts: set[str] = set()
    if not content:
        raise GenOfficeDocxQuickEditPreflightError("GenOffice quick-edit input is empty")
    if len(content) > selected_policy.max_archive_bytes:
        findings.add("archive_size_limit")
    try:
        with zipfile.ZipFile(BytesIO(content), "r") as archive:
            infos = archive.infolist()
            archive_part_count = len(infos)
            declared_total = sum(info.file_size for info in infos)
            if archive_part_count > selected_policy.max_parts:
                findings.add("part_count_limit")
            if declared_total > selected_policy.max_total_uncompressed_bytes:
                findings.add("total_uncompressed_size_limit")
            names_seen: set[str] = set()
            case_names_seen: dict[str, str] = {}
            safe_infos: dict[str, zipfile.ZipInfo] = {}
            for info in infos:
                name = info.filename
                if not _safe_part_name(name):
                    findings.add("unsafe_part_name")
                    continue
                if name in names_seen:
                    findings.add("duplicate_part_name")
                    continue
                names_seen.add(name)
                case_name = name.casefold()
                previous_case_name = case_names_seen.get(case_name)
                if previous_case_name is not None and previous_case_name != name:
                    findings.add("case_colliding_part_name")
                    continue
                case_names_seen[case_name] = name
                if info.flag_bits & 1:
                    findings.add("encrypted_zip_entry")
                    continue
                if info.compress_type not in selected_policy.allowed_compression_methods:
                    findings.add("unsupported_compression_method")
                    continue
                if info.file_size > selected_policy.max_part_uncompressed_bytes:
                    findings.add("part_size_limit")
                    continue
                ratio = info.file_size / max(info.compress_size, 1)
                if ratio > selected_policy.max_compression_ratio:
                    findings.add("compression_ratio_limit")
                    continue
                safe_infos[name] = info
            for required in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
                if required not in names_seen:
                    findings.add("required_part_missing")
            xml_roots: dict[str, ElementTree.Element] = {}
            for name, info in safe_infos.items():
                if not (name.endswith((".xml", ".rels")) or name == "[Content_Types].xml"):
                    continue
                root, finding = _read_xml_part(archive, info, policy=selected_policy)
                if finding is not None:
                    findings.add(finding)
                elif root is not None:
                    xml_roots[name] = root
            for name, root in xml_roots.items():
                if name.endswith(".rels"):
                    for relationship in root.iter():
                        if _local_name(relationship.tag) != "Relationship":
                            continue
                        relationship_count += 1
                        relationship_type = relationship.attrib.get("Type", "").casefold()
                        if relationship.attrib.get("TargetMode", "").casefold() == "external":
                            external_relationship_count += 1
                            findings.add("external_relationship")
                        if relationship_type.endswith("/attachedtemplate"):
                            findings.add("attached_template_relationship")
                        if relationship_type.endswith(("/vbaproject", "/activex")):
                            active_content_markers.add(relationship_type)
                        if relationship_type.endswith(("/oleobject", "/package")):
                            embedded_object_markers.add(relationship_type)
                        if "digital-signature" in relationship_type:
                            signature_parts.add(name)
                if name == "[Content_Types].xml":
                    for node in root.iter():
                        content_type = node.attrib.get("ContentType", "").casefold()
                        if any(marker in content_type for marker in ("macroenabled", "vbaproject", "activex")):
                            active_content_markers.add(content_type)
                        if any(marker in content_type for marker in ("oleobject", "embedded")):
                            embedded_object_markers.add(content_type)
            if relationship_count > selected_policy.max_relationships:
                findings.add("relationship_count_limit")
            for name in names_seen:
                lowered = name.casefold()
                if "vbaproject.bin" in lowered or "/activex/" in lowered:
                    active_content_markers.add(lowered)
                if "/embeddings/" in lowered:
                    embedded_object_markers.add(lowered)
                if lowered.startswith("_xmlsignatures/") or lowered.endswith("origin.sigs"):
                    signature_parts.add(lowered)
            if active_content_markers:
                findings.add("active_content")
            if embedded_object_markers:
                findings.add("embedded_object")
            if signature_parts:
                findings.add("signature_validation_required")
    except (zipfile.BadZipFile, zipfile.LargeZipFile):
        findings.add("invalid_zip")
    canonical_findings = tuple(sorted(findings))
    signature_state: SignatureState = "present_unverified" if signature_parts else "absent"
    decision: PreflightDecision = "reject_before_engine" if canonical_findings else "allow_future_engine_evaluation"
    draft = GenOfficeDocxQuickEditPreflightReport(
        input_sha256=_sha256_bytes(content),
        input_size_bytes=len(content),
        preflight_policy_hash=selected_policy.policy_hash,
        archive_part_count=archive_part_count,
        declared_total_uncompressed_bytes=declared_total,
        relationship_count=relationship_count,
        external_relationship_count=external_relationship_count,
        active_content_marker_count=len(active_content_markers),
        embedded_object_marker_count=len(embedded_object_markers),
        signature_part_count=len(signature_parts),
        signature_state=signature_state,
        derived_signature_state="invalidated_by_edit" if signature_parts else "not_applicable",
        original_bytes_retention_required=bool(signature_parts),
        decision=decision,
        findings=canonical_findings,
        future_engine_evaluation_eligible=not canonical_findings,
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_docx_quick_edit_preflight_report_hash(draft)})


def build_genoffice_docx_quick_edit_corpus_evaluation_report_hash(
    report: GenOfficeDocxQuickEditCorpusEvaluationReport,
) -> str:
    return _hash_model(report, hash_field="report_hash")


def evaluate_genoffice_docx_quick_edit_corpus(
    *,
    manifest: GenOfficeDocxQuickEditCorpusManifest,
    corpus_directory: Path,
    policy: GenOfficeDocxQuickEditPreflightPolicy,
) -> GenOfficeDocxQuickEditCorpusEvaluationReport:
    expected_files, expected_manifest = build_genoffice_docx_quick_edit_corpus(policy=policy)
    if (
        manifest != expected_manifest
        or build_genoffice_docx_quick_edit_corpus_manifest_hash(manifest) != manifest.manifest_hash
    ):
        raise GenOfficeDocxQuickEditPreflightError("GenOffice quick-edit corpus manifest is not canonical")
    actual_names = tuple(sorted(path.name for path in corpus_directory.iterdir() if path.is_file()))
    expected_names = tuple(sorted((*expected_files, "genoffice-docx-quick-edit-corpus-manifest.json")))
    if actual_names != expected_names:
        raise GenOfficeDocxQuickEditPreflightError("GenOffice quick-edit corpus directory inventory drifted")
    reports: list[GenOfficeDocxQuickEditPreflightReport] = []
    for artifact in manifest.artifacts:
        content = (corpus_directory / artifact.filename).read_bytes()
        if len(content) != artifact.size_bytes or _sha256_bytes(content) != artifact.content_sha256:
            raise GenOfficeDocxQuickEditPreflightError(
                f"GenOffice quick-edit fixture bytes drifted: {artifact.fixture_id}"
            )
        report = inspect_genoffice_docx_quick_edit_candidate(content, policy=policy)
        if (
            report.decision != artifact.expected_decision
            or report.findings != artifact.expected_findings
            or report.signature_state != artifact.expected_signature_state
            or report.original_bytes_retention_required != artifact.original_retention_required
        ):
            raise GenOfficeDocxQuickEditPreflightError(
                f"GenOffice quick-edit fixture expectation drifted: {artifact.fixture_id}"
            )
        reports.append(report)
    allowed = sum(report.future_engine_evaluation_eligible for report in reports)
    draft = GenOfficeDocxQuickEditCorpusEvaluationReport(
        corpus_manifest_hash=manifest.manifest_hash,
        preflight_policy_hash=policy.policy_hash,
        fixture_reports=tuple(reports),
        allowed_fixture_count=allowed,
        rejected_fixture_count=len(reports) - allowed,
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"report_hash": build_genoffice_docx_quick_edit_corpus_evaluation_report_hash(draft)}
    )


def build_genoffice_docx_source_blind_revalidation_report_hash(
    report: GenOfficeDocxSourceBlindRevalidationReport,
) -> str:
    return _hash_model(report, hash_field="report_hash")


def revalidate_genoffice_docx_candidate_source_blind(
    candidate: bytes,
    *,
    expected_candidate_sha256: str,
    policy: GenOfficeDocxQuickEditPreflightPolicy,
) -> GenOfficeDocxSourceBlindRevalidationReport:
    if _sha256_bytes(candidate) != expected_candidate_sha256:
        raise GenOfficeDocxQuickEditPreflightError("GenOffice source-blind candidate hash drifted")
    preflight = inspect_genoffice_docx_quick_edit_candidate(candidate, policy=policy)
    if not preflight.future_engine_evaluation_eligible:
        raise GenOfficeDocxQuickEditPreflightError("GenOffice source-blind candidate failed independent preflight")
    draft = GenOfficeDocxSourceBlindRevalidationReport(
        candidate_sha256=expected_candidate_sha256,
        candidate_size_bytes=len(candidate),
        preflight_policy_hash=policy.policy_hash,
        preflight_report_hash=preflight.report_hash,
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_docx_source_blind_revalidation_report_hash(draft)})


def build_genoffice_docx_quick_edit_harness_admission_report_hash(
    report: GenOfficeDocxQuickEditHarnessAdmissionReport,
) -> str:
    return _hash_model(report, hash_field="report_hash")


def build_genoffice_docx_quick_edit_harness_admission_report(
    *,
    policy: GenOfficeDocxQuickEditPreflightPolicy,
    corpus_evaluation: GenOfficeDocxQuickEditCorpusEvaluationReport,
    source_blind_revalidation: GenOfficeDocxSourceBlindRevalidationReport,
) -> GenOfficeDocxQuickEditHarnessAdmissionReport:
    if corpus_evaluation.preflight_policy_hash != policy.policy_hash:
        raise GenOfficeDocxQuickEditPreflightError("GenOffice quick-edit corpus policy binding drifted")
    if source_blind_revalidation.preflight_policy_hash != policy.policy_hash:
        raise GenOfficeDocxQuickEditPreflightError("GenOffice source-blind policy binding drifted")
    draft = GenOfficeDocxQuickEditHarnessAdmissionReport(
        preflight_policy_hash=policy.policy_hash,
        corpus_evaluation_report_hash=corpus_evaluation.report_hash,
        source_blind_revalidation_report_hash=source_blind_revalidation.report_hash,
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"report_hash": build_genoffice_docx_quick_edit_harness_admission_report_hash(draft)}
    )


def materialize_genoffice_docx_quick_edit_preflight_bundle(
    output_directory: Path,
) -> GenOfficeDocxQuickEditHarnessAdmissionReport:
    output_directory.mkdir(parents=True, exist_ok=True)
    if any(output_directory.iterdir()):
        raise GenOfficeDocxQuickEditPreflightError("GenOffice quick-edit bundle output directory is not empty")
    policy = build_genoffice_docx_quick_edit_preflight_policy()
    files, manifest = build_genoffice_docx_quick_edit_corpus(policy=policy)
    corpus_directory = output_directory / "corpus"
    corpus_directory.mkdir(mode=0o700)
    for name, content in files.items():
        _write_new_private(corpus_directory / name, content)
    _write_new_private(
        corpus_directory / "genoffice-docx-quick-edit-corpus-manifest.json",
        _json_bytes(manifest),
    )
    evaluation = evaluate_genoffice_docx_quick_edit_corpus(
        manifest=manifest,
        corpus_directory=corpus_directory,
        policy=policy,
    )
    clean_fixture = files["formatting-table-fidelity.docx"]
    source_blind = revalidate_genoffice_docx_candidate_source_blind(
        clean_fixture,
        expected_candidate_sha256=_sha256_bytes(clean_fixture),
        policy=policy,
    )
    harness = build_genoffice_docx_quick_edit_harness_admission_report(
        policy=policy,
        corpus_evaluation=evaluation,
        source_blind_revalidation=source_blind,
    )
    for name, model in (
        ("genoffice-docx-quick-edit-preflight-policy.json", policy),
        ("genoffice-docx-quick-edit-corpus-evaluation-report.json", evaluation),
        ("genoffice-docx-source-blind-revalidation-report.json", source_blind),
        ("genoffice-docx-quick-edit-harness-admission-report.json", harness),
    ):
        _write_new_private(output_directory / name, _json_bytes(model))
    return harness


def persist_genoffice_docx_quick_edit_preflight_schemas(output_directory: Path) -> dict[str, str]:
    schemas: tuple[tuple[str, type[BaseModel]], ...] = (
        ("genoffice-docx-quick-edit-preflight-policy.schema.json", GenOfficeDocxQuickEditPreflightPolicy),
        ("genoffice-docx-quick-edit-corpus-manifest.schema.json", GenOfficeDocxQuickEditCorpusManifest),
        ("genoffice-docx-quick-edit-preflight-report.schema.json", GenOfficeDocxQuickEditPreflightReport),
        (
            "genoffice-docx-quick-edit-corpus-evaluation-report.schema.json",
            GenOfficeDocxQuickEditCorpusEvaluationReport,
        ),
        (
            "genoffice-docx-source-blind-revalidation-report.schema.json",
            GenOfficeDocxSourceBlindRevalidationReport,
        ),
        (
            "genoffice-docx-quick-edit-harness-admission-report.schema.json",
            GenOfficeDocxQuickEditHarnessAdmissionReport,
        ),
    )
    hashes: dict[str, str] = {}
    for filename, model in schemas:
        content = _json_bytes(model.model_json_schema())
        _write_new_private(output_directory / filename, content)
        hashes[filename] = _sha256_bytes(content)
    return hashes


def main() -> None:
    mode = os.environ.get("SUITE_GENOFFICE_QUICK_EDIT_PREFLIGHT_MODE", "").strip()
    try:
        if mode == "schema":
            result: BaseModel | Mapping[str, Any] = persist_genoffice_docx_quick_edit_preflight_schemas(
                Path(os.environ["SUITE_GENOFFICE_QUICK_EDIT_SCHEMA_OUTPUT_DIR"])
            )
        elif mode == "bundle":
            result = materialize_genoffice_docx_quick_edit_preflight_bundle(
                Path(os.environ["SUITE_GENOFFICE_QUICK_EDIT_BUNDLE_OUTPUT_DIR"])
            )
        else:
            raise GenOfficeDocxQuickEditPreflightError("GenOffice quick-edit preflight mode is invalid")
        print(json.dumps(result.model_dump(mode="json") if isinstance(result, BaseModel) else result, sort_keys=True))
    except (GenOfficeDocxQuickEditPreflightError, KeyError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "schema_version": "genoffice_docx_quick_edit_preflight_error.v1"}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
