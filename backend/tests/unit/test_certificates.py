"""Published certificates: parsed for the tab, added once, removed by
fingerprint. The certificates are generated here, so the test cannot rot the
way a pasted one would."""

from __future__ import annotations

import base64
import sys
import types
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from samadcon.ad import certificates
from samadcon.core.errors import Conflict, InvalidRequest, NotFound

USER_DN = "CN=anna,OU=Users,DC=example,DC=test"


def make_cert(cn: str, issuer: str = "Example CA", purposes: list[Any] | None = None) -> x509.Certificate:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    issuer_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime(2026, 1, 1, tzinfo=UTC))
        .not_valid_after(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=365))
    )
    if purposes:
        builder = builder.add_extension(x509.ExtendedKeyUsage(purposes), critical=False)
    return builder.sign(key, hashes.SHA256())


def b64(cert: x509.Certificate, encoding: Encoding = Encoding.DER) -> str:
    return base64.b64encode(cert.public_bytes(encoding)).decode()


class Account:
    def __init__(self, certs: list[x509.Certificate]) -> None:
        self.values = [c.public_bytes(Encoding.DER) for c in certs]
        self.modified: list[tuple[int, list[bytes]]] = []
        self.samdb = object()

    def get(self, dn: str, attrs: list[str] | None = None) -> Any:
        assert dn == USER_DN
        return {"userCertificate": list(self.values)} if self.values else {}

    def modify(self, message: Any) -> None:
        element = message["userCertificate"]
        self.modified.append((element.flags, list(element)))


@pytest.fixture(autouse=True)
def fake_ldb(monkeypatch):
    class Dn:
        def __init__(self, samdb: Any, text: str) -> None:
            self.text = text

    class MessageElement(list):
        def __init__(self, value: Any, flags: int, name: str) -> None:
            super().__init__(value)
            self.flags = flags

    class Message(dict):
        dn: Any = None

    fake = types.SimpleNamespace(
        Dn=Dn, Message=Message, MessageElement=MessageElement, FLAG_MOD_ADD=1, FLAG_MOD_DELETE=3,
    )
    monkeypatch.setitem(sys.modules, "ldb", fake)


def test_the_tab_gets_what_aduc_shows():
    cert = make_cert("anna", purposes=[ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SMARTCARD_LOGON])
    conn = Account([cert])
    [shown] = certificates.list_certificates(conn, USER_DN)
    assert shown["subject"] == "anna"
    assert shown["issuer"] == "Example CA"
    assert shown["purposes"] == ["Client Authentication", "Smart Card Logon"]
    assert shown["not_after"].startswith("2027-01-01")
    assert shown["fingerprint"] == cert.fingerprint(hashes.SHA256()).hex()
    assert base64.b64decode(shown["der"]) == cert.public_bytes(Encoding.DER)
    assert shown["pem"].startswith("-----BEGIN CERTIFICATE-----")


def test_a_value_that_is_not_a_certificate_is_reported_not_hidden():
    conn = Account([])
    conn.values = [b"not a certificate"]
    [shown] = certificates.list_certificates(conn, USER_DN)
    assert shown["unparseable"] is True
    assert shown["subject"] is None


def test_pem_and_der_both_decode():
    cert = make_cert("anna")
    assert certificates.inspect(b64(cert, Encoding.PEM))["subject"] == "anna"
    assert certificates.inspect(b64(cert))["subject"] == "anna"


def test_garbage_is_refused_with_a_code():
    with pytest.raises(InvalidRequest) as caught:
        certificates.inspect(base64.b64encode(b"hello").decode())
    assert caught.value.code == "not_a_certificate"
    with pytest.raises(InvalidRequest) as caught:
        certificates.inspect("not base64!!")
    assert caught.value.code == "not_base64"


def test_adding_appends_the_der_and_only_once():
    existing = make_cert("anna")
    new = make_cert("anna")  # same name, different key: a different certificate
    conn = Account([existing])

    certificates.add_certificate(conn, USER_DN, b64(new, Encoding.PEM))
    assert conn.modified == [(1, [new.public_bytes(Encoding.DER)])]

    with pytest.raises(Conflict) as caught:
        certificates.add_certificate(conn, USER_DN, b64(existing))
    assert caught.value.code == "certificate_already_present"


def test_removing_takes_exactly_the_one_with_that_fingerprint():
    first, second = make_cert("anna"), make_cert("anna")
    conn = Account([first, second])
    certificates.remove_certificate(conn, USER_DN, second.fingerprint(hashes.SHA256()).hex().upper())
    assert conn.modified == [(3, [second.public_bytes(Encoding.DER)])]

    with pytest.raises(NotFound):
        certificates.remove_certificate(conn, USER_DN, "00" * 32)
