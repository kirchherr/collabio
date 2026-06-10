from __future__ import annotations

import argparse
import base64
import json
import sys
from typing import Any

from suite.rag.parser_worker import ParserWorkerRequest
from suite.rag.rich_document_parser import RichDocumentParserWorker


def parse_payload(payload: dict[str, Any]) -> ParserWorkerRequest:
    content_base64 = payload.get("content_base64")
    if not isinstance(content_base64, str):
        raise ValueError("content_base64 must be provided")
    return ParserWorkerRequest(
        tenant_id=str(payload["tenant_id"]),
        source_object_id=str(payload["source_object_id"]),
        source_version_id=str(payload["source_version_id"]),
        source_object_type=str(payload["source_object_type"]),
        mime_type=str(payload["mime_type"]),
        content=base64.b64decode(content_base64, validate=True),
        filename=str(payload["filename"]) if payload.get("filename") is not None else None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated rich document parser worker")
    parser.add_argument("--describe", action="store_true", help="print parser manifest and exit")
    args = parser.parse_args()

    worker = RichDocumentParserWorker()
    if args.describe:
        print(json.dumps(worker.manifest().__dict__, sort_keys=True))
        return

    request = parse_payload(json.loads(sys.stdin.read()))
    artifact = worker.parse(request)
    print(json.dumps(artifact.__dict__, sort_keys=True))


if __name__ == "__main__":
    main()
