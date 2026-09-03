from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

MAX_INPUT_BYTES = 2 * 1024 * 1024
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
IMAGE_REFERENCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9./_-]*@sha256:[a-f0-9]{64}$")


class SelfHostedProviderStackError(RuntimeError):
    pass


class StrictStackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _require_sha256(value: str) -> str:
    if not SHA256_PATTERN.fullmatch(value):
        raise ValueError("value must be a lowercase sha256 reference")
    return value


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


def _require_self_hosted_https_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("provider endpoint must be a credential-free HTTPS origin")
    hostname = parsed.hostname.lower()
    if hostname.endswith(".amazonaws.com") or hostname.endswith(".amazonaws.com.cn"):
        raise ValueError("provider endpoint must be self-hosted")
    return value.rstrip("/")


class ProviderVersions(StrictStackModel):
    kubernetes_minimum: str = Field(pattern=r"^1\.(3[0-9]|[4-9][0-9])\.[0-9]+$")
    rook_chart: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    ceph: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    openbao_chart: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    openbao: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")


class TopologyMinimums(StrictStackModel):
    kubernetes_nodes: int = Field(ge=1)
    failure_domains: int = Field(ge=1)
    ceph_monitors: int = Field(ge=1)
    ceph_managers: int = Field(ge=1)
    ceph_osds: int = Field(ge=1)
    rgw_instances: int = Field(ge=1)
    openbao_raft_voters: int = Field(ge=1)
    openbao_healthy_voters: int = Field(ge=1)
    openbao_audit_devices: int = Field(ge=1)


class SelfHostedProviderStackPolicy(StrictStackModel):
    schema_version: Literal["self_hosted_provider_stack_policy.v1"] = "self_hosted_provider_stack_policy.v1"
    policy_id: str = Field(min_length=1, max_length=128)
    provider_profile: Literal["self-hosted-ceph-openbao-v1"] = "self-hosted-ceph-openbao-v1"
    versions: ProviderVersions
    proof_minimums: TopologyMinimums
    production_minimums: TopologyMinimums
    maximum_evidence_age_hours: int = Field(ge=1, le=168)
    openbao_seal_strategy: Literal["shamir-offline-custody"] = "shamir-offline-custody"
    production_unseal_shares: int = Field(ge=3, le=16)
    production_unseal_threshold: int = Field(ge=2, le=16)
    require_digest_pinned_images: Literal[True] = True
    require_verified_release_signatures: Literal[True] = True
    require_tls: Literal[True] = True
    require_ceph_msgr2_encryption: Literal[True] = True
    require_object_lock_compliance: Literal[True] = True
    require_openbao_transit_for_sse_kms: Literal[True] = True
    require_separate_storage_and_signing_keys: Literal[True] = True
    require_openbao_storage_independent_from_ceph: Literal[True] = True
    forbid_public_provider_endpoints: Literal[True] = True
    forbid_root_runtime_tokens: Literal[True] = True
    forbid_unseal_material_in_cluster: Literal[True] = True

    @model_validator(mode="after")
    def require_production_not_weaker_than_proof(self) -> Self:
        for field_name in TopologyMinimums.model_fields:
            if getattr(self.production_minimums, field_name) < getattr(self.proof_minimums, field_name):
                raise ValueError("production topology minimums must not be weaker than proof minimums")
        if self.production_unseal_threshold > self.production_unseal_shares:
            raise ValueError("OpenBao unseal threshold must not exceed share count")
        return self


class ComponentArtifactEvidence(StrictStackModel):
    version: str = Field(pattern=r"^v?[0-9]+\.[0-9]+\.[0-9]+$")
    image_reference: str
    image_digest: str
    release_signature_verified: Literal[True]
    sbom_sha256: str

    _validate_hashes = field_validator("image_digest", "sbom_sha256")(_require_sha256)

    @model_validator(mode="after")
    def require_digest_pinned_reference(self) -> Self:
        if not IMAGE_REFERENCE_PATTERN.fullmatch(self.image_reference):
            raise ValueError("component image must be pinned by sha256 digest")
        if not self.image_reference.endswith("@" + self.image_digest):
            raise ValueError("component image digest does not match image reference")
        return self


class KubernetesStackEvidence(StrictStackModel):
    version: str = Field(pattern=r"^1\.[0-9]+\.[0-9]+$")
    node_count: int = Field(ge=1)
    failure_domain_count: int = Field(ge=1)
    network_policies_enforced: Literal[True]
    restricted_pod_security_enforced: Literal[True]
    provider_namespaces_dedicated: Literal[True]
    public_provider_endpoint_exposed: Literal[False]


class CephStackEvidence(StrictStackModel):
    rook: ComponentArtifactEvidence
    ceph: ComponentArtifactEvidence
    rgw_endpoint: str
    health_status: Literal["HEALTH_OK"]
    monitor_count: int = Field(ge=1)
    manager_count: int = Field(ge=1)
    osd_count: int = Field(ge=1)
    rgw_instance_count: int = Field(ge=1)
    failure_domain_count: int = Field(ge=1)
    msgr2_encryption_verified: Literal[True]
    osd_device_encryption_verified: Literal[True]
    rgw_tls_verified: Literal[True]
    bucket_versioning_verified: Literal[True]
    object_lock_enabled_at_bucket_creation: Literal[True]
    compliance_retention_verified: Literal[True]
    exact_version_delete_denial_verified: Literal[True]
    sse_kms_openbao_transit_verified: Literal[True]
    storage_key_non_exportable_verified: Literal[True]
    storage_key_ref_sha256: str
    health_report_sha256: str

    _validate_endpoint = field_validator("rgw_endpoint")(_require_self_hosted_https_origin)
    _validate_hashes = field_validator("storage_key_ref_sha256", "health_report_sha256")(_require_sha256)


class OpenBaoStackEvidence(StrictStackModel):
    chart_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    artifact: ComponentArtifactEvidence
    endpoint: str
    initialized: Literal[True]
    sealed: Literal[False]
    high_availability_enabled: Literal[True]
    raft_voter_count: int = Field(ge=1)
    healthy_raft_voter_count: int = Field(ge=1)
    failure_domain_count: int = Field(ge=1)
    tls_verified: Literal[True]
    dev_mode_enabled: Literal[False]
    root_token_in_runtime_use: Literal[False]
    audit_device_count: int = Field(ge=1)
    audit_devices_healthy: Literal[True]
    transit_enabled: Literal[True]
    signing_key_non_exportable_verified: Literal[True]
    signing_key_deletion_disabled: Literal[True]
    signing_key_ref_sha256: str
    seal_strategy: Literal["shamir-offline-custody"]
    unseal_share_count: int = Field(ge=1, le=16)
    unseal_threshold: int = Field(ge=1, le=16)
    unseal_material_stored_in_cluster: Literal[False]
    storage_independent_from_ceph: Literal[True]
    health_report_sha256: str

    _validate_endpoint = field_validator("endpoint")(_require_self_hosted_https_origin)
    _validate_hashes = field_validator("signing_key_ref_sha256", "health_report_sha256")(_require_sha256)

    @model_validator(mode="after")
    def require_valid_unseal_quorum(self) -> Self:
        if self.unseal_threshold > self.unseal_share_count:
            raise ValueError("OpenBao unseal threshold must not exceed share count")
        return self


class ProviderRecoveryEvidence(StrictStackModel):
    ceph_replication_verified: bool
    ceph_isolated_restore_verified: bool
    openbao_raft_snapshot_verified: bool
    openbao_isolated_restore_verified: bool
    independent_recovery_site_verified: bool
    recovery_credentials_independent: bool
    openbao_snapshot_target_independent_from_ceph: bool
    kubernetes_control_plane_restore_verified: bool
    ceph_restore_report_sha256: str
    openbao_restore_report_sha256: str

    _validate_hashes = field_validator(
        "ceph_restore_report_sha256",
        "openbao_restore_report_sha256",
    )(_require_sha256)


class SelfHostedProviderStackEvidence(StrictStackModel):
    schema_version: Literal["self_hosted_provider_stack_evidence.v1"] = "self_hosted_provider_stack_evidence.v1"
    target_profile: Literal["proof", "production"]
    provider_profile: Literal["self-hosted-ceph-openbao-v1"] = "self-hosted-ceph-openbao-v1"
    deployment_ref_sha256: str
    configuration_bundle_sha256: str
    observed_at_utc: datetime
    kubernetes: KubernetesStackEvidence
    ceph: CephStackEvidence
    openbao: OpenBaoStackEvidence
    recovery: ProviderRecoveryEvidence
    audit_worm_provider_acceptance_report_sha256: str | None = None
    storage_and_signing_keys_distinct: Literal[True]
    tenant_content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    destructive_action_requested: Literal[False] = False

    _validate_hashes = field_validator("deployment_ref_sha256", "configuration_bundle_sha256")(_require_sha256)
    _validate_timestamp = field_validator("observed_at_utc")(_require_utc)

    @field_validator("audit_worm_provider_acceptance_report_sha256")
    @classmethod
    def validate_optional_hash(cls, value: str | None) -> str | None:
        return _require_sha256(value) if value is not None else None

    @model_validator(mode="after")
    def require_distinct_key_references(self) -> Self:
        if self.ceph.storage_key_ref_sha256 == self.openbao.signing_key_ref_sha256:
            raise ValueError("storage and signing key references must be distinct")
        return self


class SelfHostedProviderStackReport(StrictStackModel):
    schema_version: Literal["self_hosted_provider_stack_report.v1"] = "self_hosted_provider_stack_report.v1"
    checked_at_utc: datetime
    valid_until_utc: datetime
    target_profile: Literal["proof", "production"]
    provider_profile: Literal["self-hosted-ceph-openbao-v1"] = "self-hosted-ceph-openbao-v1"
    policy_id: str
    policy_sha256: str
    evidence_sha256: str
    deployment_ref_sha256: str
    configuration_bundle_sha256: str
    version_pins_verified: bool
    topology_verified: bool
    storage_controls_verified: bool
    signing_controls_verified: bool
    isolation_controls_verified: bool
    recovery_controls_verified: bool
    audit_worm_acceptance_bound: bool
    metadata_only_evidence_verified: bool
    blocking_reasons: tuple[str, ...]
    ready: bool
    deployment_execution_allowed: Literal[False] = False
    secrets_included: Literal[False] = False
    tenant_content_included: Literal[False] = False
    report_sha256: str

    _validate_hashes = field_validator(
        "policy_sha256",
        "evidence_sha256",
        "deployment_ref_sha256",
        "configuration_bundle_sha256",
        "report_sha256",
    )(_require_sha256)
    _validate_checked_at = field_validator("checked_at_utc")(_require_utc)
    _validate_valid_until = field_validator("valid_until_utc")(_require_utc)


class SelfHostedProviderStackFailure(StrictStackModel):
    schema_version: Literal["self_hosted_provider_stack_failure.v1"] = "self_hosted_provider_stack_failure.v1"
    ready: Literal[False] = False
    failure_code: Literal["provider_stack_preflight_failed"] = "provider_stack_preflight_failed"
    secrets_included: Literal[False] = False
    tenant_content_included: Literal[False] = False


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _hash(value: object) -> str:
    encoded = value if isinstance(value, bytes) else _canonical_bytes(value)
    return "sha256:" + sha256(encoded).hexdigest()


def build_self_hosted_provider_stack_policy_hash(policy: SelfHostedProviderStackPolicy) -> str:
    return _hash(policy.model_dump(mode="json"))


def build_self_hosted_provider_stack_evidence_hash(evidence: SelfHostedProviderStackEvidence) -> str:
    return _hash(evidence.model_dump(mode="json"))


def build_self_hosted_provider_stack_report_hash(report: SelfHostedProviderStackReport) -> str:
    return _hash(report.model_dump(mode="json", exclude={"report_sha256"}))


def _version_tuple(value: str) -> tuple[int, int, int]:
    major, minor, patch = value.removeprefix("v").split(".")
    return int(major), int(minor), int(patch)


def build_self_hosted_provider_stack_report(
    *,
    policy: SelfHostedProviderStackPolicy,
    expected_policy_hash: str,
    evidence: SelfHostedProviderStackEvidence,
    checked_at_utc: datetime | None = None,
) -> SelfHostedProviderStackReport:
    _require_sha256(expected_policy_hash)
    if build_self_hosted_provider_stack_policy_hash(policy) != expected_policy_hash:
        raise SelfHostedProviderStackError("provider_stack_policy_hash_mismatch")

    checked_at = _require_utc(checked_at_utc or datetime.now(UTC))
    minimums = policy.production_minimums if evidence.target_profile == "production" else policy.proof_minimums
    version_pins_verified = all(
        (
            _version_tuple(evidence.kubernetes.version) >= _version_tuple(policy.versions.kubernetes_minimum),
            evidence.ceph.rook.version == policy.versions.rook_chart,
            evidence.ceph.ceph.version == policy.versions.ceph,
            evidence.openbao.chart_version == policy.versions.openbao_chart,
            evidence.openbao.artifact.version == policy.versions.openbao,
        )
    )
    topology_verified = all(
        (
            evidence.kubernetes.node_count >= minimums.kubernetes_nodes,
            evidence.kubernetes.failure_domain_count >= minimums.failure_domains,
            evidence.ceph.monitor_count >= minimums.ceph_monitors,
            evidence.ceph.manager_count >= minimums.ceph_managers,
            evidence.ceph.osd_count >= minimums.ceph_osds,
            evidence.ceph.rgw_instance_count >= minimums.rgw_instances,
            evidence.ceph.failure_domain_count >= minimums.failure_domains,
            evidence.openbao.raft_voter_count >= minimums.openbao_raft_voters,
            evidence.openbao.healthy_raft_voter_count >= minimums.openbao_healthy_voters,
            evidence.openbao.failure_domain_count >= minimums.failure_domains,
            evidence.openbao.audit_device_count >= minimums.openbao_audit_devices,
        )
    )
    storage_controls_verified = all(
        (
            evidence.ceph.msgr2_encryption_verified,
            evidence.ceph.osd_device_encryption_verified,
            evidence.ceph.rgw_tls_verified,
            evidence.ceph.bucket_versioning_verified,
            evidence.ceph.object_lock_enabled_at_bucket_creation,
            evidence.ceph.compliance_retention_verified,
            evidence.ceph.exact_version_delete_denial_verified,
            evidence.ceph.sse_kms_openbao_transit_verified,
            evidence.ceph.storage_key_non_exportable_verified,
        )
    )
    signing_controls_verified = all(
        (
            evidence.openbao.initialized,
            not evidence.openbao.sealed,
            evidence.openbao.high_availability_enabled,
            evidence.openbao.tls_verified,
            not evidence.openbao.dev_mode_enabled,
            not evidence.openbao.root_token_in_runtime_use,
            evidence.openbao.audit_devices_healthy,
            evidence.openbao.transit_enabled,
            evidence.openbao.signing_key_non_exportable_verified,
            evidence.openbao.signing_key_deletion_disabled,
            not evidence.openbao.unseal_material_stored_in_cluster,
            evidence.openbao.storage_independent_from_ceph,
            evidence.storage_and_signing_keys_distinct,
        )
    )
    if evidence.target_profile == "production":
        signing_controls_verified = signing_controls_verified and all(
            (
                evidence.openbao.unseal_share_count == policy.production_unseal_shares,
                evidence.openbao.unseal_threshold == policy.production_unseal_threshold,
            )
        )
    isolation_controls_verified = all(
        (
            evidence.kubernetes.network_policies_enforced,
            evidence.kubernetes.restricted_pod_security_enforced,
            evidence.kubernetes.provider_namespaces_dedicated,
            not evidence.kubernetes.public_provider_endpoint_exposed,
            not evidence.tenant_content_included,
            not evidence.secrets_included,
            not evidence.destructive_action_requested,
        )
    )
    recovery_controls_verified = True
    if evidence.target_profile == "production":
        recovery_controls_verified = all(
            (
                evidence.recovery.ceph_replication_verified,
                evidence.recovery.ceph_isolated_restore_verified,
                evidence.recovery.openbao_raft_snapshot_verified,
                evidence.recovery.openbao_isolated_restore_verified,
                evidence.recovery.independent_recovery_site_verified,
                evidence.recovery.recovery_credentials_independent,
                evidence.recovery.openbao_snapshot_target_independent_from_ceph,
                evidence.recovery.kubernetes_control_plane_restore_verified,
            )
        )
    audit_worm_acceptance_bound = evidence.audit_worm_provider_acceptance_report_sha256 is not None
    oldest_allowed = checked_at - timedelta(hours=policy.maximum_evidence_age_hours)
    evidence_fresh = oldest_allowed <= evidence.observed_at_utc <= checked_at

    checks = {
        "version_pins_not_verified": version_pins_verified,
        "topology_not_verified": topology_verified,
        "storage_controls_not_verified": storage_controls_verified,
        "signing_controls_not_verified": signing_controls_verified,
        "isolation_controls_not_verified": isolation_controls_verified,
        "recovery_controls_not_verified": recovery_controls_verified,
        "evidence_not_fresh": evidence_fresh,
    }
    if evidence.target_profile == "production":
        checks["audit_worm_acceptance_not_bound"] = audit_worm_acceptance_bound
    blocking_reasons = tuple(reason for reason, passed in checks.items() if not passed)
    draft = SelfHostedProviderStackReport(
        checked_at_utc=checked_at,
        valid_until_utc=evidence.observed_at_utc + timedelta(hours=policy.maximum_evidence_age_hours),
        target_profile=evidence.target_profile,
        policy_id=policy.policy_id,
        policy_sha256=expected_policy_hash,
        evidence_sha256=build_self_hosted_provider_stack_evidence_hash(evidence),
        deployment_ref_sha256=evidence.deployment_ref_sha256,
        configuration_bundle_sha256=evidence.configuration_bundle_sha256,
        version_pins_verified=version_pins_verified,
        topology_verified=topology_verified,
        storage_controls_verified=storage_controls_verified,
        signing_controls_verified=signing_controls_verified,
        isolation_controls_verified=isolation_controls_verified,
        recovery_controls_verified=recovery_controls_verified,
        audit_worm_acceptance_bound=audit_worm_acceptance_bound,
        metadata_only_evidence_verified=True,
        blocking_reasons=blocking_reasons,
        ready=not blocking_reasons,
        report_sha256="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_sha256": build_self_hosted_provider_stack_report_hash(draft)})


def _read_bounded(path: Path) -> bytes:
    try:
        if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
            raise SelfHostedProviderStackError("provider_stack_input_invalid")
        value = path.read_bytes()
    except OSError as exc:
        raise SelfHostedProviderStackError("provider_stack_input_invalid") from exc
    if not value:
        raise SelfHostedProviderStackError("provider_stack_input_invalid")
    return value


def load_self_hosted_provider_stack_policy(path: Path) -> SelfHostedProviderStackPolicy:
    return SelfHostedProviderStackPolicy.model_validate_json(_read_bounded(path))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate self-hosted Ceph and OpenBao deployment evidence")
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--expected-policy-hash", required=True)
    parser.add_argument("--evidence", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        policy = load_self_hosted_provider_stack_policy(args.policy)
        evidence = SelfHostedProviderStackEvidence.model_validate_json(_read_bounded(args.evidence))
        report = build_self_hosted_provider_stack_report(
            policy=policy,
            expected_policy_hash=args.expected_policy_hash,
            evidence=evidence,
        )
    except (SelfHostedProviderStackError, ValidationError, ValueError):
        print(_canonical_bytes(SelfHostedProviderStackFailure().model_dump(mode="json")).decode("ascii"))
        return 1
    print(_canonical_bytes(report.model_dump(mode="json")).decode("ascii"))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
