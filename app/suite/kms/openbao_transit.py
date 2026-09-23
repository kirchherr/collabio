from __future__ import annotations

import base64
import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol, Self, cast
from urllib.parse import quote, urlsplit

import httpx
from cryptography.hazmat.primitives import serialization

from suite.kms.adapter import KmsPolicyViolation
from suite.kms.signing import (
    AuditCheckpointSignature,
    AuditSignatureError,
    AuditSigningAlgorithm,
    AuditSigningKeyReference,
    AuditSigningProviderInspection,
)

OPENBAO_PROVIDER_KEY_PATTERN = re.compile(
    r"^openbao-transit://([a-z0-9][a-z0-9_-]{0,127})/([a-zA-Z0-9][a-zA-Z0-9_.-]{0,255})/v([1-9][0-9]*)$"
)
MAX_OPENBAO_RESPONSE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class OpenBaoTransitKeyReference:
    mount_path: str
    key_name: str
    key_version: int

    @property
    def canonical_ref(self) -> str:
        return f"openbao-transit://{self.mount_path}/{self.key_name}/v{self.key_version}"

    @classmethod
    def parse(cls, value: str) -> Self:
        normalized = value.strip()
        match = OPENBAO_PROVIDER_KEY_PATTERN.fullmatch(normalized)
        if match is None:
            raise KmsPolicyViolation(
                "OpenBao provider key reference must be openbao-transit://<mount>/<key-name>/v<version>"
            )
        reference = cls(
            mount_path=match.group(1),
            key_name=match.group(2),
            key_version=int(match.group(3)),
        )
        if reference.canonical_ref != normalized:
            raise KmsPolicyViolation("OpenBao provider key reference must be canonical")
        return reference


class OpenBaoTransitClient(Protocol):
    def read_key(self, *, mount_path: str, key_name: str) -> Mapping[str, Any]: ...

    def sign_digest(
        self,
        *,
        mount_path: str,
        key_name: str,
        key_version: int,
        digest_base64: str,
        signature_algorithm: str | None,
    ) -> Mapping[str, Any]: ...

    def verify_digest(
        self,
        *,
        mount_path: str,
        key_name: str,
        digest_base64: str,
        signature: str,
        signature_algorithm: str | None,
    ) -> Mapping[str, Any]: ...


class OpenBaoTransitHttpClient:
    def __init__(
        self,
        *,
        address: str,
        token: str,
        namespace: str | None = None,
        tls_ca_file: str | None = None,
        client_cert_file: str | None = None,
        client_key_file: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        normalized_address = _require_https_address(address)
        normalized_token = token.strip()
        if not normalized_token or len(normalized_token) > 16_384:
            raise KmsPolicyViolation("OpenBao token is missing or too large")
        if bool(client_cert_file) != bool(client_key_file):
            raise KmsPolicyViolation("OpenBao mTLS requires both client certificate and key files")
        headers = {"X-Vault-Token": normalized_token}
        if namespace and namespace.strip():
            headers["X-Vault-Namespace"] = namespace.strip()
        client_options: dict[str, Any] = {
            "base_url": normalized_address,
            "headers": headers,
            "timeout": timeout_seconds,
            "verify": tls_ca_file or True,
            "follow_redirects": False,
        }
        if client_cert_file and client_key_file:
            client_options["cert"] = (client_cert_file, client_key_file)
        self._client = httpx.Client(**client_options)

    def read_key(self, *, mount_path: str, key_name: str) -> Mapping[str, Any]:
        return self._request("GET", _key_path(mount_path=mount_path, key_name=key_name))

    def sign_digest(
        self,
        *,
        mount_path: str,
        key_name: str,
        key_version: int,
        digest_base64: str,
        signature_algorithm: str | None,
    ) -> Mapping[str, Any]:
        payload: dict[str, object] = {
            "input": digest_base64,
            "prehashed": True,
            "key_version": key_version,
        }
        if signature_algorithm is not None:
            payload["signature_algorithm"] = signature_algorithm
            payload["salt_length"] = "hash"
        return self._request(
            "POST",
            _operation_path(mount_path=mount_path, operation="sign", key_name=key_name),
            payload=payload,
        )

    def verify_digest(
        self,
        *,
        mount_path: str,
        key_name: str,
        digest_base64: str,
        signature: str,
        signature_algorithm: str | None,
    ) -> Mapping[str, Any]:
        payload: dict[str, object] = {
            "input": digest_base64,
            "prehashed": True,
            "signature": signature,
        }
        if signature_algorithm is not None:
            payload["signature_algorithm"] = signature_algorithm
            payload["salt_length"] = "hash"
        return self._request(
            "POST",
            _operation_path(mount_path=mount_path, operation="verify", key_name=key_name),
            payload=payload,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any]:
        try:
            response = self._client.request(method, path, json=payload)
        except httpx.HTTPError as exc:
            raise AuditSignatureError("OpenBao Transit request failed") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise AuditSignatureError("OpenBao Transit request was rejected")
        if len(response.content) > MAX_OPENBAO_RESPONSE_BYTES:
            raise AuditSignatureError("OpenBao Transit response exceeded the size limit")
        try:
            decoded = response.json()
        except ValueError as exc:
            raise AuditSignatureError("OpenBao Transit returned invalid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise AuditSignatureError("OpenBao Transit returned an invalid response")
        return cast(Mapping[str, Any], decoded)


class OpenBaoTransitSigningKeyInspector:
    def __init__(self, *, client: OpenBaoTransitClient) -> None:
        self.client = client

    def inspect_provider_key(self, *, provider_key_id: str) -> AuditSigningProviderInspection:
        key_ref = OpenBaoTransitKeyReference.parse(provider_key_id)
        try:
            response = self.client.read_key(mount_path=key_ref.mount_path, key_name=key_ref.key_name)
        except AuditSignatureError:
            raise
        except Exception as exc:
            raise AuditSignatureError("OpenBao Transit key inspection failed") from exc
        data = _response_data(response)
        if data.get("deletion_allowed") is not False:
            raise AuditSignatureError("OpenBao Transit signing key must forbid deletion")
        key_type = str(data.get("type", "")).strip()
        if key_type not in {"ecdsa-p256", "rsa-2048", "rsa-3072", "rsa-4096"}:
            raise AuditSignatureError("OpenBao Transit key type is not approved for audit signing")
        key_versions = data.get("keys")
        if not isinstance(key_versions, Mapping):
            raise AuditSignatureError("OpenBao Transit key versions are missing")
        version = key_versions.get(str(key_ref.key_version)) or key_versions.get(key_ref.key_version)
        if not isinstance(version, Mapping):
            raise AuditSignatureError("OpenBao Transit signing key version is missing")
        public_key_pem = str(version.get("public_key", "")).strip()
        if not public_key_pem:
            raise AuditSignatureError("OpenBao Transit public key is missing")
        try:
            public_key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
            public_key_der = public_key.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        except (TypeError, ValueError) as exc:
            raise AuditSignatureError("OpenBao Transit public key is invalid") from exc
        return AuditSigningProviderInspection(
            provider_key_id=key_ref.canonical_ref,
            key_type=key_type,
            key_version=key_ref.key_version,
            public_key_der=public_key_der,
            request_id=_request_id(response),
        )


class OpenBaoTransitAuditCheckpointSigner(OpenBaoTransitSigningKeyInspector):
    def __init__(
        self,
        *,
        client: OpenBaoTransitClient,
        kms_key_ref: str,
        provider_key_id: str,
        signing_algorithm: AuditSigningAlgorithm = AuditSigningAlgorithm.ECDSA_SHA_256,
        provider_profile: str = "openbao-transit",
    ) -> None:
        super().__init__(client=client)
        self.key_ref = AuditSigningKeyReference.parse(kms_key_ref)
        self.provider_key_ref = OpenBaoTransitKeyReference.parse(provider_key_id)
        if self.provider_key_ref.key_version != self.key_ref.key_version:
            raise KmsPolicyViolation("OpenBao and logical audit signing key versions must match")
        if not provider_profile.strip():
            raise KmsPolicyViolation("provider_profile must not be empty")
        self.signing_algorithm = signing_algorithm
        self.provider_profile = provider_profile.strip()

    def sign_digest(
        self,
        *,
        tenant_id: str,
        digest: bytes,
        signed_at_utc: str,
    ) -> AuditCheckpointSignature:
        if tenant_id != self.key_ref.tenant_id:
            raise KmsPolicyViolation("audit signing key tenant does not match request tenant")
        if len(digest) != sha256().digest_size:
            raise AuditSignatureError("audit checkpoint signer requires a SHA-256 digest")
        inspection = self.inspect_provider_key(provider_key_id=self.provider_key_ref.canonical_ref)
        _require_algorithm_key_type(algorithm=self.signing_algorithm, key_type=inspection.key_type)
        digest_base64 = base64.b64encode(digest).decode("ascii")
        signature_algorithm = "pss" if self.signing_algorithm is AuditSigningAlgorithm.RSASSA_PSS_SHA_256 else None
        try:
            sign_response = self.client.sign_digest(
                mount_path=self.provider_key_ref.mount_path,
                key_name=self.provider_key_ref.key_name,
                key_version=self.provider_key_ref.key_version,
                digest_base64=digest_base64,
                signature_algorithm=signature_algorithm,
            )
        except AuditSignatureError:
            raise
        except Exception as exc:
            raise AuditSignatureError("OpenBao Transit signing failed") from exc
        signature_text = str(_response_data(sign_response).get("signature", "")).strip()
        signature = _decode_signature(signature_text, expected_version=self.provider_key_ref.key_version)
        try:
            verify_response = self.client.verify_digest(
                mount_path=self.provider_key_ref.mount_path,
                key_name=self.provider_key_ref.key_name,
                digest_base64=digest_base64,
                signature=signature_text,
                signature_algorithm=signature_algorithm,
            )
        except AuditSignatureError:
            raise
        except Exception as exc:
            raise AuditSignatureError("OpenBao Transit verification failed") from exc
        if _response_data(verify_response).get("valid") is not True:
            raise AuditSignatureError("OpenBao Transit did not verify the generated signature")
        return AuditCheckpointSignature(
            tenant_id=tenant_id,
            signed_digest="sha256:" + digest.hex(),
            signing_algorithm=self.signing_algorithm,
            kms_key_ref=self.key_ref.canonical_ref,
            kms_key_version=self.key_ref.key_version,
            provider_profile=self.provider_profile,
            provider_key_id=inspection.provider_key_id,
            public_key_der_base64=base64.b64encode(inspection.public_key_der).decode("ascii"),
            public_key_sha256=_sha256_ref(inspection.public_key_der),
            signature_base64=base64.b64encode(signature).decode("ascii"),
            signature_sha256=_sha256_ref(signature),
            signed_at_utc=signed_at_utc,
            provider_sign_request_id=_request_id(sign_response),
            provider_verify_request_id=_request_id(verify_response),
            provider_verified=True,
        )


def _require_https_address(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise KmsPolicyViolation("OpenBao address must be an HTTPS origin without credentials or path")
    return normalized


def _key_path(*, mount_path: str, key_name: str) -> str:
    return f"/v1/{quote(mount_path, safe='')}/keys/{quote(key_name, safe='')}"


def _operation_path(*, mount_path: str, operation: str, key_name: str) -> str:
    return f"/v1/{quote(mount_path, safe='')}/{operation}/{quote(key_name, safe='')}/sha2-256"


def _response_data(response: Mapping[str, Any]) -> Mapping[str, Any]:
    data = response.get("data")
    if not isinstance(data, Mapping):
        raise AuditSignatureError("OpenBao Transit response did not contain data")
    return data


def _request_id(response: Mapping[str, Any]) -> str:
    request_id = str(response.get("request_id", "")).strip()
    if not request_id:
        raise AuditSignatureError("OpenBao Transit response did not include a request ID")
    return request_id


def _decode_signature(value: str, *, expected_version: int) -> bytes:
    parts = value.split(":", maxsplit=2)
    if len(parts) != 3 or parts[0] != "vault" or parts[1] != f"v{expected_version}":
        raise AuditSignatureError("OpenBao Transit returned an unexpected signature envelope")
    try:
        signature = base64.b64decode(parts[2], validate=True)
    except ValueError as exc:
        raise AuditSignatureError("OpenBao Transit returned an invalid signature") from exc
    if not signature or base64.b64encode(signature).decode("ascii") != parts[2]:
        raise AuditSignatureError("OpenBao Transit returned an invalid signature")
    return signature


def _require_algorithm_key_type(*, algorithm: AuditSigningAlgorithm, key_type: str) -> None:
    if algorithm is AuditSigningAlgorithm.ECDSA_SHA_256 and key_type != "ecdsa-p256":
        raise AuditSignatureError("OpenBao Transit ECDSA signing requires an ecdsa-p256 key")
    if algorithm is AuditSigningAlgorithm.RSASSA_PSS_SHA_256 and key_type not in {
        "rsa-2048",
        "rsa-3072",
        "rsa-4096",
    }:
        raise AuditSignatureError("OpenBao Transit RSA-PSS signing requires an approved RSA key")


def _sha256_ref(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()
