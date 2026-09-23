from __future__ import annotations

import importlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from suite.kms.openbao_transit import OpenBaoTransitHttpClient, OpenBaoTransitSigningKeyInspector
from suite.kms.signing import AuditSigningProviderInspection, AuditSigningProviderInspector

MAX_INPUT_BYTES = 1024 * 1024
MAX_SECRET_BYTES = 16 * 1024
MAX_STATUS_AGE = timedelta(minutes=30)
MAX_CLOCK_SKEW = timedelta(minutes=5)
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")

RGW_ENDPOINT = "https://rook-ceph-rgw-collabio-objects.rook-ceph.svc.cluster.local:443"
OPENBAO_ENDPOINT = "https://openbao-active.openbao.svc.cluster.local:8200"
S3_REGION = "us-east-1"
SIGNING_PROVIDER_KEY_ID = "openbao-transit://collabio-signing/collabio-audit-signing/v1"


class SelfHostedProviderProtocolProbeError(RuntimeError):
    pass


class StrictProbeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _require_sha256(value: str) -> str:
    if not SHA256_PATTERN.fullmatch(value):
        raise ValueError("value must be a lowercase sha256 reference")
    return value


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


class ProviderDevelopmentVersions(StrictProbeModel):
    kubernetes: Literal["v1.36.4"]
    rook: Literal["v1.20.7"]
    ceph: Literal["20.2.4"]
    openbao_chart: Literal["0.29.4"]
    openbao: Literal["2.6.2"]


class ProviderDevelopmentTopology(StrictProbeModel):
    kubernetes_nodes: Literal[3]
    simulated_failure_domains: Literal[3]
    physical_hosts: Literal[1]
    openbao_raft_voters: Literal[3]
    rgw_instances: Literal[2]


class ProviderDevelopmentControls(StrictProbeModel):
    kubernetes_secrets_encrypted: Literal[True]
    kubernetes_audit_level: Literal["Metadata"]
    network_policy_controller: Literal["k3s-kube-router"]
    provider_endpoints_public: Literal[False]
    ceph_health: Literal["HEALTH_OK"]
    ceph_msgr2_encryption: Literal[True]
    ceph_osd_encryption: Literal[True]
    openbao_tls: Literal[True]
    openbao_dev_mode: Literal[False]
    openbao_audit_devices: int = Field(ge=2)
    openbao_storage_independent_from_ceph: Literal[True]
    storage_and_signing_keys_distinct: Literal[True]
    storage_key_exportable: Literal[False]


class SelfHostedProviderDevelopmentStatus(StrictProbeModel):
    schema_version: Literal["self_hosted_provider_development_status.v1"]
    observed_at_utc: datetime
    environment: Literal["development-single-physical-host"]
    production_ha_claim: Literal[False]
    tenant_content_included: Literal[False]
    secrets_included: Literal[False]
    cluster: Literal["collabio-provider"]
    versions: ProviderDevelopmentVersions
    topology: ProviderDevelopmentTopology
    controls: ProviderDevelopmentControls

    _validate_observed_at = field_validator("observed_at_utc")(_require_utc)


class SelfHostedProviderProtocolProbeReport(StrictProbeModel):
    schema_version: Literal["self_hosted_provider_protocol_probe_report.v1"] = (
        "self_hosted_provider_protocol_probe_report.v1"
    )
    checked_at_utc: datetime
    provider_profile: Literal["self-hosted-ceph-openbao-v1"] = "self-hosted-ceph-openbao-v1"
    cluster: Literal["collabio-provider"] = "collabio-provider"
    provider_status_sha256: str
    runtime_image_id_sha256: str
    tls_ca_sha256: str
    rgw_endpoint_sha256: str
    openbao_endpoint_sha256: str
    s3_region: Literal["us-east-1"] = "us-east-1"
    s3_request_id_sha256: str
    visible_bucket_count: int = Field(ge=0)
    signing_provider_key_id_sha256: str
    signing_public_key_sha256: str
    signing_key_type: Literal["ecdsa-p256"] = "ecdsa-p256"
    signing_key_version: Literal[1] = 1
    signing_key_inspection_request_id_sha256: str
    kubernetes_nodes: int = Field(ge=3)
    openbao_raft_voters: int = Field(ge=3)
    rgw_instances: int = Field(ge=2)
    ceph_health: Literal["HEALTH_OK"] = "HEALTH_OK"
    authenticated_rgw_read_only_call_verified: Literal[True] = True
    authenticated_openbao_key_read_verified: Literal[True] = True
    bucket_names_included: Literal[False] = False
    object_versions_read: Literal[False] = False
    signature_operation_attempted: Literal[False] = False
    write_attempted: Literal[False] = False
    delete_attempted: Literal[False] = False
    tenant_content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    production_evidence_admissible: Literal[False] = False
    production_ha_claim: Literal[False] = False
    ready: Literal[True] = True
    report_sha256: str

    _validate_hashes = field_validator(
        "provider_status_sha256",
        "runtime_image_id_sha256",
        "tls_ca_sha256",
        "rgw_endpoint_sha256",
        "openbao_endpoint_sha256",
        "s3_request_id_sha256",
        "signing_provider_key_id_sha256",
        "signing_public_key_sha256",
        "signing_key_inspection_request_id_sha256",
        "report_sha256",
    )(_require_sha256)
    _validate_checked_at = field_validator("checked_at_utc")(_require_utc)


class SelfHostedProviderProtocolProbeFailure(StrictProbeModel):
    schema_version: Literal["self_hosted_provider_protocol_probe_failure.v1"] = (
        "self_hosted_provider_protocol_probe_failure.v1"
    )
    ready: Literal[False] = False
    failure_code: Literal["provider_protocol_probe_failed"] = "provider_protocol_probe_failed"
    tenant_content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    production_evidence_admissible: Literal[False] = False
    write_attempted: Literal[False] = False
    delete_attempted: Literal[False] = False


class ProviderProbeS3Client(Protocol):
    def list_buckets(self) -> Mapping[str, Any]: ...


def build_self_hosted_provider_protocol_probe_report_hash(
    report: SelfHostedProviderProtocolProbeReport,
) -> str:
    return _sha256_ref(_canonical_bytes(report.model_dump(mode="json", exclude={"report_sha256"})))


def probe_self_hosted_provider_protocols(
    *,
    status_bytes: bytes,
    expected_status_sha256: str,
    runtime_image_id_sha256: str,
    tls_ca_bytes: bytes,
    s3_client: ProviderProbeS3Client,
    signing_key_inspector: AuditSigningProviderInspector,
    checked_at_utc: datetime | None = None,
) -> SelfHostedProviderProtocolProbeReport:
    _require_sha256(expected_status_sha256)
    _require_sha256(runtime_image_id_sha256)
    if not tls_ca_bytes or len(tls_ca_bytes) > MAX_INPUT_BYTES:
        raise SelfHostedProviderProtocolProbeError("provider_probe_ca_invalid")
    if _sha256_ref(status_bytes) != expected_status_sha256:
        raise SelfHostedProviderProtocolProbeError("provider_status_hash_mismatch")
    try:
        status = SelfHostedProviderDevelopmentStatus.model_validate_json(status_bytes)
    except (ValidationError, ValueError) as exc:
        raise SelfHostedProviderProtocolProbeError("provider_status_invalid") from exc

    checked_at = _require_utc(checked_at_utc or datetime.now(UTC))
    if not checked_at - MAX_STATUS_AGE <= status.observed_at_utc <= checked_at + MAX_CLOCK_SKEW:
        raise SelfHostedProviderProtocolProbeError("provider_status_not_fresh")

    try:
        s3_response = s3_client.list_buckets()
    except Exception as exc:
        raise SelfHostedProviderProtocolProbeError("authenticated_rgw_probe_failed") from exc
    bucket_count = _bucket_count(s3_response)
    s3_request_id_sha256 = _s3_request_id_hash(s3_response)

    try:
        signing_key = signing_key_inspector.inspect_provider_key(provider_key_id=SIGNING_PROVIDER_KEY_ID)
    except Exception as exc:
        raise SelfHostedProviderProtocolProbeError("authenticated_openbao_probe_failed") from exc
    _require_expected_signing_key(signing_key)

    draft = SelfHostedProviderProtocolProbeReport(
        checked_at_utc=checked_at,
        provider_status_sha256=expected_status_sha256,
        runtime_image_id_sha256=runtime_image_id_sha256,
        tls_ca_sha256=_sha256_ref(tls_ca_bytes),
        rgw_endpoint_sha256=_sha256_ref(RGW_ENDPOINT.encode("utf-8")),
        openbao_endpoint_sha256=_sha256_ref(OPENBAO_ENDPOINT.encode("utf-8")),
        s3_request_id_sha256=s3_request_id_sha256,
        visible_bucket_count=bucket_count,
        signing_provider_key_id_sha256=_sha256_ref(signing_key.provider_key_id.encode("utf-8")),
        signing_public_key_sha256=_sha256_ref(signing_key.public_key_der),
        signing_key_inspection_request_id_sha256=_sha256_ref(signing_key.request_id.encode("utf-8")),
        kubernetes_nodes=status.topology.kubernetes_nodes,
        openbao_raft_voters=status.topology.openbao_raft_voters,
        rgw_instances=status.topology.rgw_instances,
        report_sha256="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_sha256": build_self_hosted_provider_protocol_probe_report_hash(draft)})


def _require_expected_signing_key(inspection: AuditSigningProviderInspection) -> None:
    if (
        inspection.provider_key_id != SIGNING_PROVIDER_KEY_ID
        or inspection.key_type != "ecdsa-p256"
        or inspection.key_version != 1
        or not inspection.public_key_der
        or not inspection.request_id.strip()
    ):
        raise SelfHostedProviderProtocolProbeError("openbao_signing_key_mismatch")


def _bucket_count(response: Mapping[str, Any]) -> int:
    buckets = response.get("Buckets")
    if not isinstance(buckets, Sequence) or isinstance(buckets, (str, bytes, bytearray)):
        raise SelfHostedProviderProtocolProbeError("rgw_bucket_response_invalid")
    return len(buckets)


def _s3_request_id_hash(response: Mapping[str, Any]) -> str:
    metadata = response.get("ResponseMetadata")
    if not isinstance(metadata, Mapping) or metadata.get("HTTPStatusCode") != 200:
        raise SelfHostedProviderProtocolProbeError("rgw_response_metadata_invalid")
    request_id = str(metadata.get("RequestId", "")).strip()
    if not request_id:
        raise SelfHostedProviderProtocolProbeError("rgw_request_id_missing")
    return _sha256_ref(request_id.encode("utf-8"))


def _read_bounded(path: Path, maximum_bytes: int) -> bytes:
    try:
        if not path.is_file() or path.stat().st_size > maximum_bytes:
            raise SelfHostedProviderProtocolProbeError("provider_probe_input_invalid")
        value = path.read_bytes()
    except OSError as exc:
        raise SelfHostedProviderProtocolProbeError("provider_probe_input_invalid") from exc
    if not value:
        raise SelfHostedProviderProtocolProbeError("provider_probe_input_invalid")
    return value


def _read_secret(path: Path) -> str:
    try:
        value = _read_bounded(path, MAX_SECRET_BYTES).decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise SelfHostedProviderProtocolProbeError("provider_probe_secret_invalid") from exc
    if not value:
        raise SelfHostedProviderProtocolProbeError("provider_probe_secret_invalid")
    return value


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise SelfHostedProviderProtocolProbeError("provider_probe_configuration_missing")
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256_ref(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def main(*, env: Mapping[str, str] | None = None) -> int:
    runtime_env = os.environ if env is None else env
    try:
        if runtime_env.get("SUITE_SELF_HOSTED_PROVIDER_PROTOCOL_PROBE_ENABLED", "").strip() != "1":
            raise SelfHostedProviderProtocolProbeError("provider_protocol_probe_not_enabled")
        status_path = Path(_required_env(runtime_env, "SUITE_SELF_HOSTED_PROVIDER_PROTOCOL_PROBE_STATUS_FILE"))
        ca_path = Path(_required_env(runtime_env, "SUITE_SELF_HOSTED_PROVIDER_PROTOCOL_PROBE_CA_FILE"))
        access_key = _read_secret(
            Path(_required_env(runtime_env, "SUITE_SELF_HOSTED_PROVIDER_PROTOCOL_PROBE_S3_ACCESS_KEY_FILE"))
        )
        secret_key = _read_secret(
            Path(_required_env(runtime_env, "SUITE_SELF_HOSTED_PROVIDER_PROTOCOL_PROBE_S3_SECRET_KEY_FILE"))
        )
        openbao_token = _read_secret(
            Path(_required_env(runtime_env, "SUITE_SELF_HOSTED_PROVIDER_PROTOCOL_PROBE_OPENBAO_TOKEN_FILE"))
        )
        ca_bytes = _read_bounded(ca_path, MAX_INPUT_BYTES)

        boto3_module = importlib.import_module("boto3")
        botocore_config = importlib.import_module("botocore.config")
        client_factory: Any = boto3_module.client
        s3_client = cast(
            ProviderProbeS3Client,
            client_factory(
                "s3",
                endpoint_url=RGW_ENDPOINT,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=S3_REGION,
                verify=str(ca_path),
                config=botocore_config.Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            ),
        )
        openbao_client = OpenBaoTransitHttpClient(
            address=OPENBAO_ENDPOINT,
            token=openbao_token,
            tls_ca_file=str(ca_path),
        )
        report = probe_self_hosted_provider_protocols(
            status_bytes=_read_bounded(status_path, MAX_INPUT_BYTES),
            expected_status_sha256=_required_env(
                runtime_env,
                "SUITE_SELF_HOSTED_PROVIDER_PROTOCOL_PROBE_EXPECTED_STATUS_SHA256",
            ),
            runtime_image_id_sha256=_required_env(
                runtime_env,
                "SUITE_SELF_HOSTED_PROVIDER_PROTOCOL_PROBE_RUNTIME_IMAGE_ID",
            ),
            tls_ca_bytes=ca_bytes,
            s3_client=s3_client,
            signing_key_inspector=OpenBaoTransitSigningKeyInspector(client=openbao_client),
        )
    except (
        ImportError,
        SelfHostedProviderProtocolProbeError,
        ValidationError,
        ValueError,
    ):
        print(_canonical_bytes(SelfHostedProviderProtocolProbeFailure().model_dump(mode="json")).decode("ascii"))
        return 1
    print(_canonical_bytes(report.model_dump(mode="json")).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
