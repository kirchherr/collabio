import base64
import hmac
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from suite.platform.context import (
    DEFAULT_DEV_JWT_SECRET,
    DEFAULT_JWT_AUDIENCE,
    DEFAULT_JWT_ISSUER,
    OIDC_RS256_DIGEST_INFO_PREFIX,
    DynamicOidcJwksVerifier,
    HmacJwtVerifier,
    InMemoryPrincipalDirectory,
    JsonFileJwtReplayStore,
    JwtAuthenticationError,
    JwtPrincipalResolver,
    JwtReplayGuard,
    OidcDiscoveryIssuerConfig,
    OidcIssuerConfig,
    OidcOutagePolicy,
    PrincipalResolutionError,
    StaticOidcJwksVerifier,
    VerifiedJwtClaims,
)

OIDC_TEST_KID = "oidc-test-key-1"
OIDC_TEST_ROTATED_KID = "oidc-test-key-2"
OIDC_TEST_MODULUS_B64 = (
    "6N98c1QOYV0JN1K2trYRH9HGm_l4DNgH5yjzizhV1soJnBQkZcy4Vf7L9HZefziozcWP8j8c-29zrlhQaXDfAw"
    "cpMCHnL8abWAzbuukR6jQiVvRGAno3VKuhYsX8JtMQz5fI1taQ2qRL11so5W9o0ct_r3KkgQNLYrEe4RmX"
    "osfCzfRIlsiY2t0H7GdhcROsY4YqXxFKN1hHOndzAPl6NmBD9wVzqbKRB3EFJuSPMzcZ6ksttdzXcZtz5pgTL"
    "kv084ZvvLkMENKQCHv_I77u1LpY7kEyxq7QpyJ7FRAYkvwCJJT_V3WXn_LpaD9Lljyhkgaj3rwsS-Vgk0B7t2Eynw"
)
OIDC_TEST_EXPONENT_B64 = "AQAB"
OIDC_TEST_PRIVATE_EXPONENT_B64 = (
    "Nt82UWyMiOelvMn6MLpc9Zz2Chmx7oDW9-Kf5H2tSFPKCON8IhqnkufbgiqEIMEmkXoMbZ3ug9aisQGxTO8iNX"
    "HyBBvxAEJxp0E8Y2H47TFEqC2d84Z91C8u83nIbRON4gSXd_wOHN7a2g9qZwml7s1fNGW0mou-ry4iIxNnNh0d"
    "1hz9kNwxP8v0XjkBt3BXCUaRyJxCc8WrvquuJM15TzOvUlTcgMgzVjwEvN28q9T-NOBhWRV-wDTBtpKuyMXxn"
    "XBIlF6pOOa8PjzKJz4YzZBLs-lyYACVZtCBOvNYMoLK9Pw_4UMlrrxSnAR3pLT1TEbkP-_4JFN7mwHqiBtFFQ"
)
OIDC_DISCOVERY_URL = "https://issuer.collabio.local/.well-known/openid-configuration"
OIDC_JWKS_URL = "https://issuer.collabio.local/jwks.json"


class MutableClock:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> float:
        return float(self.value)


class FakeJsonFetcher:
    def __init__(self, responses: dict[str, list[dict[str, Any] | Exception]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def fetch_json(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        if url not in self.responses:
            raise JwtAuthenticationError(f"unexpected fetch url: {url}")
        queue = self.responses[url]
        response = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(response, Exception):
            raise response
        return response


def signed_jwt(claims: dict[str, Any], *, secret: str = DEFAULT_DEV_JWT_SECRET) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    encoded_header = base64url_json(header)
    encoded_payload = base64url_json(claims)
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{base64url_bytes(signature)}"


def signed_rs256_jwt(claims: dict[str, Any], *, kid: str = OIDC_TEST_KID) -> str:
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    encoded_header = base64url_json(header)
    encoded_payload = base64url_json(claims)
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    modulus = base64url_uint(OIDC_TEST_MODULUS_B64)
    private_exponent = base64url_uint(OIDC_TEST_PRIVATE_EXPONENT_B64)
    modulus_length = (modulus.bit_length() + 7) // 8
    digest_info = OIDC_RS256_DIGEST_INFO_PREFIX + sha256(signing_input).digest()
    padding_length = modulus_length - len(digest_info) - 3
    encoded_message = b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded_message, "big"), private_exponent, modulus).to_bytes(modulus_length, "big")
    return f"{encoded_header}.{encoded_payload}.{base64url_bytes(signature)}"


def base64url_json(payload: dict[str, Any]) -> str:
    return base64url_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def base64url_bytes(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def base64url_uint(value: str) -> int:
    padding = "=" * (-len(value) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(value + padding), "big")


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


def oidc_verifier() -> StaticOidcJwksVerifier:
    return StaticOidcJwksVerifier(
        issuers=[
            OidcIssuerConfig(
                issuer=DEFAULT_JWT_ISSUER,
                audiences={DEFAULT_JWT_AUDIENCE},
                jwks={
                    "keys": [
                        {
                            "kty": "RSA",
                            "kid": OIDC_TEST_KID,
                            "alg": "RS256",
                            "use": "sig",
                            "n": OIDC_TEST_MODULUS_B64,
                            "e": OIDC_TEST_EXPONENT_B64,
                        },
                        {
                            "kty": "RSA",
                            "kid": OIDC_TEST_ROTATED_KID,
                            "alg": "RS256",
                            "use": "sig",
                            "n": OIDC_TEST_MODULUS_B64,
                            "e": OIDC_TEST_EXPONENT_B64,
                        },
                    ]
                },
            )
        ],
        now_epoch=lambda: 1_000,
    )


def oidc_discovery_config(
    *,
    refresh_interval_seconds: int = 10,
    stale_grace_seconds: int = 30,
    outage_policy: OidcOutagePolicy = OidcOutagePolicy.FAIL_CLOSED,
) -> OidcDiscoveryIssuerConfig:
    return OidcDiscoveryIssuerConfig(
        issuer=DEFAULT_JWT_ISSUER,
        audiences={DEFAULT_JWT_AUDIENCE},
        discovery_url=OIDC_DISCOVERY_URL,
        refresh_interval_seconds=refresh_interval_seconds,
        stale_grace_seconds=stale_grace_seconds,
        outage_policy=outage_policy,
    )


def oidc_discovery_document() -> dict[str, Any]:
    return {
        "issuer": DEFAULT_JWT_ISSUER,
        "jwks_uri": OIDC_JWKS_URL,
        "id_token_signing_alg_values_supported": ["RS256"],
    }


def oidc_jwks(*, include_rotated_key: bool = False) -> dict[str, Any]:
    keys = [
        {
            "kty": "RSA",
            "kid": OIDC_TEST_KID,
            "alg": "RS256",
            "use": "sig",
            "n": OIDC_TEST_MODULUS_B64,
            "e": OIDC_TEST_EXPONENT_B64,
        }
    ]
    if include_rotated_key:
        keys.append(
            {
                "kty": "RSA",
                "kid": OIDC_TEST_ROTATED_KID,
                "alg": "RS256",
                "use": "sig",
                "n": OIDC_TEST_MODULUS_B64,
                "e": OIDC_TEST_EXPONENT_B64,
            }
        )
    return {"keys": keys}


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


def test_static_oidc_jwks_verifier_accepts_rs256_signed_token_and_reports_health() -> None:
    token = signed_rs256_jwt({**claims(), "jti": "jwt-1"})
    rotated_token = signed_rs256_jwt({**claims(), "jti": "jwt-2"}, kid=OIDC_TEST_ROTATED_KID)
    verifier = oidc_verifier()

    verified = verifier.verify(token)
    rotated_verified = verifier.verify(rotated_token)
    health = verifier.health()

    assert verified.subject == "user-demo"
    assert verified.jwt_id == "jwt-1"
    assert rotated_verified.jwt_id == "jwt-2"
    assert health.issuer_count == 1
    assert health.key_count == 2
    assert health.allowed_algorithms == {"RS256"}
    assert health.replay_guard_enabled is True


def test_static_oidc_jwks_verifier_rejects_replay_untrusted_audience_and_unknown_key() -> None:
    verifier = oidc_verifier()
    replayed = signed_rs256_jwt({**claims(), "jti": "jwt-replay"})
    verifier.verify(replayed)

    with pytest.raises(JwtAuthenticationError, match="replay"):
        verifier.verify(replayed)

    with pytest.raises(JwtAuthenticationError, match="audience"):
        verifier.verify(signed_rs256_jwt({**claims(), "aud": "other-api", "jti": "jwt-aud"}))

    with pytest.raises(JwtAuthenticationError, match="signing key"):
        verifier.verify(signed_rs256_jwt({**claims(), "jti": "jwt-kid"}, kid="unknown-key"))


def test_dynamic_oidc_verifier_discovers_jwks_and_refreshes_for_key_rotation() -> None:
    clock = MutableClock(1_000)
    fetcher = FakeJsonFetcher(
        {
            OIDC_DISCOVERY_URL: [oidc_discovery_document(), oidc_discovery_document()],
            OIDC_JWKS_URL: [oidc_jwks(), oidc_jwks(include_rotated_key=True)],
        }
    )
    verifier = DynamicOidcJwksVerifier(
        issuers=[oidc_discovery_config()],
        fetcher=fetcher,
        now_epoch=clock,
    )

    first = verifier.verify(signed_rs256_jwt({**claims(exp=2_000), "jti": "dynamic-1"}))
    rotated = verifier.verify(signed_rs256_jwt({**claims(exp=2_000), "jti": "dynamic-2"}, kid=OIDC_TEST_ROTATED_KID))
    health = verifier.health()

    assert first.jwt_id == "dynamic-1"
    assert rotated.jwt_id == "dynamic-2"
    assert fetcher.calls == [OIDC_DISCOVERY_URL, OIDC_JWKS_URL, OIDC_DISCOVERY_URL, OIDC_JWKS_URL]
    assert health.key_count == 2
    assert health.refreshed_issuer_count == 1
    assert health.last_error_count == 0


def test_dynamic_oidc_verifier_uses_stale_keys_during_idp_outage_until_grace_expires() -> None:
    clock = MutableClock(1_000)
    fetcher = FakeJsonFetcher(
        {
            OIDC_DISCOVERY_URL: [
                oidc_discovery_document(),
                JwtAuthenticationError("idp outage"),
                JwtAuthenticationError("idp still down"),
            ],
            OIDC_JWKS_URL: [oidc_jwks()],
        }
    )
    verifier = DynamicOidcJwksVerifier(
        issuers=[
            oidc_discovery_config(
                refresh_interval_seconds=10,
                stale_grace_seconds=30,
                outage_policy=OidcOutagePolicy.USE_STALE_KEYS,
            )
        ],
        fetcher=fetcher,
        now_epoch=clock,
    )

    verifier.verify(signed_rs256_jwt({**claims(exp=2_000), "jti": "stale-1"}))
    clock.value = 1_012
    accepted_with_stale_key = verifier.verify(signed_rs256_jwt({**claims(exp=2_000), "jti": "stale-2"}))

    assert accepted_with_stale_key.jwt_id == "stale-2"
    assert verifier.health().last_error_count == 1

    clock.value = 1_041
    with pytest.raises(JwtAuthenticationError, match="cache expired"):
        verifier.verify(signed_rs256_jwt({**claims(exp=2_000), "jti": "stale-3"}))


def test_json_file_jwt_replay_store_persists_replayed_token_ids(tmp_path: Path) -> None:
    store_path = tmp_path / "jwt_replay_store.json"
    claims_with_jti = VerifiedJwtClaims(
        issuer=DEFAULT_JWT_ISSUER,
        subject="user-demo",
        audience={DEFAULT_JWT_AUDIENCE},
        tenant_id="tenant-demo",
        expires_at_epoch=2_000,
        jwt_id="persistent-jti",
    )

    JwtReplayGuard(store=JsonFileJwtReplayStore(store_path)).require_not_replayed(
        claims_with_jti,
        now_epoch=1_000,
    )

    with pytest.raises(JwtAuthenticationError, match="replay"):
        JwtReplayGuard(store=JsonFileJwtReplayStore(store_path)).require_not_replayed(
            claims_with_jti,
            now_epoch=1_001,
        )
