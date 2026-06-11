from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4

import psycopg

from suite.platform.context import JwtAuthenticationError


class PgJwtReplayStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise JwtAuthenticationError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def contains(self, *, tenant_id: str, issuer: str, jwt_id: str, now_epoch: int) -> bool:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT 1
                FROM collabio.jwt_replay_tokens
                WHERE tenant_id = %s
                  AND issuer = %s
                  AND jwt_id = %s
                  AND expires_at_epoch > %s
                LIMIT 1
                """,
                (tenant_id, issuer, jwt_id, now_epoch),
            ).fetchone()
        return row is not None

    def record(
        self,
        *,
        tenant_id: str,
        issuer: str,
        subject: str,
        jwt_id: str,
        expires_at_epoch: int,
        now_epoch: int,
    ) -> None:
        expires_at_utc = self._utc_from_epoch(expires_at_epoch)
        try:
            with psycopg.connect(self.database_dsn) as connection:
                self._set_tenant(connection, tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.jwt_replay_tokens (
                        tenant_id,
                        issuer,
                        subject,
                        jwt_id,
                        expires_at_epoch,
                        expires_at_utc,
                        audit_chain_ref
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        tenant_id,
                        issuer,
                        subject,
                        jwt_id,
                        expires_at_epoch,
                        expires_at_utc,
                        self._audit_chain_ref(
                            event_type="accepted",
                            tenant_id=tenant_id,
                            issuer=issuer,
                            subject=subject,
                            jwt_id=jwt_id,
                            expires_at_epoch=expires_at_epoch,
                            now_epoch=now_epoch,
                        ),
                    ),
                )
                self._insert_event(
                    connection,
                    tenant_id=tenant_id,
                    event_type="accepted",
                    issuer=issuer,
                    subject=subject,
                    jwt_id=jwt_id,
                    expires_at_epoch=expires_at_epoch,
                    expires_at_utc=expires_at_utc,
                    now_epoch=now_epoch,
                )
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            self.record_replay_detected(
                tenant_id=tenant_id,
                issuer=issuer,
                subject=subject,
                jwt_id=jwt_id,
                expires_at_epoch=expires_at_epoch,
                now_epoch=now_epoch,
            )
            raise JwtAuthenticationError("JWT replay detected") from exc

    def record_replay_detected(
        self,
        *,
        tenant_id: str,
        issuer: str,
        subject: str,
        jwt_id: str,
        expires_at_epoch: int,
        now_epoch: int,
    ) -> None:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            self._insert_event(
                connection,
                tenant_id=tenant_id,
                event_type="replayed",
                issuer=issuer,
                subject=subject,
                jwt_id=jwt_id,
                expires_at_epoch=expires_at_epoch,
                expires_at_utc=self._utc_from_epoch(expires_at_epoch),
                now_epoch=now_epoch,
            )
            connection.commit()

    def _insert_event(
        self,
        connection: psycopg.Connection[Any],
        *,
        tenant_id: str,
        event_type: str,
        issuer: str,
        subject: str,
        jwt_id: str,
        expires_at_epoch: int,
        expires_at_utc: datetime,
        now_epoch: int,
    ) -> None:
        event_id = f"jwt-replay-{uuid4().hex}"
        connection.execute(
            """
            INSERT INTO collabio.jwt_replay_events (
                tenant_id,
                event_id,
                event_type,
                issuer,
                subject,
                jwt_id,
                expires_at_epoch,
                expires_at_utc,
                observed_at_epoch,
                audit_chain_ref
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id,
                event_id,
                event_type,
                issuer,
                subject,
                jwt_id,
                expires_at_epoch,
                expires_at_utc,
                now_epoch,
                self._audit_chain_ref(
                    event_type=event_type,
                    tenant_id=tenant_id,
                    issuer=issuer,
                    subject=subject,
                    jwt_id=jwt_id,
                    expires_at_epoch=expires_at_epoch,
                    now_epoch=now_epoch,
                    event_id=event_id,
                ),
            ),
        )

    def _audit_chain_ref(
        self,
        *,
        event_type: str,
        tenant_id: str,
        issuer: str,
        subject: str,
        jwt_id: str,
        expires_at_epoch: int,
        now_epoch: int,
        event_id: str = "",
    ) -> str:
        payload = "\x1f".join(
            [event_type, tenant_id, issuer, subject, jwt_id, str(expires_at_epoch), str(now_epoch), event_id]
        )
        return "audit:jwt-replay:" + sha256(payload.encode("utf-8")).hexdigest()

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))

    def _utc_from_epoch(self, epoch: int) -> datetime:
        return datetime.fromtimestamp(epoch, tz=UTC)
