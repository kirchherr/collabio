import pytest

from office_recovery_proof import require_office_recovery_environment, verify_restored_page_break_versions
from suite.ai_control_plane.audit import canonical_json
from suite.platform.office_documents import OfficeDocumentCreateCommand, OfficeDocumentSaveCommand
from test_office_paragraph_recovery import recovery_documents
from test_office_recovery_proof import recovery_environment
from work_e2e_page_breaks import PAGE_BREAK_RECOVERY_TITLE, page_break_recovery_document


def test_page_break_seed_rejects_normal_environment_before_database_access() -> None:
    from unittest.mock import Mock

    from test_work_e2e_harness import valid_environment
    from work_e2e_page_breaks import seed_synthetic_office_page_breaks

    environment = valid_environment()
    environment["SUITE_DATABASE_DSN"] = "postgresql://app:secret@postgres:5432/collabio"
    client = Mock()
    with pytest.raises(RuntimeError):
        seed_synthetic_office_page_breaks(environment=environment, client=client)
    assert not client.mock_calls


def test_page_break_restore_target_requires_matching_fixed_pair() -> None:
    env = recovery_environment()
    for key in ("SUITE_POSTGRES_RESTORE_TARGET_DSN", "SUITE_OFFICE_RECOVERY_TARGET_DSN"):
        env[key] = env[key].replace("/collabio_work_e2e_restore", "/collabio_work_e2e_271_restore")
    require_office_recovery_environment(env)
    env["SUITE_POSTGRES_RESTORE_TARGET_DSN"] = recovery_environment()["SUITE_POSTGRES_RESTORE_TARGET_DSN"]
    with pytest.raises(ValueError):
        require_office_recovery_environment(env)


@pytest.mark.parametrize("tamper", [None, "missing", "format", "hash", "lineage"])
def test_recovery_binds_designated_legacy_and_formatted_sources_without_body_evidence(tamper: str | None) -> None:
    fixture = recovery_documents()
    fixture.service.writes_available = True
    user = fixture.users[0]
    created = fixture.service.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title=PAGE_BREAK_RECOVERY_TITLE,
            document=page_break_recovery_document(1),
            mutation_reference="work-e2e-page-break-recovery-1",
            human_confirmation=True,
        ),
    )
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    current = created
    for number in (2, 3):
        content = page_break_recovery_document(number)
        if tamper == "format" and number == 2:
            content["content"].pop(1)
        current = fixture.service.save(
            user_context=user,
            object_id=object_id,
            write_enabled=True,
            command=OfficeDocumentSaveCommand(
                title=PAGE_BREAK_RECOVERY_TITLE,
                document=content,
                mutation_reference=f"work-e2e-page-break-recovery-{number}",
                human_confirmation=True,
                expected_current_version_id=current.version.version_id,
            ),
        )
    fixture.service.writes_available = False
    versions = [
        record.model_dump() for record in fixture.repository.saved_versions.values() if record.object_id == object_id
    ]
    if tamper == "missing":
        versions.pop()
    elif tamper == "hash":
        versions[1]["content_hash"] = "sha256:incorrect"
    elif tamper == "lineage":
        versions[1]["previous_version_id"] = None
    if tamper is not None:
        with pytest.raises(ValueError):
            verify_restored_page_break_versions(documents=fixture.service, readers={object_id: user}, versions=versions)
    else:
        report = verify_restored_page_break_versions(documents=fixture.service, readers={object_id: user}, versions=versions)
        assert report["verified_page_break_fixture_version_count"] == 3
        assert report["page_break_insert_remove_verified"]
        assert report["legacy_page_break_canonical_hash_verified"]
        assert "Caf" not in canonical_json(report) and "textAlign" not in canonical_json(report)
