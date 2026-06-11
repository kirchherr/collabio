import pytest

from suite.storage.content_hash import (
    ContentHashAlgorithm,
    ContentHashVerificationError,
    compute_content_hash,
    parse_content_hash,
    verify_content_hash,
)


def test_compute_content_hash_returns_canonical_sha256_reference() -> None:
    assert compute_content_hash(b"hello") == "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_verify_content_hash_returns_restore_ready_evidence() -> None:
    expected_hash = compute_content_hash(b"restored bytes")

    result = verify_content_hash(
        content=b"restored bytes",
        expected_hash=expected_hash,
        verification_context="restore",
    )

    assert result.verified is True
    assert result.algorithm == ContentHashAlgorithm.SHA256
    assert result.expected_hash == expected_hash
    assert result.actual_hash == expected_hash
    assert result.byte_length == len(b"restored bytes")
    assert result.verification_context == "restore"


def test_parse_content_hash_rejects_unsupported_algorithm() -> None:
    with pytest.raises(ContentHashVerificationError, match="unsupported content hash algorithm"):
        parse_content_hash("md5:00000000000000000000000000000000")


def test_parse_content_hash_rejects_malformed_sha256_digest() -> None:
    with pytest.raises(ContentHashVerificationError, match="sha256"):
        parse_content_hash("sha256:not-the-content")


def test_verify_content_hash_rejects_mismatched_bytes() -> None:
    with pytest.raises(ContentHashVerificationError, match="does not match"):
        verify_content_hash(
            content=b"tampered bytes",
            expected_hash=compute_content_hash(b"original bytes"),
            verification_context="read",
        )


def test_verify_content_hash_requires_named_verification_context() -> None:
    with pytest.raises(ContentHashVerificationError, match="verification_context"):
        verify_content_hash(
            content=b"content",
            expected_hash=compute_content_hash(b"content"),
            verification_context=" ",
        )
