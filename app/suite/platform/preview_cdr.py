from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.storage.source_objects import sha256_bytes

PREVIEW_CDR_MANIFEST_SCHEMA_VERSION = "source_object_preview_cdr_rgb_manifest.v1"
PREVIEW_CDR_PROFILE_REF = "collabio-pixel-cdr:raw-rgb.v1"
ZERO_HASH = "sha256:" + ("0" * 64)
SHA256_REF_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
PAGE_FILENAME_PATTERN = re.compile(r"^page-(\d{6})\.rgb$")


class PreviewCdrValidationError(ValueError):
    pass


class PreviewCdrPageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1, le=10000)
    width_pixels: int = Field(ge=1, le=4096)
    height_pixels: int = Field(ge=1, le=4096)
    rgb_content_hash: str
    rgb_byte_length: int = Field(ge=3, le=4096 * 4096 * 3)

    @field_validator("rgb_content_hash")
    @classmethod
    def require_sha256_ref(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("preview CDR page hash must be a sha256 reference")
        return value

    @model_validator(mode="after")
    def require_exact_rgb_length(self) -> PreviewCdrPageManifest:
        if self.rgb_byte_length != self.width_pixels * self.height_pixels * 3:
            raise ValueError("preview CDR RGB byte length does not match page dimensions")
        return self

    @property
    def filename(self) -> str:
        return f"page-{self.page_number:06d}.rgb"


class PreviewCdrBundleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = PREVIEW_CDR_MANIFEST_SCHEMA_VERSION
    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_manifest_hash: str
    source_content_hash: str
    command_hash: str
    execution_gate_evidence_hash: str
    source_preflight_evidence_hash: str
    worker_image_ref: str
    cdr_profile_ref: str = PREVIEW_CDR_PROFILE_REF
    document_converter_engine: str = "libreoffice"
    document_converter_version: str
    rasterizer_engine: str = "pdftoppm"
    rasterizer_version: str
    font_baseline_hash: str
    raster_dpi: int = Field(default=144, ge=72, le=300)
    maximum_page_dimension_pixels: int = Field(default=4096, ge=512, le=4096)
    page_count: int = Field(ge=1, le=10000)
    raw_rgb_byte_length: int = Field(ge=3, le=4 * 1024 * 1024 * 1024)
    pages: tuple[PreviewCdrPageManifest, ...]
    source_content_in_manifest: bool = False
    active_content_preserved: bool = False
    external_network_used: bool = False
    completed_at_utc: datetime
    manifest_hash: str

    @field_validator("tenant_id", "source_object_id", "source_version_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("preview CDR identity values must not be empty")
        return normalized

    @field_validator(
        "source_manifest_hash",
        "source_content_hash",
        "command_hash",
        "execution_gate_evidence_hash",
        "source_preflight_evidence_hash",
        "font_baseline_hash",
        "manifest_hash",
    )
    @classmethod
    def require_sha256_ref(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("preview CDR hashes must be sha256 references")
        return value

    @field_validator("worker_image_ref")
    @classmethod
    def require_digest_pinned_image(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._/:+-]*@sha256:[a-f0-9]{64}", normalized):
            raise ValueError("preview CDR worker image must be digest pinned")
        return normalized

    @model_validator(mode="after")
    def require_closed_manifest(self) -> PreviewCdrBundleManifest:
        if self.cdr_profile_ref != PREVIEW_CDR_PROFILE_REF:
            raise ValueError("preview CDR profile is unsupported")
        if self.page_count != len(self.pages):
            raise ValueError("preview CDR page count does not match manifest pages")
        if tuple(page.page_number for page in self.pages) != tuple(range(1, self.page_count + 1)):
            raise ValueError("preview CDR pages must be contiguous and ordered")
        if self.raw_rgb_byte_length != sum(page.rgb_byte_length for page in self.pages):
            raise ValueError("preview CDR aggregate RGB byte length is inconsistent")
        if self.source_content_in_manifest or self.active_content_preserved or self.external_network_used:
            raise ValueError("preview CDR manifest violates the content disarm boundary")
        return self


def build_preview_cdr_manifest_hash(manifest: PreviewCdrBundleManifest) -> str:
    return stable_hash(canonical_json(manifest.model_dump(mode="json", exclude={"manifest_hash"})))


def require_preview_cdr_bundle(
    *,
    manifest: PreviewCdrBundleManifest,
    bundle_dir: Path,
    maximum_raw_rgb_bytes: int,
) -> tuple[Path, ...]:
    if manifest.manifest_hash != build_preview_cdr_manifest_hash(manifest):
        raise PreviewCdrValidationError("preview CDR manifest hash is invalid")
    if manifest.raw_rgb_byte_length > maximum_raw_rgb_bytes:
        raise PreviewCdrValidationError("preview CDR bundle exceeds admitted temporary storage")

    resolved_dir = bundle_dir.resolve()
    if bundle_dir.is_symlink() or not resolved_dir.is_dir():
        raise PreviewCdrValidationError("preview CDR bundle directory is invalid")
    expected_names = {"manifest.json", *(page.filename for page in manifest.pages)}
    entries = tuple(resolved_dir.iterdir())
    if {entry.name for entry in entries} != expected_names:
        raise PreviewCdrValidationError("preview CDR bundle contains unexpected or missing entries")
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise PreviewCdrValidationError("preview CDR bundle entries must be regular files")

    page_paths: list[Path] = []
    total_bytes = 0
    for page in manifest.pages:
        page_path = (resolved_dir / page.filename).resolve()
        if page_path.parent != resolved_dir or not PAGE_FILENAME_PATTERN.fullmatch(page_path.name):
            raise PreviewCdrValidationError("preview CDR page path escaped the bundle")
        rgb_bytes = page_path.read_bytes()
        total_bytes += len(rgb_bytes)
        if len(rgb_bytes) != page.rgb_byte_length:
            raise PreviewCdrValidationError("preview CDR page byte length mismatch")
        if sha256_bytes(rgb_bytes) != page.rgb_content_hash:
            raise PreviewCdrValidationError("preview CDR page content hash mismatch")
        page_paths.append(page_path)
    if total_bytes != manifest.raw_rgb_byte_length:
        raise PreviewCdrValidationError("preview CDR bundle byte length mismatch")
    return tuple(page_paths)
