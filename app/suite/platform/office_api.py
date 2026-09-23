from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.routing import APIRoute
from psycopg import Error as PsycopgError
from starlette.datastructures import MutableHeaders
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.context import TenantRequestContext
from suite.platform.modules import InMemoryModuleRegistry, ModuleGateSurface, ModuleLifecycleError
from suite.platform.office_access_logging import protect_office_discovery_access_logs
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository, PgOfficeDocumentRepository
from suite.platform.office_document_schema import OfficeDocumentInvalidContentError
from suite.platform.office_documents import (
    OFFICE_DOCUMENTS_MODULE_ID,
    OFFICE_DOCUMENTS_WRITE_FEATURE_ID,
    OfficeDocumentConflictError,
    OfficeDocumentContentResponse,
    OfficeDocumentCreateCommand,
    OfficeDocumentHistoryRequestError,
    OfficeDocumentHistoryResponse,
    OfficeDocumentListRequestError,
    OfficeDocumentListResponse,
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
    OfficeDocumentSaveCommand,
    OfficeDocumentService,
)
from suite.platform.office_image_codec import (
    MAX_IMAGE_INPUT,
    OfficeImageInvalid,
    OfficeImageUnavailable,
    normalize_image,
)
from suite.platform.office_images import read_image, store_uploaded_image
from suite.platform.office_review_repository import InMemoryOfficeReviewRepository, PgOfficeReviewRepository
from suite.platform.office_reviews import (
    OfficeReviewService,
    ReviewCreateCommand,
    ReviewDetailResponse,
    ReviewEventCommand,
    ReviewListResponse,
    ReviewMutationResponse,
)
from suite.platform.office_suggestion_repository import OfficeSuggestionRepositoryAdapter
from suite.platform.office_suggestions import (
    OfficeSuggestionService,
    SuggestionCreateCommand,
    SuggestionDecisionCommand,
    SuggestionDetailResponse,
    SuggestionListResponse,
    SuggestionMutationResponse,
)
from suite.storage.source_object_storage import PgSourceObjectRepository, SourceObjectStorageError
from suite.storage.source_objects import (
    InMemorySourceObjectRepository,
    PgSourceObjectWriteReceiptStore,
    SourceObjectRepository,
)

MAX_OFFICE_REQUEST_BYTES = 512_000
OFFICE_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; "
    "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class OfficeBoundaryMiddleware:
    """Bound JSON before parsing; protect Office errors and content from caching."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        protect_office_discovery_access_logs()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == "/office" or path.startswith(("/office/", "/v1/office/"))):
            await self.app(scope, receive, send)
            return

        async def protected_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Content-Security-Policy"] = OFFICE_CSP
            await send(message)

        if path.startswith("/v1/office/") and scope.get("method") == "POST":
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                maximum = MAX_IMAGE_INPUT if path.endswith("/images") else MAX_OFFICE_REQUEST_BYTES
                if len(body) > maximum:
                    await JSONResponse({"detail": "Document request is too large"}, status_code=413)(
                        scope, receive, protected_send
                    )
                    return
                if not message.get("more_body", False):
                    break
            consumed = False

            async def bounded_receive() -> Message:
                nonlocal consumed
                if consumed:
                    return await receive()
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            await self.app(scope, bounded_receive, protected_send)
        else:
            await self.app(scope, receive, protected_send)


class OfficeRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Any]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Any:
            try:
                return await handler(request)
            except (RequestValidationError, RecursionError):
                # FastAPI's default errors may echo whole document bodies.
                return JSONResponse({"detail": "Invalid document request"}, status_code=422)
            except OfficeDocumentNotFoundError:
                return JSONResponse({"detail": "Document not found"}, status_code=404)
            except OfficeDocumentListRequestError:
                return JSONResponse({"detail": "Invalid document list request"}, status_code=400)
            except OfficeDocumentHistoryRequestError:
                return JSONResponse({"detail": "Invalid version history request"}, status_code=400)
            except OfficeDocumentPermissionError:
                return JSONResponse({"detail": "Document write is not allowed"}, status_code=403)
            except OfficeDocumentConflictError:
                return JSONResponse(
                    {"detail": "The document has a newer or conflicting saved version"}, status_code=409
                )
            except (OfficeDocumentInvalidContentError, OfficeImageInvalid):
                return JSONResponse({"detail": "Document validation failed"}, status_code=400)
            except (SourceObjectStorageError, PsycopgError, OfficeImageUnavailable):
                return JSONResponse({"detail": "Office storage unavailable"}, status_code=503)

        return guarded


def build_office_document_service(
    *, source_repository: SourceObjectRepository, audit: InMemoryAuditLogger
) -> OfficeDocumentService:
    if isinstance(source_repository, PgSourceObjectRepository):
        repository = PgOfficeDocumentRepository(
            database_dsn=source_repository.database_dsn,
            source_repository=source_repository,
            receipt_store=PgSourceObjectWriteReceiptStore(database_dsn=source_repository.database_dsn),
        )
        return OfficeDocumentService(repository=repository, source_repository=source_repository, audit=audit)
    if not isinstance(source_repository, InMemorySourceObjectRepository):
        raise ValueError("Office requires an explicit supported source repository")
    return OfficeDocumentService(
        repository=InMemoryOfficeDocumentRepository(source_repository=source_repository),
        source_repository=source_repository,
        audit=audit,
        writes_available=False,
    )


def _write_enabled(request: Request, context: TenantRequestContext) -> bool:
    registry = cast(InMemoryModuleRegistry, request.app.state.module_registry)
    try:
        registry.require_module_gate(
            tenant_id=context.user_context.tenant_id,
            module_id=OFFICE_DOCUMENTS_MODULE_ID,
            surface=ModuleGateSurface.NORMAL_API,
            feature_id=OFFICE_DOCUMENTS_WRITE_FEATURE_ID,
        )
    except (LookupError, ModuleLifecycleError):
        return False
    return True


def build_office_review_service(
    *, document_service: OfficeDocumentService, audit: InMemoryAuditLogger
) -> OfficeReviewService:
    repository = (
        PgOfficeReviewRepository(document_service=document_service)
        if isinstance(document_service.repository, PgOfficeDocumentRepository)
        else InMemoryOfficeReviewRepository(document_service=document_service)
    )
    return OfficeReviewService(
        repository=repository,
        source_repository=document_service.source_repository,
        audit=audit,
        writes_available=document_service.writes_available,
    )


def build_office_suggestion_service(
    *,
    document_service: OfficeDocumentService,
    audit: InMemoryAuditLogger,
) -> OfficeSuggestionService:
    return OfficeSuggestionService(
        repository=OfficeSuggestionRepositoryAdapter(document_service=document_service),
        document_service=document_service,
        audit=audit,
    )


def register_office_routes(
    app: FastAPI,
    *,
    context_dependency: Callable[..., Any],
    read_gate: Callable[..., Any],
    write_gate: Callable[..., Any],
) -> None:
    app.add_middleware(OfficeBoundaryMiddleware)
    ui_dir = Path(__file__).resolve().parent.parent / "ui" / "office"
    app.mount("/office/assets", StaticFiles(directory=ui_dir), name="office-assets")

    @app.get("/office", response_class=FileResponse)
    def office_workspace() -> FileResponse:
        return FileResponse(ui_dir / "index.html")

    @app.get("/office/editor.js", response_class=FileResponse)
    def office_editor_bundle() -> FileResponse:
        bundle = Path("/opt/collabio-office/office.bundle.js")
        if not bundle.is_file():
            raise HTTPException(status_code=503, detail="Office editor build is unavailable")
        return FileResponse(bundle, media_type="text/javascript")

    @app.get("/office/licenses", response_class=FileResponse)
    def office_component_licenses() -> FileResponse:
        return FileResponse("/opt/collabio-office/THIRD_PARTY_NOTICES.txt", media_type="text/plain")

    router = APIRouter(prefix="/v1/office/documents", route_class=OfficeRoute, dependencies=[Depends(read_gate)])

    @router.post("/{object_id}/images", dependencies=[Depends(write_gate)])
    def upload_image(
        object_id: str,
        request: Request,
        content: bytes = Body(media_type="application/octet-stream"),
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
    ) -> Any:
        service = request.app.state.office_document_service
        repository = service.repository
        if not service.writes_available or not isinstance(repository, PgOfficeDocumentRepository):
            raise OfficeDocumentPermissionError("Image writes unavailable")
        repository.get_document(user_context=context.user_context, object_id=object_id)
        if not repository.can_write(user_context=context.user_context, object_id=object_id):
            raise OfficeDocumentPermissionError("Image writing is not permitted")
        if request.headers.get("X-Office-Upload-Confirmed") != "true":
            raise OfficeDocumentInvalidContentError("Image upload requires explicit confirmation")
        normalized, width, height = normalize_image(content, request.headers.get("Content-Type", ""))
        attrs = store_uploaded_image(repository, context.user_context, object_id, normalized, width, height)
        event = service._audit(
            context.user_context,
            "office.images.uploaded",
            object_id=object_id,
            asset_id=attrs["assetId"],
            version_id=attrs["versionId"],
            content_hash=attrs["contentHash"],
        )
        return {"image": attrs, "audit_event_id": event}

    @router.get("/{object_id}/images/{asset_id}/{version_id}")
    def image_content(
        object_id: str,
        asset_id: str,
        version_id: str,
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
    ) -> Response:
        service = request.app.state.office_document_service
        document = service.repository.get_document(user_context=context.user_context, object_id=object_id)
        metadata, content = read_image(
            service.source_repository, document, {"documentId": object_id, "assetId": asset_id, "versionId": version_id}
        )
        service._audit(
            context.user_context,
            "office.images.read",
            object_id=object_id,
            asset_id=asset_id,
            version_id=version_id,
            content_hash=metadata.content_hash,
        )
        return Response(
            content,
            media_type="image/png",
            headers={
                "X-Office-Content-Hash": metadata.content_hash,
                "X-Office-Manifest-Hash": metadata.manifest_hash,
            },
        )

    @router.get("", response_model=OfficeDocumentListResponse)
    def list_documents(
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
        query: str = Query(default="", max_length=200),
        page_size: int = Query(default=200, ge=1, le=200),
        cursor: str | None = Query(default=None, min_length=1, max_length=1024),
    ) -> Any:
        return request.app.state.office_document_service.list_documents(
            user_context=context.user_context,
            write_enabled=_write_enabled(request, context),
            query=query,
            page_size=page_size,
            cursor=cursor,
        )

    @router.post("", response_model=OfficeDocumentContentResponse, dependencies=[Depends(write_gate)])
    def create_document(
        command: OfficeDocumentCreateCommand,
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
    ) -> Any:
        return request.app.state.office_document_service.create(
            user_context=context.user_context, command=command, write_enabled=True
        )

    @router.get("/{object_id}/content", response_model=OfficeDocumentContentResponse)
    def read_document(
        object_id: str,
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
        version_id: str | None = Query(default=None, min_length=1, max_length=128),
    ) -> Any:
        return request.app.state.office_document_service.read_content(
            user_context=context.user_context,
            object_id=object_id,
            version_id=version_id,
            write_enabled=_write_enabled(request, context),
        )

    @router.get("/{object_id}/versions", response_model=OfficeDocumentHistoryResponse)
    def document_history(
        object_id: str,
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
        page_size: int = Query(default=200, ge=1, le=200),
        cursor: str | None = Query(default=None, min_length=1, max_length=1024),
    ) -> Any:
        return request.app.state.office_document_service.history(
            user_context=context.user_context,
            object_id=object_id,
            page_size=page_size,
            cursor=cursor,
        )

    @router.post(
        "/{object_id}/versions", response_model=OfficeDocumentContentResponse, dependencies=[Depends(write_gate)]
    )
    def save_document(
        object_id: str,
        command: OfficeDocumentSaveCommand,
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
    ) -> Any:
        return request.app.state.office_document_service.save(
            user_context=context.user_context, object_id=object_id, command=command, write_enabled=True
        )

    @router.get("/{object_id}/review-threads", response_model=ReviewListResponse)
    def review_threads(
        object_id: str,
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
        after: str | None = Query(default=None, min_length=1, max_length=128),
        limit: int = Query(default=20, ge=1, le=50),
        anchor_version_id: str | None = Query(default=None, min_length=1, max_length=128),
    ) -> Any:
        return request.app.state.office_review_service.list_threads(
            user_context=context.user_context,
            object_id=object_id,
            after=after,
            limit=limit,
            anchor_version_id=anchor_version_id,
            write_enabled=_write_enabled(request, context),
        )

    @router.get("/{object_id}/review-threads/{thread_id}", response_model=ReviewDetailResponse)
    def review_thread_detail(
        object_id: str,
        thread_id: str,
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
        after_revision: int = Query(default=0, ge=0, le=2147483647),
        limit: int = Query(default=20, ge=1, le=50),
    ) -> Any:
        return request.app.state.office_review_service.detail(
            user_context=context.user_context,
            object_id=object_id,
            thread_id=thread_id,
            after_revision=after_revision,
            limit=limit,
            write_enabled=_write_enabled(request, context),
        )

    @router.post(
        "/{object_id}/review-threads", response_model=ReviewMutationResponse, dependencies=[Depends(write_gate)]
    )
    def create_review_thread(
        object_id: str,
        command: ReviewCreateCommand,
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
    ) -> Any:
        return request.app.state.office_review_service.mutate(
            user_context=context.user_context, object_id=object_id, command=command, write_enabled=True
        )

    @router.post(
        "/{object_id}/review-threads/{thread_id}/events",
        response_model=ReviewMutationResponse,
        dependencies=[Depends(write_gate)],
    )
    def append_review_event(
        object_id: str,
        thread_id: str,
        command: ReviewEventCommand,
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
    ) -> Any:
        return request.app.state.office_review_service.mutate(
            user_context=context.user_context,
            object_id=object_id,
            thread_id=thread_id,
            command=command,
            write_enabled=True,
        )

    @router.get("/{object_id}/suggestions", response_model=SuggestionListResponse)
    def list_suggestions(
        object_id: str,
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
        after: str | None = Query(default=None, min_length=1, max_length=128),
        limit: int = Query(default=20, ge=1, le=50),
        anchor_version_id: str | None = Query(default=None, min_length=1, max_length=128),
    ) -> Any:
        return request.app.state.office_suggestion_service.list_suggestions(
            user_context=context.user_context,
            object_id=object_id,
            after=after,
            limit=limit,
            anchor_version_id=anchor_version_id,
            write_enabled=_write_enabled(request, context),
        )

    @router.get("/{object_id}/suggestions/{suggestion_id}", response_model=SuggestionDetailResponse)
    def suggestion_detail(
        object_id: str,
        suggestion_id: str,
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
    ) -> Any:
        return request.app.state.office_suggestion_service.detail(
            user_context=context.user_context,
            object_id=object_id,
            suggestion_id=suggestion_id,
            write_enabled=_write_enabled(request, context),
        )

    @router.post(
        "/{object_id}/suggestions", response_model=SuggestionMutationResponse, dependencies=[Depends(write_gate)]
    )
    def create_suggestion(
        object_id: str,
        command: SuggestionCreateCommand,
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
    ) -> Any:
        return request.app.state.office_suggestion_service.mutate(
            user_context=context.user_context,
            object_id=object_id,
            command=command,
            write_enabled=True,
        )

    @router.post(
        "/{object_id}/suggestions/{suggestion_id}/decisions",
        response_model=SuggestionMutationResponse,
        dependencies=[Depends(write_gate)],
    )
    def decide_suggestion(
        object_id: str,
        suggestion_id: str,
        command: SuggestionDecisionCommand,
        request: Request,
        context: TenantRequestContext = Depends(context_dependency),  # noqa: B008
    ) -> Any:
        return request.app.state.office_suggestion_service.mutate(
            user_context=context.user_context,
            object_id=object_id,
            suggestion_id=suggestion_id,
            command=command,
            write_enabled=True,
        )

    app.include_router(router)
