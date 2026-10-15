from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from suite.kms.x509_evidence import X509EvidenceError, inspect_der_x509_certificate


def _reviewed_fulcio_certificate() -> bytes:
    verification = json.loads(
        Path("docs/operations/genoffice_emf_converter_npm_verification.json").read_text(encoding="utf-8")
    )
    bundles = verification["verified"][0]["attestationBundles"]
    slsa = next(bundle for bundle in bundles if bundle["predicateType"] == "https://slsa.dev/provenance/v1")
    return base64.b64decode(slsa["bundle"]["verificationMaterial"]["certificate"]["rawBytes"], validate=True)


def test_inspects_reviewed_fulcio_certificate_without_exposing_provider_types() -> None:
    evidence = inspect_der_x509_certificate(_reviewed_fulcio_certificate())

    assert evidence.der_sha256 == "sha256:b26c2c25ff00d5cfd69b3156d66b84e4d13a88e28522227386486405948506d4"
    assert evidence.issuer_organizations == ("sigstore.dev",)
    assert evidence.issuer_common_names == ("sigstore-intermediate",)
    assert evidence.uri_subject_alternative_names == (
        "https://github.com/ChristopherVR/emf-converter/.github/workflows/publish.yml@refs/heads/main",
    )
    assert evidence.unrecognized_extension("1.3.6.1.4.1.57264.1.12") is not None


def test_rejects_malformed_der_certificate() -> None:
    with pytest.raises(X509EvidenceError, match="malformed"):
        inspect_der_x509_certificate(b"not-a-certificate")
