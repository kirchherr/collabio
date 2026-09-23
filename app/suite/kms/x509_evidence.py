from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography import x509
from cryptography.x509.oid import ExtensionOID, NameOID


class X509EvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class X509CertificateEvidence:
    der_sha256: str
    issuer_organizations: tuple[str, ...]
    issuer_common_names: tuple[str, ...]
    serial_hex: str
    not_before_utc: datetime
    not_after_utc: datetime
    uri_subject_alternative_names: tuple[str, ...]
    unrecognized_extensions: tuple[tuple[str, bytes], ...]

    def unrecognized_extension(self, oid: str) -> bytes | None:
        return dict(self.unrecognized_extensions).get(oid)


def _text_values(attributes: list[x509.NameAttribute], *, field: str) -> tuple[str, ...]:
    values = tuple(attribute.value for attribute in attributes)
    if not all(isinstance(value, str) for value in values):
        raise X509EvidenceError(f"X.509 {field} contains a non-text value")
    return tuple(str(value) for value in values)


def inspect_der_x509_certificate(certificate_der: bytes) -> X509CertificateEvidence:
    try:
        certificate = x509.load_der_x509_certificate(certificate_der)
    except ValueError as exc:
        raise X509EvidenceError("X.509 certificate is malformed") from exc
    try:
        san = certificate.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    except x509.ExtensionNotFound:
        uri_sans: tuple[str, ...] = ()
    else:
        if not isinstance(san, x509.SubjectAlternativeName):
            raise X509EvidenceError("X.509 subject alternative name is malformed")
        uri_sans = tuple(san.get_values_for_type(x509.UniformResourceIdentifier))
    unrecognized = tuple(
        sorted(
            (
                extension.oid.dotted_string,
                extension.value.value,
            )
            for extension in certificate.extensions
            if isinstance(extension.value, x509.UnrecognizedExtension)
        )
    )
    return X509CertificateEvidence(
        der_sha256=f"sha256:{hashlib.sha256(certificate_der).hexdigest()}",
        issuer_organizations=_text_values(
            certificate.issuer.get_attributes_for_oid(NameOID.ORGANIZATION_NAME), field="issuer organization"
        ),
        issuer_common_names=_text_values(
            certificate.issuer.get_attributes_for_oid(NameOID.COMMON_NAME), field="issuer common name"
        ),
        serial_hex=f"{certificate.serial_number:X}",
        not_before_utc=certificate.not_valid_before_utc.astimezone(UTC),
        not_after_utc=certificate.not_valid_after_utc.astimezone(UTC),
        uri_subject_alternative_names=uri_sans,
        unrecognized_extensions=unrecognized,
    )
