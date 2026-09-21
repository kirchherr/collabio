from __future__ import annotations

import io
import logging

import pytest

from suite.platform.office_access_logging import (
    OfficeDiscoveryAccessLogFilter,
    protect_office_discovery_access_logs,
)


@pytest.mark.parametrize("status", [200, 307, 400, 403, 404, 422, 503])
@pytest.mark.parametrize(
    "path",
    [
        "/v1/office/documents",
        "/v1/office/documents/",
        "/v1/office/documents/office-doc-0123456789abcdef0123456789abcdef/versions",
        "/v1/office/documents/office-doc-0123456789abcdef0123456789abcdef/versions/",
        "/v1/office/documents/invalid-object/versions",
    ],
)
def test_discovery_access_records_redact_queries_before_formatting(status: int, path: str) -> None:
    secret_query = "private-title-%F0%9F%98%80"
    secret_cursor = "actor-bound-secret-cursor"
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", f"{path}?query={secret_query}&cursor={secret_cursor}&page_size=50", "1.1", status),
        None,
    )
    assert OfficeDiscoveryAccessLogFilter().filter(record)
    assert record.args == ("127.0.0.1:1234", "GET", path, "1.1", status)
    assert record.getMessage() == f'127.0.0.1:1234 - "GET {path} HTTP/1.1" {status}'
    assert secret_query not in str(record.__dict__)
    assert secret_cursor not in str(record.__dict__)


@pytest.mark.parametrize(
    "target",
    [
        "/health",
        "/v1/office/documents",
        "/v1/office/documents/object/content?version_id=version",
        "/v1/office/documents/object/versions/extra?cursor=value",
        "/other?query=value",
    ],
)
def test_discovery_filter_preserves_unrelated_access_records(target: str) -> None:
    arguments = ("127.0.0.1:1234", "GET", target, "1.1", 200)
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "%s %s %s %s %s", arguments, None)
    assert OfficeDiscoveryAccessLogFilter().filter(record)
    assert record.args == arguments


@pytest.mark.parametrize("path", ["/v1/office/documents", "/v1/office/documents/object/versions"])
def test_discovery_log_protection_is_idempotent_and_keeps_status_observable(path: str) -> None:
    logger = logging.getLogger("uvicorn.access")
    previous_filters, previous_handlers = logger.filters[:], logger.handlers[:]
    previous_level, previous_propagate, previous_disabled = logger.level, logger.propagate, logger.disabled
    stream = io.StringIO()
    try:
        logger.filters = []
        logger.handlers = [logging.StreamHandler(stream)]
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.disabled = False
        protect_office_discovery_access_logs()
        protect_office_discovery_access_logs()
        assert len(logger.filters) == 1
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "client",
            "GET",
            f"{path}?query=private&cursor=secret",
            "1.1",
            422,
        )
        assert stream.getvalue() == f'client - "GET {path} HTTP/1.1" 422\n'
    finally:
        logger.filters, logger.handlers = previous_filters, previous_handlers
        logger.setLevel(previous_level)
        logger.propagate, logger.disabled = previous_propagate, previous_disabled
