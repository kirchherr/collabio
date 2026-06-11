import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.context import (
    DEFAULT_JWT_AUDIENCE,
    DEFAULT_JWT_ISSUER,
    JwtAuthenticationError,
    JwtReplayGuard,
    VerifiedJwtClaims,
)
from suite.platform.jwt_replay_store import PgJwtReplayStore


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    app_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn)


def set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
    connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def claims(*, tenant_id: str, subject: str, jwt_id: str, exp: int = 2_000) -> VerifiedJwtClaims:
    return VerifiedJwtClaims(
        issuer=DEFAULT_JWT_ISSUER,
        subject=subject,
        audience={DEFAULT_JWT_AUDIENCE},
        tenant_id=tenant_id,
        expires_at_epoch=exp,
        issued_at_epoch=1_000,
        jwt_id=jwt_id,
    )


def test_pg_jwt_replay_store_records_accepted_and_replayed_events(live_database: LiveDatabase) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-replay-{suffix}"
    subject = f"user-{suffix}"
    jwt_id = f"jwt-{suffix}"
    replay_guard = JwtReplayGuard(store=PgJwtReplayStore(database_dsn=live_database.app_dsn))
    verified_claims = claims(tenant_id=tenant_id, subject=subject, jwt_id=jwt_id)

    replay_guard.require_not_replayed(verified_claims, now_epoch=1_000)

    with pytest.raises(JwtAuthenticationError, match="replay"):
        replay_guard.require_not_replayed(verified_claims, now_epoch=1_001)

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        token_row = owner_connection.execute(
            """
            SELECT tenant_id, issuer, subject, jwt_id, expires_at_epoch, audit_chain_ref
            FROM collabio.jwt_replay_tokens
            WHERE issuer = %s AND jwt_id = %s
            """,
            (DEFAULT_JWT_ISSUER, jwt_id),
        ).fetchone()
        event_rows = owner_connection.execute(
            """
            SELECT tenant_id, event_type, issuer, subject, jwt_id, audit_chain_ref
            FROM collabio.jwt_replay_events
            WHERE issuer = %s AND jwt_id = %s
            ORDER BY event_type
            """,
            (DEFAULT_JWT_ISSUER, jwt_id),
        ).fetchall()

    assert token_row is not None
    assert token_row == (
        tenant_id,
        DEFAULT_JWT_ISSUER,
        subject,
        jwt_id,
        2_000,
        token_row[5],
    )
    assert str(token_row[5]).startswith("audit:jwt-replay:")
    assert [row[1] for row in event_rows] == ["accepted", "replayed"]
    assert {row[0] for row in event_rows} == {tenant_id}
    assert all(str(row[5]).startswith("audit:jwt-replay:") for row in event_rows)


def test_pg_jwt_replay_store_blocks_cross_tenant_jti_reuse(live_database: LiveDatabase) -> None:
    suffix = uuid4().hex
    tenant_a = f"tenant-a-{suffix}"
    tenant_b = f"tenant-b-{suffix}"
    jwt_id = f"jwt-cross-tenant-{suffix}"
    replay_guard = JwtReplayGuard(store=PgJwtReplayStore(database_dsn=live_database.app_dsn))

    replay_guard.require_not_replayed(
        claims(tenant_id=tenant_a, subject=f"user-a-{suffix}", jwt_id=jwt_id),
        now_epoch=1_000,
    )

    with pytest.raises(JwtAuthenticationError, match="replay"):
        replay_guard.require_not_replayed(
            claims(tenant_id=tenant_b, subject=f"user-b-{suffix}", jwt_id=jwt_id),
            now_epoch=1_001,
        )

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        token_rows = owner_connection.execute(
            """
            SELECT tenant_id, jwt_id
            FROM collabio.jwt_replay_tokens
            WHERE issuer = %s AND jwt_id = %s
            """,
            (DEFAULT_JWT_ISSUER, jwt_id),
        ).fetchall()
        event_rows = owner_connection.execute(
            """
            SELECT tenant_id, event_type
            FROM collabio.jwt_replay_events
            WHERE issuer = %s AND jwt_id = %s
            ORDER BY event_type, tenant_id
            """,
            (DEFAULT_JWT_ISSUER, jwt_id),
        ).fetchall()

    assert token_rows == [(tenant_a, jwt_id)]
    assert event_rows == [(tenant_a, "accepted"), (tenant_b, "replayed")]


def test_pg_jwt_replay_store_enforces_rls_and_no_runtime_delete(live_database: LiveDatabase) -> None:
    suffix = uuid4().hex
    tenant_a = f"tenant-a-{suffix}"
    tenant_b = f"tenant-b-{suffix}"
    jwt_a = f"jwt-a-{suffix}"
    jwt_b = f"jwt-b-{suffix}"
    replay_guard = JwtReplayGuard(store=PgJwtReplayStore(database_dsn=live_database.app_dsn))

    replay_guard.require_not_replayed(
        claims(tenant_id=tenant_a, subject=f"user-a-{suffix}", jwt_id=jwt_a),
        now_epoch=1_000,
    )
    replay_guard.require_not_replayed(
        claims(tenant_id=tenant_b, subject=f"user-b-{suffix}", jwt_id=jwt_b),
        now_epoch=1_000,
    )

    with psycopg.connect(live_database.app_dsn) as app_connection:
        set_tenant(app_connection, tenant_a)
        rows = app_connection.execute(
            """
            SELECT tenant_id, jwt_id
            FROM collabio.jwt_replay_tokens
            WHERE jwt_id IN (%s, %s)
            ORDER BY jwt_id
            """,
            (jwt_a, jwt_b),
        ).fetchall()

        assert rows == [(tenant_a, jwt_a)]

        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
            app_connection.execute(
                """
                DELETE FROM collabio.jwt_replay_tokens
                WHERE issuer = %s AND jwt_id = %s
                """,
                (DEFAULT_JWT_ISSUER, jwt_a),
            )
