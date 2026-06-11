from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from time import time
from typing import Any, Protocol, Self, cast

from pydantic import BaseModel, Field, field_validator, model_validator

from suite.ai_control_plane.models import TenantPolicy, UserContext
from suite.platform.runtime import is_production_environment, suite_auth_mode

DEFAULT_JWT_ISSUER = "https://issuer.collabio.local"
DEFAULT_JWT_AUDIENCE = "collabio-api"
DEFAULT_DEV_JWT_SECRET = "collabio-local-dev-jwt-secret-v1"
OIDC_RS256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class DevHeaderAuthError(ValueError):
    pass


class JwtAuthenticationError(ValueError):
    pass


class PrincipalResolutionError(ValueError):
    pass


class TenantRequestContext(BaseModel):
    user_context: UserContext
    tenant_policy: TenantPolicy


def require_dev_header_auth_allowed() -> None:
    if suite_auth_mode() != "dev":
        raise DevHeaderAuthError("Dev header tenant context requires SUITE_AUTH_MODE=dev")
    if is_production_environment():
        raise DevHeaderAuthError("Dev header tenant context is disabled in production")


class VerifiedJwtClaims(BaseModel):
    issuer: str
    subject: str
    audience: set[str] = Field(default_factory=set)
    tenant_id: str
    expires_at_epoch: int
    issued_at_epoch: int | None = None
    not_before_epoch: int | None = None
    jwt_id: str | None = None

    @field_validator("issuer", "subject", "tenant_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized


class JwtVerifier(Protocol):
    def verify(self, token: str) -> VerifiedJwtClaims: ...


class JwtReplayGuard:
    def __init__(self) -> None:
        self._seen_jti_by_issuer: dict[tuple[str, str], int] = {}

    def require_not_replayed(self, claims: VerifiedJwtClaims, *, now_epoch: int) -> None:
        if claims.jwt_id is None:
            return
        self._purge_expired(now_epoch)
        key = (claims.issuer, claims.jwt_id)
        if key in self._seen_jti_by_issuer:
            raise JwtAuthenticationError("JWT replay detected")
        self._seen_jti_by_issuer[key] = claims.expires_at_epoch

    def _purge_expired(self, now_epoch: int) -> None:
        expired = [key for key, expires_at in self._seen_jti_by_issuer.items() if expires_at <= now_epoch]
        for key in expired:
            del self._seen_jti_by_issuer[key]


class OidcIssuerConfig(BaseModel):
    issuer: str
    audiences: set[str] = Field(min_length=1)
    jwks: dict[str, Any]

    @field_validator("issuer")
    @classmethod
    def require_non_empty_issuer(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("issuer must not be empty")
        return normalized


class OidcVerifierHealth(BaseModel):
    issuer_count: int
    key_count: int
    allowed_algorithms: set[str]
    replay_guard_enabled: bool


class JwksRs256Key(BaseModel):
    key_id: str
    issuer: str
    modulus: int = Field(gt=0)
    exponent: int = Field(gt=0)


class StaticOidcJwksVerifier:
    def __init__(
        self,
        *,
        issuers: list[OidcIssuerConfig],
        now_epoch: Callable[[], float] = time,
        allowed_clock_skew_seconds: int = 30,
        replay_guard: JwtReplayGuard | None = None,
    ) -> None:
        if not issuers:
            raise JwtAuthenticationError("At least one OIDC issuer is required")
        self._audiences_by_issuer = {issuer.issuer: issuer.audiences for issuer in issuers}
        self._keys = _build_rs256_jwks_key_index(issuers)
        if not self._keys:
            raise JwtAuthenticationError("OIDC verifier requires at least one RS256 signing key")
        self.now_epoch = now_epoch
        self.allowed_clock_skew_seconds = allowed_clock_skew_seconds
        self.replay_guard = replay_guard or JwtReplayGuard()

    def verify(self, token: str) -> VerifiedJwtClaims:
        header, payload, signature = _split_compact_jwt(token)
        header_data = _decode_json_object(header, "JWT header")
        algorithm = header_data.get("alg")
        if algorithm != "RS256":
            raise JwtAuthenticationError("Unsupported JWT alg")
        key_id = _required_header_string(header_data, "kid")
        claims_data = _decode_json_object(payload, "JWT claims")
        issuer = _required_string_claim(claims_data, "iss")
        key = self._key_for(issuer=issuer, key_id=key_id)
        signing_input = f"{header}.{payload}".encode("ascii")
        if not _verify_rs256_signature(
            key=key,
            signing_input=signing_input,
            signature=_base64url_decode(signature),
        ):
            raise JwtAuthenticationError("JWT signature verification failed")

        claims = VerifiedJwtClaims(
            issuer=issuer,
            subject=_required_string_claim(claims_data, "sub"),
            audience=_audience_claim(claims_data),
            tenant_id=_required_string_claim(claims_data, "tenant_id"),
            expires_at_epoch=_required_int_claim(claims_data, "exp"),
            issued_at_epoch=_optional_int_claim(claims_data, "iat"),
            not_before_epoch=_optional_int_claim(claims_data, "nbf"),
            jwt_id=_optional_string_claim(claims_data, "jti"),
        )
        self._validate_registered_claims(claims)
        self.replay_guard.require_not_replayed(claims, now_epoch=int(self.now_epoch()))
        return claims

    def health(self) -> OidcVerifierHealth:
        return OidcVerifierHealth(
            issuer_count=len(self._audiences_by_issuer),
            key_count=len(self._keys),
            allowed_algorithms={"RS256"},
            replay_guard_enabled=True,
        )

    def _key_for(self, *, issuer: str, key_id: str) -> JwksRs256Key:
        if issuer not in self._audiences_by_issuer:
            raise JwtAuthenticationError("JWT issuer is not trusted")
        try:
            return self._keys[(issuer, key_id)]
        except KeyError as exc:
            raise JwtAuthenticationError("JWT signing key is not trusted") from exc

    def _validate_registered_claims(self, claims: VerifiedJwtClaims) -> None:
        now = int(self.now_epoch())
        trusted_audiences = self._audiences_by_issuer.get(claims.issuer)
        if trusted_audiences is None:
            raise JwtAuthenticationError("JWT issuer is not trusted")
        if claims.audience.isdisjoint(trusted_audiences):
            raise JwtAuthenticationError("JWT audience is not trusted")
        if claims.expires_at_epoch <= now - self.allowed_clock_skew_seconds:
            raise JwtAuthenticationError("JWT is expired")
        if claims.not_before_epoch is not None and claims.not_before_epoch > now + self.allowed_clock_skew_seconds:
            raise JwtAuthenticationError("JWT is not valid yet")
        if claims.issued_at_epoch is not None and claims.issued_at_epoch > now + self.allowed_clock_skew_seconds:
            raise JwtAuthenticationError("JWT issued_at is in the future")


class HmacJwtVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        secret: str,
        now_epoch: Callable[[], float] = time,
        allowed_clock_skew_seconds: int = 30,
    ) -> None:
        if not secret.strip():
            raise JwtAuthenticationError("JWT verifier secret must not be empty")
        self.issuer = issuer
        self.audience = audience
        self.secret = secret.encode("utf-8")
        self.now_epoch = now_epoch
        self.allowed_clock_skew_seconds = allowed_clock_skew_seconds

    def verify(self, token: str) -> VerifiedJwtClaims:
        header, payload, signature = _split_compact_jwt(token)
        header_payload = f"{header}.{payload}".encode("ascii")
        header_data = _decode_json_object(header, "JWT header")
        if header_data.get("typ") not in {None, "JWT"}:
            raise JwtAuthenticationError("Unsupported JWT typ")
        if header_data.get("alg") != "HS256":
            raise JwtAuthenticationError("Unsupported JWT alg")

        expected_signature = hmac.new(self.secret, header_payload, sha256).digest()
        if not hmac.compare_digest(_base64url_decode(signature), expected_signature):
            raise JwtAuthenticationError("JWT signature verification failed")

        claims = _decode_json_object(payload, "JWT claims")
        verified = VerifiedJwtClaims(
            issuer=_required_string_claim(claims, "iss"),
            subject=_required_string_claim(claims, "sub"),
            audience=_audience_claim(claims),
            tenant_id=_required_string_claim(claims, "tenant_id"),
            expires_at_epoch=_required_int_claim(claims, "exp"),
            issued_at_epoch=_optional_int_claim(claims, "iat"),
            not_before_epoch=_optional_int_claim(claims, "nbf"),
            jwt_id=_optional_string_claim(claims, "jti"),
        )
        self._validate_registered_claims(verified)
        return verified

    def _validate_registered_claims(self, claims: VerifiedJwtClaims) -> None:
        now = int(self.now_epoch())
        if claims.issuer != self.issuer:
            raise JwtAuthenticationError("JWT issuer is not trusted")
        if self.audience not in claims.audience:
            raise JwtAuthenticationError("JWT audience is not trusted")
        if claims.expires_at_epoch <= now - self.allowed_clock_skew_seconds:
            raise JwtAuthenticationError("JWT is expired")
        if claims.not_before_epoch is not None and claims.not_before_epoch > now + self.allowed_clock_skew_seconds:
            raise JwtAuthenticationError("JWT is not valid yet")
        if claims.issued_at_epoch is not None and claims.issued_at_epoch > now + self.allowed_clock_skew_seconds:
            raise JwtAuthenticationError("JWT issued_at is in the future")


class TenantMembership(BaseModel):
    tenant_id: str
    role_ids: set[str] = Field(default_factory=set)
    group_ids: set[str] = Field(default_factory=set)
    active: bool = True

    @field_validator("tenant_id")
    @classmethod
    def require_non_empty_tenant(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tenant_id must not be empty")
        return normalized


class PrincipalRecord(BaseModel):
    issuer: str
    subject: str
    user_id: str
    memberships: list[TenantMembership] = Field(default_factory=list)

    @field_validator("issuer", "subject", "user_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @model_validator(mode="after")
    def require_membership(self) -> Self:
        if not self.memberships:
            raise ValueError("principal must have at least one tenant membership")
        return self


class ObjectAclRecord(BaseModel):
    tenant_id: str
    object_id: str
    readable_user_ids: set[str] = Field(default_factory=set)
    readable_role_ids: set[str] = Field(default_factory=set)
    readable_group_ids: set[str] = Field(default_factory=set)

    @field_validator("tenant_id", "object_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized


class InMemoryPrincipalDirectory:
    def __init__(self, *, principals: list[PrincipalRecord], object_acls: list[ObjectAclRecord]) -> None:
        self._principals = {(principal.issuer, principal.subject): principal for principal in principals}
        self._object_acls = object_acls

    @classmethod
    def default(cls) -> InMemoryPrincipalDirectory:
        issuer = os.getenv("SUITE_JWT_ISSUER", DEFAULT_JWT_ISSUER)
        return cls(
            principals=[
                PrincipalRecord(
                    issuer=issuer,
                    subject="user-demo",
                    user_id="user-demo",
                    memberships=[
                        TenantMembership(
                            tenant_id="tenant-demo",
                            role_ids={"knowledge-worker"},
                            group_ids={"team-demo"},
                        )
                    ],
                ),
                PrincipalRecord(
                    issuer=issuer,
                    subject="tenant-admin-demo",
                    user_id="tenant-admin-demo",
                    memberships=[
                        TenantMembership(
                            tenant_id="tenant-demo",
                            role_ids={"tenant-admin"},
                            group_ids={"tenant-admins"},
                        )
                    ],
                ),
                PrincipalRecord(
                    issuer=issuer,
                    subject="security-admin-demo",
                    user_id="security-admin-demo",
                    memberships=[
                        TenantMembership(
                            tenant_id="tenant-demo",
                            role_ids={"security-admin"},
                            group_ids={"security-admins"},
                        )
                    ],
                ),
            ],
            object_acls=[
                ObjectAclRecord(
                    tenant_id="tenant-demo",
                    object_id="doc-1",
                    readable_group_ids={"team-demo"},
                    readable_role_ids={"tenant-admin", "security-admin"},
                ),
                ObjectAclRecord(
                    tenant_id="tenant-demo",
                    object_id="mail-1",
                    readable_group_ids={"team-demo"},
                    readable_role_ids={"tenant-admin", "security-admin"},
                ),
                ObjectAclRecord(
                    tenant_id="tenant-demo",
                    object_id="secret-1",
                    readable_group_ids={"payroll"},
                    readable_role_ids={"security-admin"},
                ),
            ],
        )

    def principal_for_claims(self, claims: VerifiedJwtClaims) -> PrincipalRecord:
        try:
            return self._principals[(claims.issuer, claims.subject)]
        except KeyError as exc:
            raise PrincipalResolutionError("Principal is not registered") from exc

    def tenant_membership(self, principal: PrincipalRecord, tenant_id: str) -> TenantMembership:
        for membership in principal.memberships:
            if membership.tenant_id == tenant_id and membership.active:
                return membership
        raise PrincipalResolutionError("Principal is not an active member of the requested tenant")

    def readable_object_ids(self, *, tenant_id: str, user_id: str, role_ids: set[str], group_ids: set[str]) -> set[str]:
        readable: set[str] = set()
        for acl in self._object_acls:
            if acl.tenant_id != tenant_id:
                continue
            if (
                user_id in acl.readable_user_ids
                or not role_ids.isdisjoint(acl.readable_role_ids)
                or not group_ids.isdisjoint(acl.readable_group_ids)
            ):
                readable.add(acl.object_id)
        return readable


class JwtPrincipalResolver:
    def __init__(self, *, verifier: JwtVerifier, directory: InMemoryPrincipalDirectory) -> None:
        self.verifier = verifier
        self.directory = directory

    def resolve_authorization_header(self, authorization: str | None) -> UserContext:
        token = _extract_bearer_token(authorization)
        claims = self.verifier.verify(token)
        principal = self.directory.principal_for_claims(claims)
        membership = self.directory.tenant_membership(principal, claims.tenant_id)
        readable_object_ids = self.directory.readable_object_ids(
            tenant_id=claims.tenant_id,
            user_id=principal.user_id,
            role_ids=membership.role_ids,
            group_ids=membership.group_ids,
        )
        return UserContext(
            user_id=principal.user_id,
            tenant_id=claims.tenant_id,
            role_ids=set(membership.role_ids),
            readable_object_ids=readable_object_ids,
        )


def build_default_principal_resolver() -> JwtPrincipalResolver:
    auth_mode = suite_auth_mode()
    verifier: JwtVerifier
    if auth_mode == "oidc":
        verifier = StaticOidcJwksVerifier(issuers=_load_oidc_issuer_configs_from_env())
    else:
        issuer = os.getenv("SUITE_JWT_ISSUER", DEFAULT_JWT_ISSUER)
        audience = os.getenv("SUITE_JWT_AUDIENCE", DEFAULT_JWT_AUDIENCE)
        secret = os.getenv("SUITE_JWT_HS256_SECRET")
        if not secret and is_production_environment() and auth_mode == "jwt":
            raise JwtAuthenticationError("SUITE_JWT_HS256_SECRET is required for signed JWT auth")
        verifier = HmacJwtVerifier(
            issuer=issuer,
            audience=audience,
            secret=secret or DEFAULT_DEV_JWT_SECRET,
        )
    return JwtPrincipalResolver(
        verifier=verifier,
        directory=InMemoryPrincipalDirectory.default(),
    )


def _load_oidc_issuer_configs_from_env() -> list[OidcIssuerConfig]:
    config_json = os.getenv("SUITE_OIDC_ISSUERS_JSON")
    if config_json:
        try:
            raw_config = json.loads(config_json)
        except json.JSONDecodeError as exc:
            raise JwtAuthenticationError("SUITE_OIDC_ISSUERS_JSON must be valid JSON") from exc
        if not isinstance(raw_config, list):
            raise JwtAuthenticationError("SUITE_OIDC_ISSUERS_JSON must be a JSON array")
        return [OidcIssuerConfig.model_validate(entry) for entry in raw_config]

    issuer = os.getenv("SUITE_OIDC_ISSUER", "").strip()
    audience = os.getenv("SUITE_OIDC_AUDIENCE", DEFAULT_JWT_AUDIENCE).strip()
    jwks_json = os.getenv("SUITE_OIDC_JWKS_JSON")
    if not issuer or not jwks_json:
        raise JwtAuthenticationError("OIDC auth requires SUITE_OIDC_ISSUER and SUITE_OIDC_JWKS_JSON")
    try:
        jwks = json.loads(jwks_json)
    except json.JSONDecodeError as exc:
        raise JwtAuthenticationError("SUITE_OIDC_JWKS_JSON must be valid JSON") from exc
    return [OidcIssuerConfig(issuer=issuer, audiences={audience}, jwks=jwks)]


def _build_rs256_jwks_key_index(issuers: list[OidcIssuerConfig]) -> dict[tuple[str, str], JwksRs256Key]:
    keys: dict[tuple[str, str], JwksRs256Key] = {}
    for issuer in issuers:
        raw_keys = issuer.jwks.get("keys")
        if not isinstance(raw_keys, list):
            raise JwtAuthenticationError("JWKS must contain a keys array")
        for raw_key in raw_keys:
            if not isinstance(raw_key, dict):
                raise JwtAuthenticationError("JWKS key must be an object")
            if raw_key.get("kty") != "RSA" or raw_key.get("alg") not in {None, "RS256"}:
                continue
            if raw_key.get("use") not in {None, "sig"}:
                continue
            key_id = _required_header_string(raw_key, "kid")
            modulus_value = _required_header_string(raw_key, "n")
            exponent_value = _required_header_string(raw_key, "e")
            key = JwksRs256Key(
                key_id=key_id,
                issuer=issuer.issuer,
                modulus=_base64url_uint(modulus_value),
                exponent=_base64url_uint(exponent_value),
            )
            key_index = (issuer.issuer, key.key_id)
            if key_index in keys:
                raise JwtAuthenticationError("Duplicate JWKS key id for issuer")
            keys[key_index] = key
    return keys


def _split_compact_jwt(token: str) -> tuple[str, str, str]:
    parts = token.split(".")
    if len(parts) != 3 or any(not part for part in parts):
        raise JwtAuthenticationError("JWT must use compact serialization")
    return parts[0], parts[1], parts[2]


def _extract_bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise JwtAuthenticationError("Bearer authorization header required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise JwtAuthenticationError("Bearer authorization header required")
    return token.strip()


def _base64url_decode(value: str) -> bytes:
    try:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, binascii.Error) as exc:
        raise JwtAuthenticationError("Invalid base64url JWT value") from exc


def _base64url_uint(value: str) -> int:
    decoded = _base64url_decode(value)
    if not decoded:
        raise JwtAuthenticationError("Invalid empty JWKS integer")
    return int.from_bytes(decoded, "big")


def _decode_json_object(value: str, label: str) -> dict[str, Any]:
    try:
        decoded = json.loads(_base64url_decode(value))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JwtAuthenticationError(f"Invalid {label}") from exc
    if not isinstance(decoded, dict):
        raise JwtAuthenticationError(f"{label} must be a JSON object")
    return cast(dict[str, Any], decoded)


def _required_header_string(header: dict[str, Any], name: str) -> str:
    value = header.get(name)
    if not isinstance(value, str) or not value.strip():
        raise JwtAuthenticationError(f"JWT header {name} is required")
    return value


def _required_string_claim(claims: dict[str, Any], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip():
        raise JwtAuthenticationError(f"JWT claim {name} is required")
    return value


def _optional_string_claim(claims: dict[str, Any], name: str) -> str | None:
    value = claims.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise JwtAuthenticationError(f"JWT claim {name} must be a string")
    return value


def _required_int_claim(claims: dict[str, Any], name: str) -> int:
    value = claims.get(name)
    if not isinstance(value, int):
        raise JwtAuthenticationError(f"JWT claim {name} is required")
    return value


def _optional_int_claim(claims: dict[str, Any], name: str) -> int | None:
    value = claims.get(name)
    if value is None:
        return None
    if not isinstance(value, int):
        raise JwtAuthenticationError(f"JWT claim {name} must be an integer")
    return value


def _audience_claim(claims: dict[str, Any]) -> set[str]:
    value = claims.get("aud")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value):
        return set(value)
    raise JwtAuthenticationError("JWT claim aud is required")


def _verify_rs256_signature(*, key: JwksRs256Key, signing_input: bytes, signature: bytes) -> bool:
    modulus_length = (key.modulus.bit_length() + 7) // 8
    if len(signature) != modulus_length:
        return False
    signature_integer = int.from_bytes(signature, "big")
    message_integer = pow(signature_integer, key.exponent, key.modulus)
    encoded_message = message_integer.to_bytes(modulus_length, "big")
    expected_digest_info = OIDC_RS256_DIGEST_INFO_PREFIX + sha256(signing_input).digest()
    return _pkcs1_v15_digest_info_matches(encoded_message, expected_digest_info)


def _pkcs1_v15_digest_info_matches(encoded_message: bytes, expected_digest_info: bytes) -> bool:
    minimum_length = 3 + 8 + len(expected_digest_info)
    if len(encoded_message) < minimum_length:
        return False
    if not encoded_message.startswith(b"\x00\x01"):
        return False
    separator_index = encoded_message.find(b"\x00", 2)
    if separator_index < 0:
        return False
    padding = encoded_message[2:separator_index]
    if len(padding) < 8 or any(byte != 0xFF for byte in padding):
        return False
    return hmac.compare_digest(encoded_message[separator_index + 1 :], expected_digest_info)


def utc_now_epoch() -> int:
    return int(datetime.now(tz=UTC).timestamp())
