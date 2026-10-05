"""Exact restoration of every retained rendition and every saved image reference."""

from collections.abc import Mapping
from typing import Any

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.platform.office_documents import OfficeDocumentService
from suite.platform.office_images import read_image
from suite.storage.source_objects import (
    SourceObjectRepository,
    SourceObjectWriteReceiptStore,
    build_source_object_write_receipt_hash,
)


def verify_restored_crop_reset(bindings: list[dict[str, Any]]) -> dict[str, Any]:
    cropped = [binding for binding in bindings if binding["crop"] is not None]
    predecessors = {
        (binding["object_id"], binding["asset_id"], binding["asset_version_id"], binding["document_version_id"])
        for binding in cropped
    }
    if not any(
        binding["crop"] is None
        and (
            binding["object_id"],
            binding["asset_id"],
            binding["asset_version_id"],
            binding["previous_document_version_id"],
        )
        in predecessors
        for binding in bindings
    ):
        raise ValueError("Crop recovery requires a reset version following a crop of the same image")
    return {
        "verified_cropped_image_reference_count": len(cropped),
        "cropped_and_reset_versions_verified": True,
    }


def verify_restored_wrap_reset(bindings: list[dict[str, Any]]) -> dict[str, Any]:
    def identity(binding: dict[str, Any], previous: bool = False) -> tuple[str, ...]:
        return tuple(
            binding[key]
            for key in (
                "object_id",
                "asset_id",
                "asset_version_id",
                "previous_document_version_id" if previous else "document_version_id",
            )
        )

    left = {identity(row): row for row in bindings if (row.get("wrap") or {}).get("side") == "left"}
    right: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in bindings:
        predecessor = left.get(identity(row, True))
        if (row.get("wrap") or {}).get("side") == "right" and predecessor and row["crop"] == predecessor["crop"]:
            right[identity(row)] = row
    if not any(
        row.get("wrap") is None and identity(row, True) in right and row["crop"] == right[identity(row, True)]["crop"]
        for row in bindings
    ):
        raise ValueError("Wrap recovery requires consecutive left/right/reset versions of the same cropped image")
    return {
        "verified_wrapped_image_reference_count": sum(row.get("wrap") is not None for row in bindings),
        "wrapped_and_reset_versions_verified": True,
    }


def verify_restored_position_reset(bindings: list[dict[str, Any]]) -> dict[str, Any]:
    def identity(binding: dict[str, Any], previous: bool = False) -> tuple[str, ...]:
        return tuple(
            binding[key]
            for key in (
                "object_id",
                "asset_id",
                "asset_version_id",
                "previous_document_version_id" if previous else "document_version_id",
            )
        )

    front = {identity(row): row for row in bindings if (row.get("position") or {}).get("layer") == "front"}
    behind: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in bindings:
        predecessor = front.get(identity(row, True))
        if (
            (row.get("position") or {}).get("layer") == "behind"
            and predecessor
            and row["crop"] == predecessor["crop"]
            and row.get("wrap") is None
            and predecessor.get("wrap") is None
        ):
            behind[identity(row)] = row
    if not any(
        row.get("position") is None
        and identity(row, True) in behind
        and row["crop"] == behind[identity(row, True)]["crop"]
        and row.get("wrap") is None
        for row in bindings
    ):
        raise ValueError("Position recovery requires consecutive front/behind/reset versions of the same image")
    return {
        "verified_positioned_image_reference_count": sum(row.get("position") is not None for row in bindings),
        "positioned_and_reset_versions_verified": True,
    }


def verify_restored_transform_reset(bindings: list[dict[str, Any]]) -> dict[str, Any]:
    def identity(binding: dict[str, Any], previous: bool = False) -> tuple[str, ...]:
        return tuple(
            binding[key]
            for key in (
                "object_id",
                "asset_id",
                "asset_version_id",
                "previous_document_version_id" if previous else "document_version_id",
            )
        )

    rotated = {
        identity(row): row
        for row in bindings
        if row.get("transform") == {"rotation": 90, "flipX": True, "flipY": False}
    }
    mirrored: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in bindings:
        predecessor = rotated.get(identity(row, True))
        if (
            row.get("transform") == {"rotation": 270, "flipX": True, "flipY": True}
            and predecessor
            and all(row.get(key) == predecessor.get(key) for key in ("crop", "wrap", "position"))
        ):
            mirrored[identity(row)] = row
    if not any(
        row.get("transform") is None
        and identity(row, True) in mirrored
        and all(row.get(key) == mirrored[identity(row, True)].get(key) for key in ("crop", "wrap", "position"))
        for row in bindings
    ):
        raise ValueError("Transform recovery requires consecutive rotate/mirror/reset versions of the same image")
    return {
        "verified_transformed_image_reference_count": sum(row.get("transform") is not None for row in bindings),
        "transformed_and_reset_versions_verified": True,
    }


def verify_restored_group_reset(versions: list[dict[str, Any]]) -> dict[str, Any]:
    def identity(row: dict[str, Any], previous: bool = False) -> tuple[str, str | None]:
        return row["object_id"], row["previous_document_version_id" if previous else "document_version_id"]

    rows = {
        identity(row): row
        for row in versions
        if len(row["groups"]) == 1
        and row["groups"][0]["layout"] == "row"
        and row["groups"][0]["gap"] == 12
        and len(row["groups"][0]["images"]) == 3
    }
    stacks: dict[tuple[str, str | None], dict[str, Any]] = {}
    for row in versions:
        predecessor = rows.get(identity(row, True))
        if (
            len(row["groups"]) == 1
            and row["groups"][0]["layout"] == "stack"
            and row["groups"][0]["gap"] == 24
            and predecessor
            and row["groups"][0]["id"] == predecessor["groups"][0]["id"]
            and row["groups"][0]["images"] == predecessor["groups"][0]["images"]
        ):
            stacks[identity(row)] = row
    if not any(
        not row["groups"]
        and identity(row, True) in stacks
        and row["images"] == stacks[identity(row, True)]["groups"][0]["images"]
        for row in versions
    ):
        raise ValueError("Image group recovery requires consecutive row/stack/reset versions of the same images")
    return {
        "verified_grouped_document_version_count": sum(bool(row["groups"]) for row in versions),
        "grouped_arranged_and_reset_versions_verified": True,
    }


def verify_restored_group_duplicate(versions: list[dict[str, Any]], bindings: list[dict[str, Any]]) -> dict[str, Any]:
    hashes = {
        (row["object_id"], row["document_version_id"], row["asset_id"], row["asset_version_id"]): row["content_hash"]
        for row in bindings
    }
    verified = 0
    for row in versions:
        for source, copied in zip(row["groups"], row["groups"][1:], strict=False):
            source_images, copied_images = source["images"], copied["images"]
            if (
                source["id"] == copied["id"]
                or source["layout"] != copied["layout"]
                or source["gap"] != copied["gap"]
                or len(source_images) != len(copied_images)
                or not 2 <= len(source_images) <= 8
                or set(source_images) & set(copied_images)
            ):
                continue
            source_hashes = [
                hashes.get((row["object_id"], row["document_version_id"], *image)) for image in source_images
            ]
            copied_hashes = [
                hashes.get((row["object_id"], row["document_version_id"], *image)) for image in copied_images
            ]
            if None not in source_hashes and source_hashes == copied_hashes:
                verified += 1
    if verified < 1:
        raise ValueError("Image group duplicate recovery requires distinct assets with identical ordered pixels")
    return {
        "verified_duplicated_image_group_count": verified,
        "independently_owned_group_duplicate_verified": True,
    }


def verify_restored_image_duplicate(versions: list[dict[str, Any]], bindings: list[dict[str, Any]]) -> dict[str, Any]:
    hashes = {
        (row["object_id"], row["document_version_id"], row["asset_id"], row["asset_version_id"]): row["content_hash"]
        for row in bindings
    }
    verified = 0
    for row in versions:
        for source, copied in zip(row["standalone_images"], row["standalone_images"][1:], strict=False):
            source_identity = (source["asset_id"], source["asset_version_id"])
            copied_identity = (copied["asset_id"], copied["asset_version_id"])
            if (
                source_identity == copied_identity
                or source.get("figure_id") is None
                or copied.get("figure_id") is None
                or source["figure_id"] == copied["figure_id"]
                or source.get("position") != {"layer": "front", "x": 980, "y": 1190}
                or copied.get("position") != {"layer": "front", "x": 940, "y": 1166}
            ):
                continue
            source_hash = hashes.get((row["object_id"], row["document_version_id"], *source_identity))
            copied_hash = hashes.get((row["object_id"], row["document_version_id"], *copied_identity))
            if source_hash is not None and source_hash == copied_hash:
                verified += 1
    if verified < 1:
        raise ValueError("Image duplicate recovery requires distinct assets, figures and bounded placement")
    return {
        "verified_duplicated_image_count": verified,
        "independently_owned_image_duplicate_verified": True,
    }


def verify_restored_images(
    *,
    documents: OfficeDocumentService,
    readers: Mapping[str, UserContext],
    original_sources: SourceObjectRepository,
    restored_sources: SourceObjectRepository,
    receipts: SourceObjectWriteReceiptStore,
    images: list[Any],
    bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    if not images or not bindings:
        raise ValueError("Office image recovery requires nonempty saved image references")
    inventory = {(row["object_id"], row["version_id"]): row for row in images}
    if len(inventory) != len(images):
        raise ValueError("Office image recovery inventory is ambiguous")
    for binding in bindings:
        row = inventory.get((binding["asset_id"], binding["asset_version_id"]))
        if (
            row is None
            or row["parent_object_id"] != binding["object_id"]
            or (row["content_hash"] != binding["content_hash"] or row["manifest_hash"] != binding["manifest_hash"])
        ):
            raise ValueError("Office image reference does not match restored inventory")
    evidence: list[dict[str, str]] = []
    for row in images:
        parent = row["parent_object_id"]
        document = documents.repository.get_document(user_context=readers[parent], object_id=parent)
        attrs = {
            "documentId": parent,
            "assetId": row["object_id"],
            "versionId": row["version_id"],
            "contentHash": row["content_hash"],
            "manifestHash": row["manifest_hash"],
        }
        original, source_bytes = read_image(original_sources, document, attrs)
        restored, restored_bytes = read_image(restored_sources, document, attrs)
        receipt = receipts.get(tenant_id=document.tenant_id, receipt_hash=row["source_object_write_receipt_hash"])
        if (
            original != restored
            or source_bytes != restored_bytes
            or (
                receipt.receipt_hash != build_source_object_write_receipt_hash(receipt)
                or receipt.object_id != restored.object_id
                or receipt.version_id != restored.version_id
                or receipt.content_hash != restored.content_hash
                or receipt.manifest_hash != restored.manifest_hash
            )
        ):
            raise ValueError("Office image bytes or receipt binding differ after restore")
        evidence.append(
            {
                "object_id": restored.object_id,
                "version_id": restored.version_id,
                "content_hash": restored.content_hash,
                "receipt_hash": receipt.receipt_hash,
            }
        )
    return {
        "verified_image_asset_count": len(evidence),
        "verified_saved_image_reference_count": len(bindings),
        "image_asset_evidence_hash": stable_hash(canonical_json(evidence)),
        "image_reference_evidence_hash": stable_hash(canonical_json(bindings)),
        "image_bytes_and_receipts_verified": True,
    }
