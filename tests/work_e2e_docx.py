"""Stored synthetic DOCX fixture; never installed in the product API."""

from __future__ import annotations

import os
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import psycopg

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass
from suite.rag.rich_document_parser import DOCX_MIME_TYPE
from suite.storage.s3_sdk_client import build_boto3_s3_compatible_client
from suite.storage.source_objects import (
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
    sha256_bytes,
)
from suite.testing.work_e2e_guard import WORK_E2E_TENANT_ID, require_isolated_work_e2e_environment
from work_e2e_controls import WORK_E2E_OFFICE_EDITOR_ID
from work_e2e_office import build_synthetic_office_service

SOURCE_ID = "work-e2e-stored-docx"
SOURCE_VERSION = "stored-docx-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle"
SECTION_SOURCE_ID = SOURCE_ID + "-sections"
SECTION_VERSION = "stored-docx-sections-v1"
SECTION_TITLE = SOURCE_TITLE + " mit Abschnitten"
_TEXT_BODY = (
    '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
    "<w:r><w:rPr><w:b/></w:rPr><w:t>Gespeicherte Quelle im echten Parser</w:t></w:r></w:p>"
    '<w:p><w:r><w:t>Vor dem Seitenwechsel</w:t><w:br w:type="page"/>'
    "<w:t>Nach dem Seitenwechsel</w:t></w:r></w:p>"
    "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Exakte Version</w:t></w:r></w:p></w:tc>"
    "<w:tc><w:p><w:r><w:t>Unveraendert</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
)
FIRST_SECTION = (
    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
    '<w:pgMar w:top="1134" w:right="680" w:bottom="1247" w:left="794" w:gutter="0"/></w:sectPr>'
)
LAST_SECTION = (
    '<w:sectPr><w:type w:val="nextPage"/><w:pgSz w:w="15840" w:h="12240" w:orient="landscape"/>'
    '<w:pgMar w:top="1020" w:right="907" w:bottom="1134" w:left="1020" w:header="720" w:footer="720"/>'
    '<w:cols w:num="2" w:space="720" w:equalWidth="1"/></w:sectPr>'
)


def synthetic_docx(*, body: str = _TEXT_BODY) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            ZipInfo("[Content_Types].xml"),
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            ZipInfo("word/document.xml"),
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
            f"{body}</w:body></w:document>",
        )
    return output.getvalue()


def section_docx() -> bytes:
    return synthetic_docx(
        body=f"<w:p><w:pPr>{FIRST_SECTION}</w:pPr><w:r><w:t>Erster Abschnitt auf A4</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Zweiter Abschnitt auf Letter</w:t></w:r></w:p>"
        f"{LAST_SECTION}"
    )


def main(
    *,
    content: bytes | None = None,
    source_id: str = SOURCE_ID,
    version: str = SOURCE_VERSION,
    title: str = SOURCE_TITLE,
) -> None:
    require_isolated_work_e2e_environment(os.environ)
    client = build_boto3_s3_compatible_client(
        endpoint_url=os.environ["SUITE_S3_ENDPOINT_URL"],
        access_key_id=os.environ["SUITE_S3_ACCESS_KEY_ID"],
        secret_access_key=os.environ["SUITE_S3_SECRET_ACCESS_KEY"],
        storage_provider="minio",
    )
    service = build_synthetic_office_service(
        database_dsn=os.environ["SUITE_DATABASE_DSN"], client=client, audit=InMemoryAuditLogger()
    )
    content = synthetic_docx() if content is None else content
    metadata = SourceObjectMetadata(
        tenant_id=WORK_E2E_TENANT_ID,
        object_id=source_id,
        version_id=version,
        object_type=SourceObjectType.DOCUMENT,
        title=title,
        owner_principal_id=WORK_E2E_OFFICE_EDITOR_ID,
        created_by=WORK_E2E_OFFICE_EDITOR_ID,
        created_at_utc="2026-10-27T10:00:00Z",
        updated_at_utc="2026-10-27T10:00:00Z",
        classification=DataClass.CONFIDENTIAL,
        retention_policy_id="rp-standard",
        kms_key_ref=f"kms://{WORK_E2E_TENANT_ID}/confidential/v1",
        manifest_hash="sha256:" + "0" * 64,
        audit_chain_ref="audit:work-e2e-stored-docx",
        source_system="work_e2e_synthetic_docx",
        mime_type=DOCX_MIME_TYPE,
        acl_hash=sha256_bytes(b"synthetic-editor-only"),
        acl_version=1,
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        lifecycle_state=SourceLifecycleState.SAVED_VERSION,
    )
    metadata = metadata.model_copy(update={"manifest_hash": build_source_object_manifest_hash(metadata)})
    try:
        existing = service.source_repository.get_metadata(  # type: ignore[attr-defined]
            tenant_id=WORK_E2E_TENANT_ID, object_id=source_id, version_id=version
        )
        if existing.content_hash != metadata.content_hash:
            raise ValueError("Synthetic DOCX fixture identity collision")
    except KeyError:
        service.source_repository.add(SourceObjectRecord(metadata=metadata, content_bytes=content))
    with psycopg.connect(os.environ["SUITE_AUTHZ_ADMIN_DATABASE_DSN"]) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (WORK_E2E_TENANT_ID,))
        connection.execute(
            "INSERT INTO collabio.object_acl_entries "
            "(tenant_id, object_id, object_type, acl_subject_type, acl_subject_id, permission, acl_version, "
            "audit_chain_ref) VALUES (%s, %s, 'document', 'user', %s, 'read', 1, %s) ON CONFLICT DO NOTHING",
            (WORK_E2E_TENANT_ID, source_id, WORK_E2E_OFFICE_EDITOR_ID, "audit:work-e2e-docx-acl"),
        )


def seed_stored_docx_sources(*, report: bool = False) -> None:
    main()
    from docx_font_family_fixture import SOURCE_ID as font_family_source_id
    from docx_font_family_fixture import SOURCE_TITLE as font_family_source_title
    from docx_font_family_fixture import SOURCE_VERSION as font_family_source_version
    from docx_font_family_fixture import font_family_docx
    from docx_font_size_fixture import SOURCE_ID as font_size_source_id
    from docx_font_size_fixture import SOURCE_TITLE as font_size_source_title
    from docx_font_size_fixture import SOURCE_VERSION as font_size_source_version
    from docx_font_size_fixture import font_size_docx
    from docx_image_fixture import image_docx
    from docx_list_fixture import SOURCE_ID as list_source_id
    from docx_list_fixture import SOURCE_TITLE as list_source_title
    from docx_list_fixture import SOURCE_VERSION as list_source_version
    from docx_list_fixture import list_docx
    from docx_navigation_fixture import SOURCE_ID as navigation_source_id
    from docx_navigation_fixture import SOURCE_TITLE as navigation_source_title
    from docx_navigation_fixture import SOURCE_VERSION as navigation_source_version
    from docx_navigation_fixture import navigation_docx
    from docx_paragraph_alignment_fixture import SOURCE_ID as alignment_source_id
    from docx_paragraph_alignment_fixture import SOURCE_TITLE as alignment_source_title
    from docx_paragraph_alignment_fixture import SOURCE_VERSION as alignment_source_version
    from docx_paragraph_alignment_fixture import paragraph_alignment_docx
    from docx_paragraph_indentation_fixture import SOURCE_ID as indentation_source_id
    from docx_paragraph_indentation_fixture import SOURCE_TITLE as indentation_source_title
    from docx_paragraph_indentation_fixture import SOURCE_VERSION as indentation_source_version
    from docx_paragraph_indentation_fixture import paragraph_indentation_docx
    from docx_paragraph_pagination_fixture import SOURCE_ID as pagination_source_id
    from docx_paragraph_pagination_fixture import SOURCE_TITLE as pagination_source_title
    from docx_paragraph_pagination_fixture import SOURCE_VERSION as pagination_source_version
    from docx_paragraph_pagination_fixture import paragraph_pagination_docx
    from docx_paragraph_spacing_fixture import SOURCE_ID as spacing_source_id
    from docx_paragraph_spacing_fixture import SOURCE_TITLE as spacing_source_title
    from docx_paragraph_spacing_fixture import SOURCE_VERSION as spacing_source_version
    from docx_paragraph_spacing_fixture import paragraph_spacing_docx
    from docx_running_fixture import SOURCE_ID as running_source_id
    from docx_running_fixture import SOURCE_TITLE as running_source_title
    from docx_running_fixture import SOURCE_VERSION as running_source_version
    from docx_running_fixture import running_docx
    from docx_table_header_fixture import SOURCE_ID as table_header_source_id
    from docx_table_header_fixture import SOURCE_TITLE as table_header_source_title
    from docx_table_header_fixture import SOURCE_VERSION as table_header_source_version
    from docx_table_header_fixture import table_header_docx
    from docx_table_span_fixture import SOURCE_ID as table_span_source_id
    from docx_table_span_fixture import SOURCE_TITLE as table_span_source_title
    from docx_table_span_fixture import SOURCE_VERSION as table_span_source_version
    from docx_table_span_fixture import table_span_docx
    from docx_text_color_fixture import SOURCE_ID as text_color_source_id
    from docx_text_color_fixture import SOURCE_TITLE as text_color_source_title
    from docx_text_color_fixture import SOURCE_VERSION as text_color_source_version
    from docx_text_color_fixture import text_color_docx

    main(
        content=image_docx(),
        source_id=SOURCE_ID + "-images",
        version="stored-docx-images-v1",
        title=SOURCE_TITLE + " mit Bildern",
    )
    main(content=section_docx(), source_id=SECTION_SOURCE_ID, version=SECTION_VERSION, title=SECTION_TITLE)
    main(
        content=running_docx(), source_id=running_source_id, version=running_source_version, title=running_source_title
    )
    main(
        content=navigation_docx(),
        source_id=navigation_source_id,
        version=navigation_source_version,
        title=navigation_source_title,
    )
    main(content=list_docx(), source_id=list_source_id, version=list_source_version, title=list_source_title)
    main(
        content=font_family_docx(),
        source_id=font_family_source_id,
        version=font_family_source_version,
        title=font_family_source_title,
    )
    main(
        content=text_color_docx(),
        source_id=text_color_source_id,
        version=text_color_source_version,
        title=text_color_source_title,
    )
    main(
        content=font_size_docx(),
        source_id=font_size_source_id,
        version=font_size_source_version,
        title=font_size_source_title,
    )
    main(
        content=paragraph_pagination_docx(),
        source_id=pagination_source_id,
        version=pagination_source_version,
        title=pagination_source_title,
    )
    main(
        content=paragraph_indentation_docx(),
        source_id=indentation_source_id,
        version=indentation_source_version,
        title=indentation_source_title,
    )
    main(
        content=paragraph_spacing_docx(),
        source_id=spacing_source_id,
        version=spacing_source_version,
        title=spacing_source_title,
    )
    main(
        content=paragraph_alignment_docx(),
        source_id=alignment_source_id,
        version=alignment_source_version,
        title=alignment_source_title,
    )
    main(
        content=table_header_docx(),
        source_id=table_header_source_id,
        version=table_header_source_version,
        title=table_header_source_title,
    )
    main(
        content=table_span_docx(),
        source_id=table_span_source_id,
        version=table_span_source_version,
        title=table_span_source_title,
    )
    if report:
        print('{"schema_version":"work_e2e_stored_docx.v1","synthetic_only":true}')


if __name__ == "__main__":
    seed_stored_docx_sources(report=True)
