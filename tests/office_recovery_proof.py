"""Explicit synthetic-only PostgreSQL/S3 recovery proof after the Work browser run.

The operator supplies an already restored, separate database and its checked
pg_dump artifact. Only this short-lived proof runner joins both test networks.
It never creates/restores/drops a database or enables a module or Office engine.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg

from office_suggestion_recovery import verify_restored_suggestions
from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.operations.postgres_restore_drill import run_postgres_restore_drill_from_environment
from suite.platform.office_document_repository import PgOfficeDocumentRepository
from suite.platform.office_documents import (
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
    OfficeDocumentService,
    OfficeDocumentVersionView,
    OfficeDocumentView,
)
from suite.platform.office_review_repository import PgOfficeReviewRepository
from suite.platform.office_reviews import OfficeReviewService, ReviewEventCommand, derive_review_quote
from suite.platform.office_suggestion_repository import OfficeSuggestionRepositoryAdapter
from suite.platform.office_suggestions import OfficeSuggestionService
from suite.platform.principal_store import PgPrincipalDirectory
from suite.storage.adapter_policy import load_storage_adapter_policy
from suite.storage.exact_version_restore_drill import (
    build_restore_target_isolation_ref_hash,
    run_exact_version_restore_drill,
)
from suite.storage.retention import load_retention_manifest_policy
from suite.storage.s3_compatible_content_store import (
    S3CompatibleSourceObjectContentStore,
    build_s3_compatible_provider_profile_evidence,
)
from suite.storage.s3_sdk_client import build_boto3_s3_compatible_client, wait_for_s3_compatible_client
from suite.storage.source_object_storage import PgSourceObjectRepository, SourceObjectStorageError
from suite.storage.source_objects import (
    PgSourceObjectWriteReceiptStore,
    SourceObjectRepository,
    SourceObjectType,
    SourceObjectWriteReceiptStore,
    build_source_object_write_receipt,
    build_source_object_write_receipt_hash,
    source_object_content_bytes,
)
from work_e2e_styles import STYLE_RECOVERY_TITLE, style_recovery_document
from work_e2e_character import CHARACTER_RECOVERY_TITLE, character_recovery_document
from work_e2e_paragraph import PARAGRAPH_RECOVERY_TITLE, PARAGRAPH_RECOVERY_VERSION_COUNT, paragraph_recovery_document

TENANT_ID = "tenant-work-e2e"
EDITOR_ID = "work-office-editor-e2e"


def require_office_recovery_environment(env: Mapping[str, str]) -> None:
    if (
        env.get("SUITE_OFFICE_RECOVERY_MODE") != "isolated-office-recovery"
        or env.get("SUITE_ENV") != "dev"
        or env.get("SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED") != "0"
    ):
        raise ValueError("Office recovery requires the isolated development marker and closed pilot")
    expected = {
        "SUITE_POSTGRES_RESTORE_SOURCE_DSN": ("work-e2e-postgres", "collabio_work_e2e", "collabio_owner"),
        "SUITE_POSTGRES_RESTORE_TARGET_DSN": ("postgres-restore", "collabio_work_e2e_restore", "collabio_owner"),
        "SUITE_DATABASE_DSN": ("work-e2e-postgres", "collabio_work_e2e", "collabio_app"),
        "SUITE_OFFICE_RECOVERY_TARGET_DSN": ("postgres-restore", "collabio_work_e2e_restore", "collabio_app"),
    }
    target_database = urlparse(env.get("SUITE_OFFICE_RECOVERY_TARGET_DSN", "")).path.removeprefix("/")
    if target_database not in {
        "collabio_work_e2e_restore",
        "collabio_work_e2e_262_restore",
        "collabio_work_e2e_263_restore",
        "collabio_work_e2e_267_restore",
    }:
        raise ValueError("Office recovery database is outside its isolated scope")
    expected["SUITE_POSTGRES_RESTORE_TARGET_DSN"] = ("postgres-restore", target_database, "collabio_owner")
    expected["SUITE_OFFICE_RECOVERY_TARGET_DSN"] = ("postgres-restore", target_database, "collabio_app")
    for key, (host, database, user) in expected.items():
        parsed = urlparse(env.get(key, ""))
        if (
            parsed.scheme not in {"postgres", "postgresql"}
            or parsed.hostname != host
            or parsed.path != f"/{database}"
            or parsed.username != user
            or parsed.port != 5432
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Office recovery database is outside its isolated scope")
    if env.get("SUITE_S3_ENDPOINT_URL") != "http://work-e2e-minio:9000":
        raise ValueError("Office recovery source storage is outside its isolated scope")
    if env.get("SUITE_RESTORE_S3_ENDPOINT_URL") != "http://minio-restore:9000":
        raise ValueError("Office recovery target storage is outside its isolated scope")
    if (
        env.get("SUITE_POSTGRES_BACKUP_DIRECTORY") != "/proof-backup"
        or env.get("SUITE_POSTGRES_RESTORE_RECEIPT_PATH") != "/proof-backup/postgres-restore-receipt.sha256"
    ):
        raise ValueError("Office recovery must use its separately mounted backup artifact")


def _metadata_snapshot(database_dsn: str) -> dict[str, list[Any]]:
    rows: dict[str, list[Any]] = {}
    with psycopg.connect(database_dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (TENANT_ID,))
        for table in (
            "documents",
            "document_versions",
            "review_threads",
            "review_events",
            "text_suggestions",
            "text_suggestion_decisions",
        ):
            result = connection.execute(
                f"SELECT to_jsonb(record) FROM office.{table} AS record WHERE tenant_id = %s "
                "ORDER BY to_jsonb(record)::text",
                (TENANT_ID,),
            ).fetchall()
            rows[table] = [row[0] for row in result]
        result = connection.execute(
            "SELECT to_jsonb(acl) FROM collabio.object_acl_entries AS acl "
            "WHERE acl.tenant_id = %s AND acl.object_type = 'office.document' "
            "ORDER BY to_jsonb(acl)::text",
            (TENANT_ID,),
        ).fetchall()
        rows["acls"] = [row[0] for row in result]
    return rows


def _metadata_hash(database_dsn: str) -> str:
    return stable_hash(canonical_json(_metadata_snapshot(database_dsn)))


def verify_restored_reviews(
    *,
    documents: OfficeDocumentService,
    reviews: OfficeReviewService,
    sources: SourceObjectRepository,
    receipts: SourceObjectWriteReceiptStore,
    user: UserContext,
    object_ids: tuple[str, ...],
    expected_thread_ids: set[str],
    expected_event_ids: set[str],
    users_by_object: Mapping[str, UserContext] | None = None,
) -> dict[str, Any]:
    """Read all restored review pages and independently bind each immutable source."""
    evidence: list[dict[str, Any]] = []
    seen_threads: set[str] = set()
    seen_events: set[str] = set()
    complete_lifecycles = 0
    anchored_threads = 0
    historical_threads = 0
    denied_target: tuple[str, str] | None = None
    denied_target_user = user
    for object_id in object_ids:
        user = users_by_object[object_id] if users_by_object is not None else user
        after: str | None = None
        while True:
            listing = reviews.list_threads(user_context=user, object_id=object_id, after=after, limit=50)
            if listing.can_create or listing.can_comment or listing.can_resolve:
                raise ValueError("Office review recovery must remain read-only")
            for thread in listing.threads:
                if thread.thread_id in seen_threads:
                    raise ValueError("Office review recovery encountered a duplicate thread")
                seen_threads.add(thread.thread_id)
                denied_target = (object_id, thread.thread_id)
                denied_target_user = user
                anchor_version = documents.read_content(
                    user_context=user, object_id=object_id, version_id=thread.anchor_version_id
                )
                quote = derive_review_quote(anchor_version.content, thread.anchor)
                anchored_threads += int(thread.anchor is not None)
                historical_threads += int(not anchor_version.is_current_version)
                after_revision = 0
                previous_event_id: str | None = None
                status = "open"
                operations: list[str] = []
                while True:
                    detail = reviews.detail(
                        user_context=user,
                        object_id=object_id,
                        thread_id=thread.thread_id,
                        after_revision=after_revision,
                        limit=50,
                    )
                    snapshot = reviews.repository.detail(
                        user=user,
                        object_id=object_id,
                        thread_id=thread.thread_id,
                        after_revision=after_revision,
                        limit=50,
                    )
                    if (
                        detail.thread != thread
                        or detail.quote != quote
                        or detail.can_comment
                        or detail.can_resolve
                        or detail.rag_indexing_allowed
                        or detail.search_indexing_allowed
                        or snapshot.thread.anchor_content_hash != anchor_version.version.content_hash
                        or len(detail.events) != len(snapshot.events)
                    ):
                        raise ValueError("Office restored review anchor or permissions are invalid")
                    for view, event in zip(detail.events, snapshot.events, strict=True):
                        record = sources.get(
                            tenant_id=user.tenant_id, object_id=thread.thread_id, version_id=event.event_id
                        )
                        payload = json.loads(source_object_content_bytes(record).decode("utf-8"))
                        receipt = receipts.get(tenant_id=user.tenant_id, receipt_hash=event.source_write_receipt_hash)
                        expected_receipt = build_source_object_write_receipt(
                            record=record,
                            receipt_reference=receipt.receipt_reference,
                            audit_chain_ref=receipt.audit_chain_ref,
                            captured_at_utc=receipt.captured_at_utc,
                        )
                        if (
                            event.event_id in seen_events
                            or event.revision != after_revision + 1
                            or event.previous_event_id != previous_event_id
                            or event.thread_id != thread.thread_id
                            or event.object_id != object_id
                            or record.metadata.object_type != SourceObjectType.COMMENT
                            or record.metadata.parent_object_id != object_id
                            or record.metadata.thread_id != thread.thread_id
                            or receipt != expected_receipt
                            or receipt.receipt_hash != event.source_write_receipt_hash
                            or receipt.content_hash != event.content_hash
                            or receipt.manifest_hash != event.source_manifest_hash
                            or stable_hash(canonical_json(payload)) != event.content_hash
                            or payload["anchor_version_id"] != thread.anchor_version_id
                            or payload["anchor_content_hash"] != anchor_version.version.content_hash
                            or payload["quote"] != quote
                            or view.body != payload["body"]
                            or view.event_id != event.event_id
                            or view.revision != event.revision
                            or view.operation != event.operation
                        ):
                            raise ValueError("Office restored review event, source or receipt binding is invalid")
                        if event.operation == "create":
                            valid_transition = event.revision == 1
                        elif event.operation == "reopen":
                            valid_transition = status == "resolved"
                        else:
                            valid_transition = status == "open" and event.revision > 1
                        status = "resolved" if event.operation == "resolve" else "open"
                        if not valid_transition or event.status_after != status:
                            raise ValueError("Office restored review status history is invalid")
                        seen_events.add(event.event_id)
                        operations.append(event.operation)
                        after_revision = event.revision
                        previous_event_id = event.event_id
                        evidence.append(
                            {
                                "object_id": object_id,
                                "thread_id": thread.thread_id,
                                "anchor_version_id": thread.anchor_version_id,
                                "event_id": event.event_id,
                                "revision": event.revision,
                                "content_hash": event.content_hash,
                                "receipt_hash": receipt.receipt_hash,
                            }
                        )
                    if detail.next_after_revision is None:
                        if (
                            after_revision != thread.revision
                            or previous_event_id != snapshot.thread.current_event_id
                            or status != thread.status
                        ):
                            raise ValueError("Office restored review head does not match its complete event history")
                        break
                    if not detail.events or detail.next_after_revision != after_revision:
                        raise ValueError("Office restored review cursor is invalid")
                complete_lifecycles += int(
                    all(operation in operations for operation in ("create", "reply", "resolve", "reopen"))
                )
            if listing.next_cursor is None:
                break
            if not listing.threads or listing.next_cursor == after or listing.next_cursor not in seen_threads:
                raise ValueError("Office restored review list cursor is invalid")
            after = listing.next_cursor
    if seen_threads != expected_thread_ids or seen_events != expected_event_ids:
        raise ValueError("Office review recovery did not read the complete database inventory")
    if complete_lifecycles < 1 or anchored_threads < 1 or historical_threads < 1 or denied_target is None:
        raise ValueError(
            "Office recovery requires nonempty anchored, historical and complete review lifecycle evidence"
        )
    object_id, thread_id = denied_target
    user = denied_target_user
    for denied_user in (
        UserContext(
            tenant_id="tenant-work-e2e-foreign", user_id=user.user_id, readable_object_ids={object_id, thread_id}
        ),
        UserContext(tenant_id=user.tenant_id, user_id="work-assignee-e2e", readable_object_ids={object_id, thread_id}),
    ):
        try:
            reviews.detail(user_context=denied_user, object_id=object_id, thread_id=thread_id)
        except OfficeDocumentNotFoundError:
            pass
        else:
            raise ValueError("Office restored review access did not deny an unauthorized reader")
    try:
        reviews.mutate(
            user_context=user,
            object_id=object_id,
            thread_id=thread_id,
            write_enabled=True,
            command=ReviewEventCommand(
                operation="reply",
                expected_revision=1,
                body="Must not persist",
                mutation_reference="synthetic-recovery-write-denied",
                human_confirmation=True,
            ),
        )
    except OfficeDocumentPermissionError:
        pass
    else:
        raise ValueError("Office review recovery accepted a mutation")
    return {
        "review_evidence_hash": stable_hash(canonical_json(evidence)),
        "verified_review_thread_count": len(seen_threads),
        "verified_review_event_count": len(seen_events),
        "complete_review_lifecycle_count": complete_lifecycles,
        "anchored_review_thread_count": anchored_threads,
        "historical_review_thread_count": historical_threads,
        "review_receipt_bindings_verified": True,
        "review_authoritative_acl_verified": True,
        "review_read_only_verified": True,
    }


def _restored_readers(database_dsn: str) -> tuple[UserContext, ...]:
    # Resolve only existing, active DB principals and memberships. Readable IDs
    # are hints from the directory; each service page/read rechecks typed ACLs.
    # No grants, role assignments or readable-object browser headers are added.
    with psycopg.connect(database_dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (TENANT_ID,))
        principals = connection.execute(
            "SELECT p.user_id, p.issuer, p.subject FROM collabio.tenant_principals AS p "
            "JOIN collabio.tenant_principal_memberships AS m "
            "ON m.tenant_id = p.tenant_id AND m.issuer = p.issuer AND m.subject = p.subject "
            "WHERE p.tenant_id = %s AND p.status = 'active' AND m.status = 'active' "
            "ORDER BY p.user_id, p.issuer, p.subject",
            (TENANT_ID,),
        ).fetchall()
        identities: list[tuple[str, set[str], set[str]]] = []
        for user_id, issuer, subject in principals:
            roles = connection.execute(
                "SELECT assignment.role_id FROM collabio.tenant_principal_role_assignments AS assignment "
                "JOIN collabio.tenant_roles AS role ON role.tenant_id = assignment.tenant_id "
                "AND role.role_id = assignment.role_id WHERE assignment.tenant_id = %s "
                "AND assignment.issuer = %s AND assignment.subject = %s "
                "AND assignment.status = 'active' AND role.status = 'active'",
                (TENANT_ID, issuer, subject),
            ).fetchall()
            groups = connection.execute(
                "SELECT membership.group_id FROM collabio.tenant_principal_group_memberships AS membership "
                "JOIN collabio.tenant_groups AS tenant_group ON tenant_group.tenant_id = membership.tenant_id "
                "AND tenant_group.group_id = membership.group_id WHERE membership.tenant_id = %s "
                "AND membership.issuer = %s AND membership.subject = %s "
                "AND membership.status = 'active' AND tenant_group.status = 'active'",
                (TENANT_ID, issuer, subject),
            ).fetchall()
            identities.append((str(user_id), {str(row[0]) for row in roles}, {str(row[0]) for row in groups}))
    if not identities:
        raise ValueError("Office recovery synthetic reader membership is missing")
    directory = PgPrincipalDirectory(database_dsn=database_dsn)
    return tuple(
        UserContext(
            tenant_id=TENANT_ID,
            user_id=user_id,
            role_ids=roles,
            readable_object_ids=directory.readable_object_ids(
                tenant_id=TENANT_ID,
                user_id=user_id,
                role_ids=roles,
                group_ids=groups,
            ),
        )
        for user_id, roles, groups in identities
    )


def restored_document_inventory(
    *,
    documents: OfficeDocumentService,
    users: tuple[UserContext, ...],
    expected_documents: list[Any],
) -> tuple[tuple[OfficeDocumentView, ...], dict[str, UserContext]]:
    expected_heads = {row["object_id"]: row["current_version_id"] for row in expected_documents}
    found: dict[str, OfficeDocumentView] = {}
    readers: dict[str, UserContext] = {}
    for user in users:
        if user.tenant_id != TENANT_ID:
            raise ValueError("Office recovery principal is outside its isolated scope")
        cursor: str | None = None
        cursors: set[str] = set()
        seen: set[str] = set()
        while True:
            page = documents.list_documents(user_context=user, page_size=200, cursor=cursor, write_enabled=True)
            if page.tenant_id != TENANT_ID or page.can_create or page.has_more != (page.next_cursor is not None):
                raise ValueError("Office recovery document page or capabilities are invalid")
            for document in page.documents:
                if (
                    document.object_id in seen
                    or document.can_write
                    or expected_heads.get(document.object_id) != document.current_version_id
                    or (document.object_id in found and found[document.object_id] != document)
                ):
                    raise ValueError("Office recovery document inventory or head is invalid")
                seen.add(document.object_id)
                found[document.object_id] = document
                readers.setdefault(document.object_id, user)
            if page.next_cursor is None:
                break
            if not page.documents or page.next_cursor in cursors:
                raise ValueError("Office recovery document cursor is invalid")
            cursor = page.next_cursor
            cursors.add(cursor)
    if set(found) != set(expected_heads):
        raise ValueError("Office recovery did not read the complete document inventory")
    return tuple(found[key] for key in sorted(found)), readers


def restored_version_inventory(
    *,
    documents: OfficeDocumentService,
    user: UserContext,
    document: OfficeDocumentView,
) -> tuple[OfficeDocumentVersionView, ...]:
    versions: list[OfficeDocumentVersionView] = []
    seen: set[str] = set()
    cursors: set[str] = set()
    cursor: str | None = None
    expected_version: str | None = document.current_version_id
    while True:
        page = documents.history(user_context=user, object_id=document.object_id, page_size=200, cursor=cursor)
        if (
            page.tenant_id != TENANT_ID
            or page.object_id != document.object_id
            or page.history_head_version_id != document.current_version_id
            or page.current_version_id != document.current_version_id
            or not page.versions
            or page.has_more != (page.next_cursor is not None)
        ):
            raise ValueError("Office recovery history page or head is invalid")
        for version in page.versions:
            if version.version_id in seen or version.version_id != expected_version:
                raise ValueError("Office recovery version chain is invalid")
            seen.add(version.version_id)
            versions.append(version)
            expected_version = version.previous_version_id
        if page.has_more != (expected_version is not None):
            raise ValueError("Office recovery version history is incomplete")
        if page.next_cursor is None:
            return tuple(versions)
        if page.next_cursor in cursors:
            raise ValueError("Office recovery history cursor is invalid")
        cursor = page.next_cursor
        cursors.add(cursor)


def verify_restored_paragraph_versions(
    *,
    documents: OfficeDocumentService,
    readers: Mapping[str, UserContext],
    versions: list[Any],
) -> dict[str, Any]:
    """Bind the designated legacy and two formatted sources to their exact versions."""
    evidence: list[dict[str, str]] = []
    object_id: str | None = None
    previous: str | None = None
    for number in range(1, PARAGRAPH_RECOVERY_VERSION_COUNT + 1):
        candidates = [row for row in versions if row["mutation_reference"] == f"work-e2e-paragraph-recovery-{number}"]
        if len(candidates) != 1:
            raise ValueError("Office recovery paragraph fixtures are missing or ambiguous")
        version = candidates[0]
        object_id = object_id or version["object_id"]
        if version["object_id"] != object_id or version["previous_version_id"] != previous:
            raise ValueError("Office recovery paragraph fixture lineage is invalid")
        expected = paragraph_recovery_document(number)
        read = documents.read_content(
            user_context=readers[object_id], object_id=object_id, version_id=version["version_id"]
        )
        if (
            read.content != expected
            or read.version.title != PARAGRAPH_RECOVERY_TITLE
            or read.version.content_hash != stable_hash(canonical_json(expected))
            or read.version.content_hash != version["content_hash"]
            or read.can_write
        ):
            raise ValueError("Office recovery paragraph content or canonical hash is invalid")
        evidence.append(
            {"object_id": object_id, "version_id": read.version.version_id, "content_hash": read.version.content_hash}
        )
        previous = read.version.version_id
    return {
        "paragraph_formatting_evidence_hash": stable_hash(canonical_json(evidence)),
        "verified_paragraph_fixture_version_count": len(evidence),
        "verified_formatted_fixture_version_count": PARAGRAPH_RECOVERY_VERSION_COUNT - 1,
        "legacy_paragraph_canonical_hash_verified": True,
    }


def verify_restored_character_versions(
    *,
    documents: OfficeDocumentService,
    readers: Mapping[str, UserContext],
    versions: list[Any],
) -> dict[str, Any]:
    """Bind the designated legacy and two formatted sources to their exact versions."""
    evidence: list[dict[str, str]] = []
    object_id: str | None = None
    previous: str | None = None
    for number in range(1, 3 + 1):
        candidates = [row for row in versions if row["mutation_reference"] == f"work-e2e-character-recovery-{number}"]
        if len(candidates) != 1:
            raise ValueError("Office recovery character fixtures are missing or ambiguous")
        version = candidates[0]
        object_id = object_id or version["object_id"]
        if version["object_id"] != object_id or version["previous_version_id"] != previous:
            raise ValueError("Office recovery character fixture lineage is invalid")
        expected = character_recovery_document(number)
        read = documents.read_content(
            user_context=readers[object_id], object_id=object_id, version_id=version["version_id"]
        )
        if (
            read.content != expected
            or read.version.title != CHARACTER_RECOVERY_TITLE
            or read.version.content_hash != stable_hash(canonical_json(expected))
            or read.version.content_hash != version["content_hash"]
            or read.can_write
        ):
            raise ValueError("Office recovery character content or canonical hash is invalid")
        evidence.append(
            {"object_id": object_id, "version_id": read.version.version_id, "content_hash": read.version.content_hash}
        )
        previous = read.version.version_id
    return {
        "character_formatting_evidence_hash": stable_hash(canonical_json(evidence)),
        "verified_character_fixture_version_count": len(evidence),
        "verified_character_formatted_version_count": 3 - 1,
        "legacy_character_canonical_hash_verified": True,
    }


def verify_restored_style_versions(
    *,
    documents: OfficeDocumentService,
    readers: Mapping[str, UserContext],
    versions: list[Any],
) -> dict[str, Any]:
    """Bind the designated legacy and two formatted sources to their exact versions."""
    evidence: list[dict[str, str]] = []
    object_id: str | None = None
    previous: str | None = None
    for number in range(1, 3 + 1):
        candidates = [row for row in versions if row["mutation_reference"] == f"work-e2e-style-recovery-{number}"]
        if len(candidates) != 1:
            raise ValueError("Office recovery style fixtures are missing or ambiguous")
        version = candidates[0]
        object_id = object_id or version["object_id"]
        if version["object_id"] != object_id or version["previous_version_id"] != previous:
            raise ValueError("Office recovery style fixture lineage is invalid")
        expected = style_recovery_document(number)
        read = documents.read_content(
            user_context=readers[object_id], object_id=object_id, version_id=version["version_id"]
        )
        if (
            read.content != expected
            or read.version.title != STYLE_RECOVERY_TITLE
            or read.version.content_hash != stable_hash(canonical_json(expected))
            or read.version.content_hash != version["content_hash"]
            or read.can_write
        ):
            raise ValueError("Office recovery style content or canonical hash is invalid")
        evidence.append(
            {"object_id": object_id, "version_id": read.version.version_id, "content_hash": read.version.content_hash}
        )
        previous = read.version.version_id
    return {
        "style_formatting_evidence_hash": stable_hash(canonical_json(evidence)),
        "verified_style_fixture_version_count": len(evidence),
        "verified_style_formatted_version_count": 3 - 1,
        "legacy_style_canonical_hash_verified": True,
    }


def run_office_recovery_proof(env: Mapping[str, str]) -> dict[str, Any]:
    require_office_recovery_environment(env)
    postgres = run_postgres_restore_drill_from_environment(env)
    if not postgres.restore_ready or not postgres.office_document_controls_verified:
        raise ValueError("Office recovery PostgreSQL controls are not verified")
    source_dsn = env["SUITE_DATABASE_DSN"]
    target_dsn = env["SUITE_OFFICE_RECOVERY_TARGET_DSN"]
    inventory = _metadata_snapshot(source_dsn)
    source_metadata_hash = stable_hash(canonical_json(inventory))
    if source_metadata_hash != _metadata_hash(target_dsn):
        raise ValueError("Office metadata and ACL snapshot do not match the source")
    storage_policy = load_storage_adapter_policy(Path("docs/storage_adapter_policy.json"))
    retention_policy = load_retention_manifest_policy(Path("docs/retention_manifest_policy.json"))
    source_client = build_boto3_s3_compatible_client(
        endpoint_url=env["SUITE_S3_ENDPOINT_URL"],
        access_key_id=env["SUITE_S3_ACCESS_KEY_ID"],
        secret_access_key=env["SUITE_S3_SECRET_ACCESS_KEY"],
        storage_provider="minio",
    )
    target_client = build_boto3_s3_compatible_client(
        endpoint_url=env["SUITE_RESTORE_S3_ENDPOINT_URL"],
        access_key_id=env["SUITE_RESTORE_S3_ACCESS_KEY_ID"],
        secret_access_key=env["SUITE_RESTORE_S3_SECRET_ACCESS_KEY"],
        storage_provider="minio-restore-target",
    )
    wait_for_s3_compatible_client(client=target_client, storage_policy=storage_policy)
    source_repository = PgSourceObjectRepository(
        database_dsn=source_dsn,
        storage_policy=storage_policy,
        retention_policy=retention_policy,
        content_store=S3CompatibleSourceObjectContentStore(client=source_client, storage_policy=storage_policy),
    )
    source_profile = build_s3_compatible_provider_profile_evidence(
        client=source_client,
        storage_policy=storage_policy,
        provider_profile_id="office-e2e-source",
    )
    target_profile = build_s3_compatible_provider_profile_evidence(
        client=target_client,
        storage_policy=storage_policy,
        provider_profile_id="office-e2e-restore",
    )
    objects = run_exact_version_restore_drill(
        repository=source_repository,
        target_client=target_client,
        storage_policy=storage_policy,
        retention_policy=retention_policy,
        source_provider_profile_evidence=source_profile,
        target_provider_profile_evidence=target_profile,
        target_isolation_ref_hash=build_restore_target_isolation_ref_hash(
            source_endpoint=env["SUITE_S3_ENDPOINT_URL"],
            target_endpoint=env["SUITE_RESTORE_S3_ENDPOINT_URL"],
            source_provider_profile_id="office-e2e-source",
            target_provider_profile_id="office-e2e-restore",
        ),
        tenant_ids=(TENANT_ID,),
    )
    if not objects.restore_ready:
        raise ValueError("Office exact-version object restoration is not verified")
    restored_sources = PgSourceObjectRepository(
        database_dsn=target_dsn,
        storage_policy=storage_policy,
        retention_policy=retention_policy,
        content_store=S3CompatibleSourceObjectContentStore(
            client=target_client,
            storage_policy=storage_policy,
            restore_reference_resolution_enabled=True,
        ),
    )
    receipt_store = PgSourceObjectWriteReceiptStore(database_dsn=target_dsn)
    restored = OfficeDocumentService(
        repository=PgOfficeDocumentRepository(
            database_dsn=target_dsn, source_repository=restored_sources, receipt_store=receipt_store
        ),
        source_repository=restored_sources,
        audit=InMemoryAuditLogger(),
        writes_available=False,
    )
    users = _restored_readers(target_dsn)
    documents, readers = restored_document_inventory(
        documents=restored,
        users=users,
        expected_documents=inventory["documents"],
    )
    evidence: list[dict[str, Any]] = []
    multi_version_documents = 0
    for document in documents:
        user = readers[document.object_id]
        versions = restored_version_inventory(documents=restored, user=user, document=document)
        multi_version_documents += int(len(versions) >= 2)
        for version in versions:
            read = restored.read_content(user_context=user, object_id=document.object_id, version_id=version.version_id)
            receipt = receipt_store.get(tenant_id=TENANT_ID, receipt_hash=version.source_write_receipt_hash)
            source = source_repository.get(
                tenant_id=TENANT_ID, object_id=document.object_id, version_id=version.version_id
            )
            if (
                receipt.receipt_hash != build_source_object_write_receipt_hash(receipt)
                or receipt.object_id != document.object_id
                or receipt.version_id != version.version_id
                or receipt.content_hash != version.content_hash
                or receipt.manifest_hash != source.metadata.manifest_hash
                or stable_hash(canonical_json(read.content)) != source.metadata.content_hash
                or read.can_write
                or read.rag_indexing_allowed
                or read.search_indexing_allowed
            ):
                raise ValueError("Office restored version or receipt binding is invalid")
            evidence.append(
                {
                    "object_id": document.object_id,
                    "version_id": version.version_id,
                    "content_hash": version.content_hash,
                    "receipt_hash": receipt.receipt_hash,
                }
            )
    if multi_version_documents < 1 or len(evidence) < 2:
        raise ValueError("Office recovery requires a non-empty document with at least two saved versions")
    if {row["version_id"] for row in evidence} != {row["version_id"] for row in inventory["document_versions"]}:
        raise ValueError("Office recovery did not read the complete version inventory")
    paragraph_evidence = verify_restored_paragraph_versions(
        documents=restored,
        readers=readers,
        versions=inventory["document_versions"],
    )
    style_evidence = verify_restored_style_versions(documents=restored, readers=readers, versions=inventory["document_versions"])
    character_evidence = verify_restored_character_versions(
        documents=restored,
        readers=readers,
        versions=inventory["document_versions"],
    )
    review_evidence = verify_restored_reviews(
        documents=restored,
        reviews=OfficeReviewService(
            repository=PgOfficeReviewRepository(document_service=restored),
            source_repository=restored_sources,
            audit=InMemoryAuditLogger(),
            writes_available=False,
        ),
        sources=restored_sources,
        receipts=receipt_store,
        user=users[0],
        users_by_object=readers,
        object_ids=tuple(document.object_id for document in documents),
        expected_thread_ids={row["thread_id"] for row in inventory["review_threads"]},
        expected_event_ids={row["event_id"] for row in inventory["review_events"]},
    )
    suggestion_evidence = verify_restored_suggestions(
        suggestions=OfficeSuggestionService(
            repository=OfficeSuggestionRepositoryAdapter(document_service=restored),
            document_service=restored,
            audit=InMemoryAuditLogger(),
        ),
        sources=restored_sources,
        receipts=receipt_store,
        user=users[0],
        users_by_object=readers,
        object_ids=tuple(document.object_id for document in documents),
        expected_suggestion_ids={row["suggestion_id"] for row in inventory["text_suggestions"]},
        expected_decision_ids={row["decision_id"] for row in inventory["text_suggestion_decisions"]},
    )
    foreign = UserContext(
        tenant_id="tenant-work-e2e-foreign", user_id=EDITOR_ID, readable_object_ids={documents[0].object_id}
    )
    try:
        restored.read_content(user_context=foreign, object_id=documents[0].object_id)
    except OfficeDocumentNotFoundError:
        pass
    else:
        raise ValueError("Office restored tenant isolation did not deny a foreign reader")
    if source_metadata_hash != _metadata_hash(source_dsn) or source_metadata_hash != _metadata_hash(target_dsn):
        raise ValueError("Office recovery observed concurrent metadata changes")
    report = {
        "schema_version": "office_native_synthetic_recovery_proof.v1",
        "synthetic_only": True,
        "postgres_restore_report_hash": postgres.report_hash,
        "backup_sha256": postgres.backup_sha256,
        "exact_version_restore_report_hash": objects.report_hash,
        "office_metadata_hash": source_metadata_hash,
        "version_evidence_hash": stable_hash(canonical_json(evidence)),
        "document_count": len(documents),
        "verified_office_version_count": len(evidence),
        "multi_version_document_count": multi_version_documents,
        "restored_source_object_count": objects.restored_object_count,
        **review_evidence,
        **suggestion_evidence,
        **paragraph_evidence,
        **character_evidence,
        **style_evidence,
        "authoritative_acl_verified": True,
        "receipt_bindings_verified": True,
        "foreign_tenant_denied": True,
        "recovery_ready": True,
        "content_included": False,
        "runtime_activated": False,
        "office_engine_admitted": False,
    }
    report["report_hash"] = stable_hash(canonical_json(report))
    return report


def main() -> int:
    try:
        report = run_office_recovery_proof(os.environ)
    except (KeyError, ValueError, OSError, psycopg.Error, SourceObjectStorageError):
        print(
            json.dumps(
                {
                    "schema_version": "office_native_synthetic_recovery_proof.v1",
                    "recovery_ready": False,
                    "content_included": False,
                    "reason": "Office synthetic recovery proof failed",
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
