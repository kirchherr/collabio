from __future__ import annotations

import re
from enum import StrEnum
from hashlib import sha256

from pydantic import BaseModel, Field

SHA256_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ContentHashAlgorithm(StrEnum):
    SHA256 = "sha256"


class ContentHashVerificationError(ValueError):
    pass


class ContentHashVerificationResult(BaseModel):
    algorithm: ContentHashAlgorithm
    expected_hash: str
    actual_hash: str
    byte_length: int = Field(ge=0)
    verification_context: str
    verified: bool = True


def compute_content_hash(
    content: bytes,
    algorithm: ContentHashAlgorithm = ContentHashAlgorithm.SHA256,
) -> str:
    if algorithm != ContentHashAlgorithm.SHA256:
        raise ContentHashVerificationError(f"unsupported content hash algorithm: {algorithm}")
    return f"{algorithm.value}:{sha256(content).hexdigest()}"


def parse_content_hash(value: str) -> tuple[ContentHashAlgorithm, str]:
    normalized = value.strip()
    prefix, separator, digest = normalized.partition(":")
    if not separator or not prefix or not digest:
        raise ContentHashVerificationError("content_hash must be a namespaced hash")

    try:
        algorithm = ContentHashAlgorithm(prefix)
    except ValueError as exc:
        raise ContentHashVerificationError(f"unsupported content hash algorithm: {prefix}") from exc

    if algorithm == ContentHashAlgorithm.SHA256 and not SHA256_DIGEST_PATTERN.fullmatch(digest):
        raise ContentHashVerificationError("content_hash must be sha256:<64 lowercase hex chars>")
    return algorithm, digest


def verify_content_hash(
    *,
    content: bytes,
    expected_hash: str,
    verification_context: str = "storage",
) -> ContentHashVerificationResult:
    context = verification_context.strip()
    if not context:
        raise ContentHashVerificationError("verification_context must not be empty")

    algorithm, _digest = parse_content_hash(expected_hash)
    normalized_expected_hash = expected_hash.strip()
    actual_hash = compute_content_hash(content, algorithm)
    if actual_hash != normalized_expected_hash:
        raise ContentHashVerificationError("content_hash does not match content bytes")

    return ContentHashVerificationResult(
        algorithm=algorithm,
        expected_hash=normalized_expected_hash,
        actual_hash=actual_hash,
        byte_length=len(content),
        verification_context=context,
    )
