import base64
import hmac
import json
from hashlib import sha256
from typing import Any

import pytest

from suite.platform.context import (
    DEFAULT_DEV_JWT_SECRET,
    DEFAULT_JWT_AUDIENCE,
    DEFAULT_JWT_ISSUER,
    HmacJwtVerifier,
    InMemoryPrincipalDirectory,
    JwtAuthenticationError,
    JwtPrincipalResolver,
    PrincipalResolutionError,
)


def signed_jwt(claims: dict[str, Any], *, secret: str = DEFAULT_DEV_JWT_SECRET) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    encoded_header = base64url_json(header)
    encoded_payload = base64url_json(claims)
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{base64url_bytes(signature)}"


def base64url_json(payload: dict[str, Any]) -> str:
    return base64url_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def base64url_bytes(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def verifier() -> HmacJwtVerifier:
    return HmacJwtVerifier(
        issuer=DEFAULT_JWT_ISSUER,
        audience=DEFAULT_JWT_AUDIENCE,
        secret=DEFAULT_DEV_JWT_SECRET,
        now_epoch=lambda: 1_000,
    )


def claims(*, subject: str = "user-demo", tenant_id: str = "tenant-demo", exp: int = 2_000) -> dict[str, Any]:
    return {
        "iss": DEFAULT_JWT_ISSUER,
        "aud": DEFAULT_JWT_AUDIENCE,
        "sub": subject,
        "tenant_id": tenant_id,
        "iat": 900,
        "exp": exp,
    }


def test_hmac_jwt_verifier_accepts_signed_oidc_style_claims() -> None:
    verified = verifier().verify(signed_jwt(claims()))

    assert verified.issuer == DEFAULT_JWT_ISSUER
    assert verified.subject == "user-demo"
    assert verified.tenant_id == "tenant-demo"
    assert verified.audience == {DEFAULT_JWT_AUDIENCE}


def test_hmac_jwt_verifier_rejects_bad_signature_and_expired_token() -> None:
    valid = signed_jwt(claims())
    header, _payload, signature = valid.split(".")
    tampered = f"{header}.{base64url_json({**claims(), 'sub': 'tenant-admin-demo'})}.{signature}"

    with pytest.raises(JwtAuthenticationError, match="signature"):
        verifier().verify(tampered)

    with pytest.raises(JwtAuthenticationError, match="expired"):
        verifier().verify(signed_jwt(claims(exp=900)))


def test_jwt_principal_resolver_uses_server_side_membership_and_acl() -> None:
    resolver = JwtPrincipalResolver(verifier=verifier(), directory=InMemoryPrincipalDirectory.default())
    token = signed_jwt(
        {
            **claims(),
            "roles": ["tenant-admin"],
            "readable_object_ids": ["secret-1"],
        }
    )

    user_context = resolver.resolve_authorization_header(f"Bearer {token}")

    assert user_context.user_id == "user-demo"
    assert user_context.tenant_id == "tenant-demo"
    assert user_context.role_ids == {"knowledge-worker"}
    assert user_context.readable_object_ids == {"doc-1", "mail-1"}


def test_jwt_principal_resolver_requires_registered_tenant_membership() -> None:
    resolver = JwtPrincipalResolver(verifier=verifier(), directory=InMemoryPrincipalDirectory.default())
    token = signed_jwt(claims(tenant_id="tenant-unknown"))

    with pytest.raises(PrincipalResolutionError, match="active member"):
        resolver.resolve_authorization_header(f"Bearer {token}")
