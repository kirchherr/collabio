from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from suite.platform.preview_cdr import (
    ZERO_HASH,
    PreviewCdrBundleManifest,
    PreviewCdrPageManifest,
    PreviewCdrValidationError,
    build_preview_cdr_manifest_hash,
    require_preview_cdr_bundle,
)
from suite.platform.source_object_preview_conversion_worker import (
    PreviewConversionWorkerError,
    _read_poppler_ppm,
)
from suite.storage.source_objects import sha256_bytes

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
RGB_BYTES = bytes((255, 0, 0, 0, 255, 0))


def test_cdr_manifest_is_hash_bound_metadata_only_and_validates_exact_rgb_bundle(tmp_path: Path) -> None:
    manifest = _manifest(RGB_BYTES)
    _write_bundle(tmp_path, manifest, RGB_BYTES)

    page_paths = require_preview_cdr_bundle(
        manifest=manifest,
        bundle_dir=tmp_path,
        maximum_raw_rgb_bytes=1024,
    )

    assert page_paths == (tmp_path / "page-000001.rgb",)
    assert manifest.manifest_hash == build_preview_cdr_manifest_hash(manifest)
    serialized = manifest.model_dump_json()
    assert RGB_BYTES.hex() not in serialized
    assert manifest.source_content_in_manifest is False
    assert manifest.active_content_preserved is False
    assert manifest.external_network_used is False


def test_cdr_bundle_rejects_page_tampering_and_unexpected_entries(tmp_path: Path) -> None:
    manifest = _manifest(RGB_BYTES)
    _write_bundle(tmp_path, manifest, RGB_BYTES)
    (tmp_path / "page-000001.rgb").write_bytes(bytes((0, 0, 0, 0, 0, 0)))

    with pytest.raises(PreviewCdrValidationError, match="hash mismatch"):
        require_preview_cdr_bundle(manifest=manifest, bundle_dir=tmp_path, maximum_raw_rgb_bytes=1024)

    (tmp_path / "page-000001.rgb").write_bytes(RGB_BYTES)
    (tmp_path / "unexpected.bin").write_bytes(b"x")
    with pytest.raises(PreviewCdrValidationError, match="unexpected"):
        require_preview_cdr_bundle(manifest=manifest, bundle_dir=tmp_path, maximum_raw_rgb_bytes=1024)


def test_cdr_manifest_rejects_inconsistent_dimensions_and_active_content_claim() -> None:
    valid = _manifest(RGB_BYTES).model_dump(mode="json")
    page = valid["pages"][0]
    assert isinstance(page, dict)
    page["rgb_byte_length"] = 3

    with pytest.raises(ValidationError, match="dimensions"):
        PreviewCdrBundleManifest.model_validate(valid)

    active = _manifest(RGB_BYTES).model_dump(mode="json")
    active["active_content_preserved"] = True
    with pytest.raises(ValidationError, match="disarm boundary"):
        PreviewCdrBundleManifest.model_validate(active)


def test_poppler_ppm_parser_accepts_only_bounded_raw_rgb(tmp_path: Path) -> None:
    page_path = tmp_path / "page.ppm"
    page_path.write_bytes(b"P6\n2 1\n255\n" + RGB_BYTES)

    assert _read_poppler_ppm(page_path) == (2, 1, RGB_BYTES)

    page_path.write_bytes(b"P6\n2 1\n255\n" + RGB_BYTES[:-1])
    with pytest.raises(PreviewConversionWorkerError, match="RGB length"):
        _read_poppler_ppm(page_path)


def _manifest(rgb_bytes: bytes) -> PreviewCdrBundleManifest:
    page = PreviewCdrPageManifest(
        page_number=1,
        width_pixels=2,
        height_pixels=1,
        rgb_content_hash=sha256_bytes(rgb_bytes),
        rgb_byte_length=len(rgb_bytes),
    )
    draft = PreviewCdrBundleManifest(
        tenant_id="tenant-demo",
        source_object_id="doc-1",
        source_version_id="v1",
        source_manifest_hash="sha256:" + ("1" * 64),
        source_content_hash="sha256:" + ("2" * 64),
        command_hash="sha256:" + ("3" * 64),
        execution_gate_evidence_hash="sha256:" + ("4" * 64),
        source_preflight_evidence_hash="sha256:" + ("5" * 64),
        worker_image_ref="registry.example.com/collabio/preview@sha256:" + ("6" * 64),
        document_converter_version="LibreOffice 25.8.7.3",
        rasterizer_version="pdftoppm version 25.12.0",
        font_baseline_hash="sha256:" + ("7" * 64),
        page_count=1,
        raw_rgb_byte_length=len(rgb_bytes),
        pages=(page,),
        completed_at_utc=NOW,
        manifest_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"manifest_hash": build_preview_cdr_manifest_hash(draft)})


def _write_bundle(directory: Path, manifest: PreviewCdrBundleManifest, rgb_bytes: bytes) -> None:
    (directory / "page-000001.rgb").write_bytes(rgb_bytes)
    (directory / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
