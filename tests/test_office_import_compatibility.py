from collections import Counter

from suite.platform.office_import_compatibility import build_office_import_compatibility_matrix
from suite.platform.office_macro_policy import build_office_macro_policy
from suite.platform.office_parser_worker_plan import build_office_parser_worker_plan


def test_import_compatibility_matrix_is_exact_metadata_only_and_dispatch_closed() -> None:
    matrix = build_office_import_compatibility_matrix(tenant_id="tenant-import")
    parser = build_office_parser_worker_plan(tenant_id="tenant-import")
    macro = build_office_macro_policy(tenant_id="tenant-import")

    assert matrix.schema_version == "office_import_compatibility_matrix.v1"
    assert matrix.matrix_state == "development_contract_dispatch_closed"
    assert matrix.parser_profile_id == parser.worker_profile_id
    assert {entry.mime_type for entry in matrix.entries} == set(parser.supported_mime_types)
    assert Counter(entry.format_id for entry in matrix.entries) == {"ooxml_docx": 5, "odf_odt": 4, "pdf": 4}
    assert Counter(entry.state for entry in matrix.entries) == {
        "text_supported": 2,
        "text_flattened": 3,
        "blocked_active_content": 3,
        "visible_review_marker": 3,
        "unsupported": 2,
    }
    assert all(not entry.fidelity_preserved for entry in matrix.entries)
    assert any(entry.feature_id == "vba_activex_ole_and_external_templates" for entry in matrix.entries)
    assert any(entry.feature_id == "basic_scripts_event_listeners_and_script_uris" for entry in matrix.entries)
    assert any(entry.feature_id == "javascript_launch_actions_and_embedded_files" for entry in matrix.entries)
    assert macro.active_content_detection_enforced_by_parser and not macro.active_content_execution_allowed
    assert not matrix.content_accepted_by_matrix_endpoint
    assert not matrix.import_dispatch_allowed and not matrix.export_allowed
    assert not matrix.round_trip_fidelity_claimed and not matrix.production_admitted
