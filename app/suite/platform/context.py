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
    issuer = os.getenv("SUITE_JWT_ISSUER", DEFAULT_JWT_ISSUER)
    audience = os.getenv("SUITE_JWT_AUDIENCE", DEFAULT_JWT_AUDIENCE)
    secret = os.getenv("SUITE_JWT_HS256_SECRET")
    if not secret and is_production_environment() and suite_auth_mode() in {"jwt", "oidc"}:
        raise JwtAuthenticationError("SUITE_JWT_HS256_SECRET is required for signed JWT auth")
    return JwtPrincipalResolver(
        verifier=HmacJwtVerifier(
            issuer=issuer,
            audience=audience,
            secret=secret or DEFAULT_DEV_JWT_SECRET,
        ),
        directory=InMemoryPrincipalDirectory.default(),
    )


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


def _decode_json_object(value: str, label: str) -> dict[str, Any]:
    try:
        decoded = json.loads(_base64url_decode(value))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JwtAuthenticationError(f"Invalid {label}") from exc
    if not isinstance(decoded, dict):
        raise JwtAuthenticationError(f"{label} must be a JSON object")
    return cast(dict[str, Any], decoded)


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


def utc_now_epoch() -> int:
    return int(datetime.now(tz=UTC).timestamp())
