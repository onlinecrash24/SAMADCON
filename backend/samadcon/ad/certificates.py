"""Published certificates: the X.509 certificates on an account.

ADUC's "Published Certificates" tab, over the ``userCertificate`` attribute —
multi-valued, each value one DER-encoded certificate. This reads them out
with what the tab shows (issued to, issued by, purposes, expiry), adds one
from a file, removes one, and identifies each by its SHA-256 fingerprint,
because two certificates for the same name are not the same certificate and
an index into a multi-valued attribute is not stable across a write.

What it does not do is "Add from Store": that button in ADUC reaches into the
Windows certificate store on the administrator's own machine, and a browser
has no such thing to reach into.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import ExtendedKeyUsageOID, ExtensionOID

from samadcon.ad.connection import DirectoryConnection
from samadcon.core.errors import Conflict, InvalidRequest, NotFound

ATTRIBUTE = "userCertificate"
MAX_CERTIFICATE_BYTES = 64 * 1024

# The names ADUC prints under "Intended Purposes", for the usages a
# certificate on an account is likely to carry.
_PURPOSES = {
    ExtendedKeyUsageOID.CLIENT_AUTH: "Client Authentication",
    ExtendedKeyUsageOID.SERVER_AUTH: "Server Authentication",
    ExtendedKeyUsageOID.EMAIL_PROTECTION: "Secure Email",
    ExtendedKeyUsageOID.CODE_SIGNING: "Code Signing",
    ExtendedKeyUsageOID.SMARTCARD_LOGON: "Smart Card Logon",
    ExtendedKeyUsageOID.TIME_STAMPING: "Time Stamping",
    ExtendedKeyUsageOID.OCSP_SIGNING: "OCSP Signing",
    ExtendedKeyUsageOID.ANY_EXTENDED_KEY_USAGE: "All",
}


def decode(data: bytes) -> x509.Certificate:
    """One certificate from DER or PEM, or an error that says which it was not."""
    if len(data) > MAX_CERTIFICATE_BYTES:
        raise InvalidRequest("The certificate is too large.", code="certificate_too_large")
    try:
        return x509.load_der_x509_certificate(data)
    except ValueError:
        pass
    try:
        return x509.load_pem_x509_certificate(data)
    except ValueError as exc:
        raise InvalidRequest(
            "The file is not an X.509 certificate in DER or PEM form.",
            code="not_a_certificate",
        ) from exc


def _name(name: x509.Name) -> str:
    """The name as ADUC prints it: the CN if there is one, else the whole RDN string."""
    for attribute in name:
        if attribute.oid == x509.NameOID.COMMON_NAME:
            return str(attribute.value)
    return name.rfc4514_string()


def _purposes(cert: x509.Certificate) -> list[str]:
    try:
        eku = cert.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE).value
    except x509.ExtensionNotFound:
        return []
    return [_PURPOSES.get(oid, oid.dotted_string) for oid in eku]


def describe(cert: x509.Certificate) -> dict[str, Any]:
    der = cert.public_bytes(Encoding.DER)
    fingerprint = cert.fingerprint(hashes.SHA256()).hex()
    return {
        "fingerprint": fingerprint,
        "subject": _name(cert.subject),
        "issuer": _name(cert.issuer),
        "subject_dn": cert.subject.rfc4514_string(),
        "issuer_dn": cert.issuer.rfc4514_string(),
        "serial": format(cert.serial_number, "x"),
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": cert.not_valid_after_utc.isoformat(),
        "purposes": _purposes(cert),
        # For "Copy to File" and for showing the whole thing: the DER as
        # base64, and the PEM as text.
        "der": base64.b64encode(der).decode("ascii"),
        "pem": cert.public_bytes(Encoding.PEM).decode("ascii"),
    }


def inspect(data_b64: str) -> dict[str, Any]:
    """What a certificate would look like on the tab, before it is added."""
    return describe(decode(_from_b64(data_b64)))


def _from_b64(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidRequest("The upload is not base64.", code="not_base64") from exc


def _stored(conn: DirectoryConnection, dn: str) -> list[bytes]:
    entry = conn.get(dn, attrs=[ATTRIBUTE])
    if entry is None:
        raise NotFound("The object does not exist.", context={"dn": dn})
    element = entry.get(ATTRIBUTE)
    if element is None:
        return []
    return [bytes(v) for v in element]


def list_certificates(conn: DirectoryConnection, dn: str) -> list[dict[str, Any]]:
    """Every certificate on the account; one that will not parse is reported, not hidden."""
    out: list[dict[str, Any]] = []
    for raw in _stored(conn, dn):
        try:
            out.append(describe(x509.load_der_x509_certificate(raw)))
        except ValueError:
            out.append({
                "fingerprint": _raw_fingerprint(raw),
                "subject": None,
                "issuer": None,
                "unparseable": True,
                "der": base64.b64encode(raw).decode("ascii"),
            })
    return out


def _raw_fingerprint(raw: bytes) -> str:
    digest = hashes.Hash(hashes.SHA256())
    digest.update(raw)
    return digest.finalize().hex()


def add_certificate(conn: DirectoryConnection, dn: str, data_b64: str) -> dict[str, Any]:
    """Append one certificate. The same one twice is refused, by fingerprint."""
    import ldb

    cert = decode(_from_b64(data_b64))
    der = cert.public_bytes(Encoding.DER)
    fingerprint = cert.fingerprint(hashes.SHA256()).hex()

    for raw in _stored(conn, dn):
        if _raw_fingerprint(raw) == fingerprint:
            raise Conflict(
                "This certificate is already published on the account.",
                code="certificate_already_present",
            )

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message[ATTRIBUTE] = ldb.MessageElement([der], ldb.FLAG_MOD_ADD, ATTRIBUTE)
    conn.modify(message)
    return {"added": fingerprint, "subject": _name(cert.subject)}


def remove_certificate(conn: DirectoryConnection, dn: str, fingerprint: str) -> dict[str, Any]:
    """Remove the one certificate with this fingerprint, and only that one."""
    import ldb

    wanted = fingerprint.lower()
    matches = [raw for raw in _stored(conn, dn) if _raw_fingerprint(raw) == wanted]
    if not matches:
        raise NotFound(
            "No certificate with that fingerprint is on the account.",
            context={"fingerprint": fingerprint},
        )

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message[ATTRIBUTE] = ldb.MessageElement(matches[:1], ldb.FLAG_MOD_DELETE, ATTRIBUTE)
    conn.modify(message)
    return {"removed": wanted}
