from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.operations.genoffice_docx_prebuild_sbom import (
    GENOFFICE_DOCX_CYCLONEDX_SPEC_VERSION,
    GenOfficeDocxPrebuildSbomError,
    genoffice_docx_prebuild_sbom_hash,
    load_genoffice_docx_prebuild_sbom,
)
from suite.operations.genoffice_docx_source_admission import (
    GenOfficeSourceAdmissionError,
    load_genoffice_docx_source_admission_report,
)
from suite.operations.genoffice_vendored_provenance_admission import (
    GenOfficeVendoredProvenanceError,
    load_genoffice_vendored_provenance_report,
)

GENOFFICE_DOCX_SUPPLY_CHAIN_ADMISSION_SCHEMA_VERSION = "genoffice_docx_supply_chain_admission_report.v1"
GENOFFICE_DOCX_REVIEWED_SOURCE_REPORT_HASH = "sha256:7a4eb66cfeefbf6defad574f33b07c904b62c7f076ecb21277e99ae87e2b951d"
GENOFFICE_REVIEWED_VENDORED_PROVENANCE_REPORT_HASH = (
    "sha256:5ac1fdfa83034db3a8da06985b5f96e87a8eb0acfe3614f05b4fb3afe8e3dd04"
)
CYCLONEDX_VALIDATOR_REF = "cyclonedx-cli-0.32.0@sha256:9a858a15e7b0843606efc0ff19d5f7575011a5428d7f3d343b4f6cf09d8f0d4e"
TRIVY_SCANNER_VERSION = "0.73.0"
TRIVY_SCANNER_IMAGE_REF = "aquasec/trivy@sha256:7cced7cae583819fc7806d4cbc0dbbc7cad18b99f7d3e235192e6da8c091045c"
MAX_EVIDENCE_SIZE_BYTES = 4 * 1024 * 1024
MAX_DB_AGE_SECONDS = 24 * 60 * 60
SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")


class GenOfficeDocxSupplyChainAdmissionError(ValueError):
    pass


class GenOfficeVulnerabilityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vulnerability_id: str
    package_purl: str
    package_name: str
    installed_version: str
    fixed_version: str | None
    severity: str
    primary_url: str | None


class GenOfficeDocxSupplyChainAdmissionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_docx_supply_chain_admission_report.v1"] = (
        "genoffice_docx_supply_chain_admission_report.v1"
    )
    source_report_hash: str
    source_archive_sha256: str
    vendored_provenance_report_hash: str
    sbom_spec_version: str
    sbom_lifecycle_phase: str
    sbom_hash: str
    sbom_component_count: int
    schema_validation_receipt_hash: str
    schema_validator_ref: str
    schema_validation_passed: bool
    scanner_name: str
    scanner_version: str
    scanner_image_ref: str
    vulnerability_report_hash: str
    scanner_artifact_type: str
    scanner_package_count: int
    scanner_package_purls: tuple[str, ...]
    vulnerability_count: int
    severity_counts: dict[str, int]
    vulnerability_findings: tuple[GenOfficeVulnerabilityFinding, ...]
    trivy_db_metadata_hash: str
    trivy_db_schema_version: int
    trivy_db_updated_at_utc: datetime
    trivy_db_downloaded_at_utc: datetime
    trivy_db_next_update_at_utc: datetime
    scan_observed_at_utc: datetime
    trivy_db_age_seconds_at_scan: int
    trivy_db_max_age_seconds: int
    sbom_exact_inventory_verified: bool
    scanner_exact_inventory_verified: bool
    trivy_db_fresh_at_scan: bool
    high_and_critical_findings_absent: bool
    automated_sbom_and_vulnerability_gate_passed: bool
    registry_signature_verified: bool = False
    registry_attestation_verified: bool = False
    legal_review_complete: bool = False
    reproducible_build_and_provenance_complete: bool = False
    source_import_allowed: bool = False
    engine_execution_allowed: bool = False
    production_use_allowed: bool = False
    remaining_gates: tuple[str, ...] = (
        "human_legal_notice_trademark_and_compound_license_review",
        "npm_registry_signature_and_slsa_attestation_verification",
        "reproducible_isolated_build_and_signed_provenance",
        "malicious_ooxml_and_archive_expansion_corpus",
        "word_libreoffice_genoffice_collabio_fidelity_corpus",
        "isolated_engine_worker_and_resource_limits",
        "candidate_revalidation_preview_confirmation_and_receipt",
        "draft_candidate_receipt_backup_restore_and_failover_drill",
    )
    report_hash: str

    @model_validator(mode="after")
    def require_pinned_closed_boundary(self) -> GenOfficeDocxSupplyChainAdmissionReport:
        expected = {
            "source_report_hash": GENOFFICE_DOCX_REVIEWED_SOURCE_REPORT_HASH,
            "vendored_provenance_report_hash": GENOFFICE_REVIEWED_VENDORED_PROVENANCE_REPORT_HASH,
            "sbom_spec_version": GENOFFICE_DOCX_CYCLONEDX_SPEC_VERSION,
            "sbom_lifecycle_phase": "pre-build",
            "schema_validator_ref": CYCLONEDX_VALIDATOR_REF,
            "scanner_name": "Trivy",
            "scanner_version": TRIVY_SCANNER_VERSION,
            "scanner_image_ref": TRIVY_SCANNER_IMAGE_REF,
            "scanner_artifact_type": "cyclonedx",
            "trivy_db_schema_version": 2,
            "trivy_db_max_age_seconds": MAX_DB_AGE_SECONDS,
        }
        for field, value in expected.items():
            if getattr(self, field) != value:
                raise ValueError(f"GenOffice supply-chain field {field} is not pinned")
        if self.automated_sbom_and_vulnerability_gate_passed and not all(
            (
                self.schema_validation_passed,
                self.sbom_exact_inventory_verified,
                self.scanner_exact_inventory_verified,
                self.trivy_db_fresh_at_scan,
                self.high_and_critical_findings_absent,
            )
        ):
            raise ValueError("GenOffice automated supply-chain gate is inconsistent")
        if any(
            (
                self.registry_signature_verified,
                self.registry_attestation_verified,
                self.legal_review_complete,
                self.reproducible_build_and_provenance_complete,
                self.source_import_allowed,
                self.engine_execution_allowed,
                self.production_use_allowed,
            )
        ):
            raise ValueError("GenOffice pre-build supply-chain evidence opened an unreviewed boundary")
        return self


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_EVIDENCE_SIZE_BYTES:
                    raise GenOfficeDocxSupplyChainAdmissionError("Supply-chain evidence exceeds its size limit")
                digest.update(chunk)
    except OSError as exc:
        raise GenOfficeDocxSupplyChainAdmissionError("Supply-chain evidence cannot be read") from exc
    return f"sha256:{digest.hexdigest()}"


def _json_object(path: Path) -> Mapping[str, Any]:
    _file_hash(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenOfficeDocxSupplyChainAdmissionError("Supply-chain evidence is not readable JSON") from exc
    if not isinstance(value, dict):
        raise GenOfficeDocxSupplyChainAdmissionError("Supply-chain evidence must be a JSON object")
    return value


def _timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise GenOfficeDocxSupplyChainAdmissionError(f"{field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GenOfficeDocxSupplyChainAdmissionError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GenOfficeDocxSupplyChainAdmissionError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _schema_receipt(path: Path, *, sbom_hash: str) -> tuple[str, bool]:
    receipt_hash = _file_hash(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise GenOfficeDocxSupplyChainAdmissionError("CycloneDX validation receipt cannot be read") from exc
    entries: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or key in entries:
            raise GenOfficeDocxSupplyChainAdmissionError("CycloneDX validation receipt is malformed")
        entries[key] = value
    expected = {
        "schema": "cyclonedx-1.6",
        "validator": CYCLONEDX_VALIDATOR_REF,
        "sbom_sha256": sbom_hash.removeprefix("sha256:"),
        "status": "valid",
    }
    if entries != expected:
        raise GenOfficeDocxSupplyChainAdmissionError("CycloneDX validation receipt is not bound to the SBOM")
    return receipt_hash, True


def _expected_purls(sbom: Mapping[str, Any]) -> tuple[str, ...]:
    metadata = sbom.get("metadata")
    components = sbom.get("components")
    if not isinstance(metadata, dict) or not isinstance(components, list):
        raise GenOfficeDocxSupplyChainAdmissionError("CycloneDX component inventory is missing")
    root = metadata.get("component")
    if not isinstance(root, dict):
        raise GenOfficeDocxSupplyChainAdmissionError("CycloneDX root component is missing")
    all_components = [root, *components]
    raw_purls = [item.get("purl") for item in all_components if isinstance(item, dict)]
    if not all(isinstance(purl, str) and purl.startswith("pkg:npm/") for purl in raw_purls):
        raise GenOfficeDocxSupplyChainAdmissionError("CycloneDX inventory contains a component without an npm PURL")
    purls = [str(purl) for purl in raw_purls]
    if len(purls) != len(all_components) or len(set(purls)) != len(purls):
        raise GenOfficeDocxSupplyChainAdmissionError("CycloneDX npm PURL inventory is incomplete or duplicated")
    return tuple(sorted(purls))


def _trivy_report(
    path: Path, *, expected_purls: tuple[str, ...]
) -> tuple[str, datetime, tuple[str, ...], tuple[GenOfficeVulnerabilityFinding, ...], dict[str, int]]:
    report_hash = _file_hash(path)
    report = _json_object(path)
    trivy = report.get("Trivy")
    if (
        report.get("SchemaVersion") != 2
        or not isinstance(trivy, dict)
        or trivy.get("Version") != TRIVY_SCANNER_VERSION
        or report.get("ArtifactType") != "cyclonedx"
        or PurePosixPath(str(report.get("ArtifactName", ""))).name != "genoffice-docx-prebuild.cdx.json"
    ):
        raise GenOfficeDocxSupplyChainAdmissionError("Trivy report identity is not the reviewed scanner output")
    scan_time = _timestamp(report.get("CreatedAt"), field="Trivy CreatedAt")
    results = report.get("Results")
    if not isinstance(results, list) or not results:
        raise GenOfficeDocxSupplyChainAdmissionError("Trivy report has no scan results")
    package_purls: list[str] = []
    findings: list[GenOfficeVulnerabilityFinding] = []
    for result in results:
        if not isinstance(result, dict):
            raise GenOfficeDocxSupplyChainAdmissionError("Trivy result is malformed")
        packages = result.get("Packages", [])
        vulnerabilities = result.get("Vulnerabilities", [])
        if not isinstance(packages, list) or not isinstance(vulnerabilities, list):
            raise GenOfficeDocxSupplyChainAdmissionError("Trivy package or vulnerability inventory is malformed")
        for package in packages:
            identifier = package.get("Identifier") if isinstance(package, dict) else None
            purl = identifier.get("PURL") if isinstance(identifier, dict) else None
            if not isinstance(purl, str):
                raise GenOfficeDocxSupplyChainAdmissionError("Trivy package has no PURL")
            package_purls.append(purl)
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                raise GenOfficeDocxSupplyChainAdmissionError("Trivy vulnerability is malformed")
            severity = str(vulnerability.get("Severity", "UNKNOWN")).upper()
            if severity not in SEVERITIES:
                severity = "UNKNOWN"
            package_identifier = vulnerability.get("PkgIdentifier")
            purl = package_identifier.get("PURL") if isinstance(package_identifier, dict) else None
            findings.append(
                GenOfficeVulnerabilityFinding(
                    vulnerability_id=str(vulnerability.get("VulnerabilityID", "unknown")),
                    package_purl=str(purl or "unknown"),
                    package_name=str(vulnerability.get("PkgName", "unknown")),
                    installed_version=str(vulnerability.get("InstalledVersion", "unknown")),
                    fixed_version=(str(vulnerability["FixedVersion"]) if vulnerability.get("FixedVersion") else None),
                    severity=severity,
                    primary_url=(str(vulnerability["PrimaryURL"]) if vulnerability.get("PrimaryURL") else None),
                )
            )
    scanned_purls = tuple(sorted(package_purls))
    if len(scanned_purls) != len(set(scanned_purls)) or scanned_purls != expected_purls:
        raise GenOfficeDocxSupplyChainAdmissionError("Trivy package inventory does not exactly match the SBOM")
    severity_counter = Counter(item.severity for item in findings)
    severity_counts = {severity: severity_counter.get(severity, 0) for severity in SEVERITIES}
    return report_hash, scan_time, scanned_purls, tuple(findings), severity_counts


def _db_metadata(path: Path, *, scan_time: datetime) -> tuple[str, int, datetime, datetime, datetime, int, bool]:
    metadata_hash = _file_hash(path)
    metadata = _json_object(path)
    version = metadata.get("Version")
    if version != 2:
        raise GenOfficeDocxSupplyChainAdmissionError("Trivy DB schema version is not supported")
    updated_at = _timestamp(metadata.get("UpdatedAt"), field="Trivy DB UpdatedAt")
    downloaded_at = _timestamp(metadata.get("DownloadedAt"), field="Trivy DB DownloadedAt")
    next_update = _timestamp(metadata.get("NextUpdate"), field="Trivy DB NextUpdate")
    age_seconds = int((scan_time - updated_at).total_seconds())
    fresh = all(
        (
            0 <= age_seconds <= MAX_DB_AGE_SECONDS,
            updated_at <= downloaded_at <= scan_time,
            scan_time < next_update,
        )
    )
    return metadata_hash, version, updated_at, downloaded_at, next_update, age_seconds, fresh


def build_genoffice_docx_supply_chain_admission_report(
    *,
    source_report_path: Path,
    vendored_provenance_path: Path,
    sbom_path: Path,
    schema_validation_receipt_path: Path,
    vulnerability_report_path: Path,
    trivy_db_metadata_path: Path,
) -> GenOfficeDocxSupplyChainAdmissionReport:
    try:
        source_report = load_genoffice_docx_source_admission_report(source_report_path)
        provenance = load_genoffice_vendored_provenance_report(vendored_provenance_path)
        sbom = load_genoffice_docx_prebuild_sbom(
            sbom_path=sbom_path,
            source_report=source_report,
            vendored_provenance=provenance,
        )
    except (GenOfficeSourceAdmissionError, GenOfficeVendoredProvenanceError, GenOfficeDocxPrebuildSbomError) as exc:
        raise GenOfficeDocxSupplyChainAdmissionError("Pinned GenOffice source or SBOM evidence is invalid") from exc
    if source_report.report_hash != GENOFFICE_DOCX_REVIEWED_SOURCE_REPORT_HASH:
        raise GenOfficeDocxSupplyChainAdmissionError("GenOffice source report is not reviewed")
    if provenance.report_hash != GENOFFICE_REVIEWED_VENDORED_PROVENANCE_REPORT_HASH:
        raise GenOfficeDocxSupplyChainAdmissionError("GenOffice vendored provenance report is not reviewed")

    sbom_hash = genoffice_docx_prebuild_sbom_hash(sbom)
    expected_purls = _expected_purls(sbom)
    receipt_hash, schema_validated = _schema_receipt(schema_validation_receipt_path, sbom_hash=sbom_hash)
    vulnerability_report_hash, scan_time, scanned_purls, findings, severity_counts = _trivy_report(
        vulnerability_report_path, expected_purls=expected_purls
    )
    db_hash, db_version, db_updated, db_downloaded, db_next, db_age, db_fresh = _db_metadata(
        trivy_db_metadata_path, scan_time=scan_time
    )
    high_critical_absent = severity_counts["HIGH"] == 0 and severity_counts["CRITICAL"] == 0
    automated_gate = schema_validated and db_fresh and high_critical_absent
    draft = GenOfficeDocxSupplyChainAdmissionReport(
        source_report_hash=source_report.report_hash,
        source_archive_sha256=source_report.archive_sha256,
        vendored_provenance_report_hash=provenance.report_hash,
        sbom_spec_version=str(sbom["specVersion"]),
        sbom_lifecycle_phase=str(sbom["metadata"]["lifecycles"][0]["phase"]),
        sbom_hash=sbom_hash,
        sbom_component_count=len(expected_purls),
        schema_validation_receipt_hash=receipt_hash,
        schema_validator_ref=CYCLONEDX_VALIDATOR_REF,
        schema_validation_passed=schema_validated,
        scanner_name="Trivy",
        scanner_version=TRIVY_SCANNER_VERSION,
        scanner_image_ref=TRIVY_SCANNER_IMAGE_REF,
        vulnerability_report_hash=vulnerability_report_hash,
        scanner_artifact_type="cyclonedx",
        scanner_package_count=len(scanned_purls),
        scanner_package_purls=scanned_purls,
        vulnerability_count=len(findings),
        severity_counts=severity_counts,
        vulnerability_findings=findings,
        trivy_db_metadata_hash=db_hash,
        trivy_db_schema_version=db_version,
        trivy_db_updated_at_utc=db_updated,
        trivy_db_downloaded_at_utc=db_downloaded,
        trivy_db_next_update_at_utc=db_next,
        scan_observed_at_utc=scan_time,
        trivy_db_age_seconds_at_scan=db_age,
        trivy_db_max_age_seconds=MAX_DB_AGE_SECONDS,
        sbom_exact_inventory_verified=True,
        scanner_exact_inventory_verified=True,
        trivy_db_fresh_at_scan=db_fresh,
        high_and_critical_findings_absent=high_critical_absent,
        automated_sbom_and_vulnerability_gate_passed=automated_gate,
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_docx_supply_chain_report_hash(draft)})


def build_genoffice_docx_supply_chain_report_hash(report: GenOfficeDocxSupplyChainAdmissionReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def persist_genoffice_docx_supply_chain_admission_report(
    *, report: GenOfficeDocxSupplyChainAdmissionReport, report_path: Path
) -> None:
    if build_genoffice_docx_supply_chain_report_hash(report) != report.report_hash:
        raise GenOfficeDocxSupplyChainAdmissionError("GenOffice supply-chain admission report hash is invalid")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary_path.replace(report_path)


def load_genoffice_docx_supply_chain_admission_report(
    report_path: Path,
) -> GenOfficeDocxSupplyChainAdmissionReport:
    try:
        report = GenOfficeDocxSupplyChainAdmissionReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GenOfficeDocxSupplyChainAdmissionError("GenOffice supply-chain report cannot be loaded") from exc
    if build_genoffice_docx_supply_chain_report_hash(report) != report.report_hash:
        raise GenOfficeDocxSupplyChainAdmissionError("GenOffice supply-chain admission report hash is invalid")
    return report


def run_genoffice_docx_supply_chain_admission_from_environment(
    env: Mapping[str, str],
) -> GenOfficeDocxSupplyChainAdmissionReport:
    path_keys = {
        "source_report_path": "SUITE_GENOFFICE_SOURCE_ADMISSION_REPORT_PATH",
        "vendored_provenance_path": "SUITE_GENOFFICE_VENDORED_PROVENANCE_REPORT_PATH",
        "sbom_path": "SUITE_GENOFFICE_PREBUILD_SBOM_PATH",
        "schema_validation_receipt_path": "SUITE_GENOFFICE_SBOM_SCHEMA_VALIDATION_RECEIPT_PATH",
        "vulnerability_report_path": "SUITE_GENOFFICE_VULNERABILITY_REPORT_PATH",
        "trivy_db_metadata_path": "SUITE_GENOFFICE_TRIVY_DB_METADATA_PATH",
        "output_path": "SUITE_GENOFFICE_SUPPLY_CHAIN_ADMISSION_REPORT_PATH",
    }
    values = {name: env.get(key, "").strip() for name, key in path_keys.items()}
    missing = sorted(name for name, value in values.items() if not value)
    if missing:
        raise GenOfficeDocxSupplyChainAdmissionError(f"GenOffice supply-chain paths are missing: {missing}")
    report = build_genoffice_docx_supply_chain_admission_report(
        source_report_path=Path(values["source_report_path"]),
        vendored_provenance_path=Path(values["vendored_provenance_path"]),
        sbom_path=Path(values["sbom_path"]),
        schema_validation_receipt_path=Path(values["schema_validation_receipt_path"]),
        vulnerability_report_path=Path(values["vulnerability_report_path"]),
        trivy_db_metadata_path=Path(values["trivy_db_metadata_path"]),
    )
    persist_genoffice_docx_supply_chain_admission_report(report=report, report_path=Path(values["output_path"]))
    return report


def main() -> None:
    try:
        report = run_genoffice_docx_supply_chain_admission_from_environment(os.environ)
        print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
        raise SystemExit(0 if report.automated_sbom_and_vulnerability_gate_passed else 2)
    except GenOfficeDocxSupplyChainAdmissionError as exc:
        print(json.dumps({"error": str(exc), "schema_version": GENOFFICE_DOCX_SUPPLY_CHAIN_ADMISSION_SCHEMA_VERSION}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
