"""A new GPO's file permissions, through Samba's own descriptor bindings.

Runs wherever python3-samba is installed — the CI image, which is the image
that ships. The descriptors are the ones measured on a Synology Directory
Server: A was refused, B accepted.
"""

from __future__ import annotations

import pytest

from samadcon.gpo import container

security = pytest.importorskip("samba.dcerpc.security")

DOMAIN = "S-1-5-21-2540059117-2646349506-3686739550"

REFUSED = (
    "O:DAG:DAD:P(A;OICI;FA;;;DA)(A;OICI;FA;;;EA)(A;OICIIO;FA;;;CO)(A;OICI;FA;;;DA)"
    "(A;OICI;FA;;;SY)(A;OICI;0x1200a9;;;AU)"
    "(OA;OICI;;edacfd8f-ffb3-11d1-b41d-00a0c968f939;;AU)(A;OICI;0x1200a9;;;ED)"
)
ACCEPTED = (
    "O:DAG:DAD:P(A;OICI;FA;;;DA)(A;OICI;FA;;;EA)(A;OICIIO;FA;;;CO)(A;OICI;FA;;;DA)"
    "(A;OICI;FA;;;SY)(A;OICI;0x1200a9;;;AU)(A;OICI;0x1200a9;;;ED)"
)


def test_dropping_object_aces_turns_the_refused_descriptor_into_the_accepted_one():
    sid = security.dom_sid(DOMAIN)
    refused = security.descriptor.from_sddl(REFUSED, sid)
    kept = container._without_object_aces(refused, security)
    assert kept is not None
    assert kept.as_sddl(sid) == ACCEPTED


def test_a_descriptor_without_object_aces_has_nothing_to_drop():
    sid = security.dom_sid(DOMAIN)
    accepted = security.descriptor.from_sddl(ACCEPTED, sid)
    assert container._without_object_aces(accepted, security) is None
