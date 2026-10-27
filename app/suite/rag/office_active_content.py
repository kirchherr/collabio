from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Literal
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from suite.rag.parser_worker import ParserInputTooLargeError, ParserWorkerError

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCM_MIME_TYPE = "application/vnd.ms-word.document.macroenabled.12"
ODT_MIME_TYPE = "application/vnd.oasis.opendocument.text"
PDF_MIME_TYPE = "application/pdf"

OfficeActiveContentDecision = Literal["allow", "allow_marked", "block"]


class OfficeActiveContentBlockedError(ParserWorkerError):
    pass


@dataclass(frozen=True)
class OfficeActiveContentInspection:
    decision: OfficeActiveContentDecision
    blocking_indicators: tuple[str, ...]
    review_markings: tuple[str, ...]
    extraction_allowed: bool
    execution_allowed: bool = False
    automatic_removal_allowed: bool = False


def inspect_office_active_content(
    *,
    mime_type: str,
    content: bytes,
    max_archive_uncompressed_bytes: int = 20_000_000,
    max_control_part_bytes: int = 20_000_000,
) -> OfficeActiveContentInspection:
    if mime_type in {DOCX_MIME_TYPE, DOCM_MIME_TYPE}:
        blocked, marked = _inspect_docx(
            content,
            max_archive_uncompressed_bytes=max_archive_uncompressed_bytes,
            max_control_part_bytes=max_control_part_bytes,
        )
        if mime_type == DOCM_MIME_TYPE:
            blocked.add("docx_macro_enabled_mime")
    elif mime_type == ODT_MIME_TYPE:
        blocked, marked = _inspect_odt(
            content,
            max_archive_uncompressed_bytes=max_archive_uncompressed_bytes,
            max_control_part_bytes=max_control_part_bytes,
        )
    elif mime_type == PDF_MIME_TYPE:
        blocked, marked = _inspect_pdf(content)
    else:
        raise ParserWorkerError("office active-content policy received an unsupported mime type")

    blocking_indicators = tuple(sorted(blocked))
    review_markings = tuple(sorted(marked))
    decision: OfficeActiveContentDecision
    if blocking_indicators:
        decision = "block"
    elif review_markings:
        decision = "allow_marked"
    else:
        decision = "allow"
    return OfficeActiveContentInspection(
        decision=decision,
        blocking_indicators=blocking_indicators,
        review_markings=review_markings,
        extraction_allowed=decision != "block",
    )


def enforce_office_active_content_policy(
    *,
    mime_type: str,
    content: bytes,
    max_archive_uncompressed_bytes: int = 20_000_000,
    max_control_part_bytes: int = 20_000_000,
) -> OfficeActiveContentInspection:
    inspection = inspect_office_active_content(
        mime_type=mime_type,
        content=content,
        max_archive_uncompressed_bytes=max_archive_uncompressed_bytes,
        max_control_part_bytes=max_control_part_bytes,
    )
    if not inspection.extraction_allowed:
        raise OfficeActiveContentBlockedError("office active-content policy blocked parser input")
    return inspection


def _safe_zip_inventory(
    content: bytes,
    *,
    max_archive_uncompressed_bytes: int,
) -> tuple[ZipFile, dict[str, ZipInfo], set[str]]:
    try:
        archive = ZipFile(BytesIO(content))
    except BadZipFile as exc:
        raise ParserWorkerError("office active-content input is not a valid zip container") from exc
    infos = archive.infolist()
    if sum(info.file_size for info in infos) > max_archive_uncompressed_bytes:
        archive.close()
        raise ParserInputTooLargeError("office active-content archive exceeds uncompressed byte limit")

    exact_names: set[str] = set()
    folded_names: dict[str, str] = {}
    safe_infos: dict[str, ZipInfo] = {}
    anomalies: set[str] = set()
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if (
            not name
            or "\\" in name
            or "\x00" in name
            or name.startswith("/")
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or (path.parts and ":" in path.parts[0])
        ):
            anomalies.add("unsafe_archive_structure")
            continue
        folded = name.casefold()
        if name in exact_names or (folded in folded_names and folded_names[folded] != name):
            anomalies.add("ambiguous_archive_structure")
            continue
        exact_names.add(name)
        folded_names[folded] = name
        if info.flag_bits & 1:
            anomalies.add("encrypted_archive_entry")
            continue
        if info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
            anomalies.add("unsupported_archive_compression")
            continue
        safe_infos[folded] = info
    return archive, safe_infos, anomalies


def _read_control_part(archive: ZipFile, info: ZipInfo, *, maximum: int) -> bytes:
    if info.file_size > maximum:
        raise ParserInputTooLargeError("office active-content control part exceeds byte limit")
    try:
        with archive.open(info) as handle:
            value = handle.read(maximum + 1)
    except (BadZipFile, RuntimeError, OSError, NotImplementedError) as exc:
        raise ParserWorkerError("office active-content control part cannot be read") from exc
    if len(value) > maximum:
        raise ParserInputTooLargeError("office active-content control part exceeds byte limit")
    return value.lower()


def _inspect_docx(
    content: bytes,
    *,
    max_archive_uncompressed_bytes: int,
    max_control_part_bytes: int,
) -> tuple[set[str], set[str]]:
    archive, infos, blocked = _safe_zip_inventory(
        content, max_archive_uncompressed_bytes=max_archive_uncompressed_bytes
    )
    marked: set[str] = set()
    try:
        for name in infos:
            if name.endswith("vbaproject.bin"):
                blocked.add("docx_vba_project")
            if "/activex/" in name:
                blocked.add("docx_activex")
            if "/embeddings/" in name:
                blocked.add("docx_embedded_object")
            if name.startswith("_xmlsignatures/") or name.endswith("origin.sigs"):
                marked.add("digital_signature_present")
        for name, info in infos.items():
            if name == "[content_types].xml" or name.endswith(".rels"):
                value = _read_control_part(archive, info, maximum=max_control_part_bytes)
                if any(marker in value for marker in (b"macroenabled", b"vbaproject", b"activex")):
                    blocked.add("docx_active_content_declaration")
                if any(marker in value for marker in (b"oleobject", b"relationships/package")):
                    blocked.add("docx_embedded_object_declaration")
                if b"attachedtemplate" in value:
                    blocked.add("docx_template_relationship")
                if b'targetmode="external"' in value and b"hyperlink" in value:
                    marked.add("external_hyperlink_present")
    finally:
        archive.close()
    return blocked, marked


def _inspect_odt(
    content: bytes,
    *,
    max_archive_uncompressed_bytes: int,
    max_control_part_bytes: int,
) -> tuple[set[str], set[str]]:
    archive, infos, blocked = _safe_zip_inventory(
        content, max_archive_uncompressed_bytes=max_archive_uncompressed_bytes
    )
    marked: set[str] = set()
    try:
        for name in infos:
            if name.startswith(("basic/", "scripts/")):
                blocked.add("odf_macro_or_script_part")
            if name in {"meta-inf/documentsignatures.xml", "meta-inf/macrosignatures.xml"}:
                marked.add("digital_signature_present")
        for name in ("content.xml", "meta-inf/manifest.xml"):
            info = infos.get(name)
            if info is None:
                continue
            value = _read_control_part(archive, info, maximum=max_control_part_bytes)
            if any(
                marker in value
                for marker in (
                    b"office:scripts",
                    b"script:event-listener",
                    b"dom:event-listener",
                    b"application/vnd.sun.star.script",
                    b"application/vnd.sun.star.basic",
                    b"vnd.sun.star.script:",
                )
            ):
                blocked.add("odf_macro_or_event_script")
            if b"xlink:href=" in value and any(scheme in value for scheme in (b"http:", b"https:")):
                marked.add("external_hyperlink_present")
    finally:
        archive.close()
    return blocked, marked


def _inspect_pdf(content: bytes) -> tuple[set[str], set[str]]:
    blocked: set[str] = set()
    marked: set[str] = set()
    if re.search(rb"/(?:JavaScript|JS|Launch|OpenAction|AA)\b", content, flags=re.IGNORECASE):
        blocked.add("pdf_active_action")
    if re.search(rb"/EmbeddedFiles?\b", content, flags=re.IGNORECASE):
        blocked.add("pdf_embedded_file")
    if re.search(rb"/Type\s*/Sig\b", content, flags=re.IGNORECASE):
        marked.add("digital_signature_present")
    if re.search(rb"/URI\s*\(", content, flags=re.IGNORECASE):
        marked.add("external_hyperlink_present")
    return blocked, marked
