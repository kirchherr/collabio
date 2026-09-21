from __future__ import annotations

import logging


class OfficeDiscoveryAccessLogFilter(logging.Filter):
    """Keep title queries and opaque page cursors out of Uvicorn access records."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn's h11/httptools access logger supplies client, method, target,
        # HTTP version and status as separate arguments. Preserve that shape so
        # both its text formatter and structured handlers see a safe target.
        arguments = record.args
        if isinstance(arguments, tuple) and len(arguments) == 5 and isinstance(arguments[2], str):
            target, separator, _ = arguments[2].partition("?")
            path = target.rstrip("/")
            parts = path.split("/")
            history_path = (
                len(parts) == 6
                and parts[:4] == ["", "v1", "office", "documents"]
                and bool(parts[4])
                and parts[5] == "versions"
            )
            if separator and (path == "/v1/office/documents" or history_path):
                record.args = (*arguments[:2], target, *arguments[3:])
        return True


def protect_office_discovery_access_logs() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, OfficeDiscoveryAccessLogFilter) for item in logger.filters):
        logger.addFilter(OfficeDiscoveryAccessLogFilter())
