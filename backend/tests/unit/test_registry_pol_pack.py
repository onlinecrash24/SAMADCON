"""Registry.pol packed and read through Samba's own preg binding.

test_registry_pol.py covers the decisions that need no Samba; this covers the
binding itself, and runs wherever python3-samba is installed — the CI image,
which is the image that ships. It was left to the integration tests, which CI
does not run, and that is how 0.6.6 shipped handing the binding a list for a
multi-string. preg takes and returns a multi-string as one block of bytes;
handed a list it does not raise, it trips a C assertion (PyBytes_Check) and
aborts the process. A tester saving a multi-line template
value took the backend down and every signed-in session with it.
"""

from __future__ import annotations

import base64

import pytest

pytest.importorskip("samba.dcerpc.preg")

from samadcon.gpo import registry_pol as pol

KEY = "Software\\Policies\\Microsoft\\Windows\\Appx"
PACKAGES = ["Microsoft.Edge.GameAssist_8wekyb3d8bbwe", "Microsoft.People_8wekyb3d8bbwe"]


def entry(value: str, kind: str, data: object) -> dict[str, object]:
    return {"key": KEY, "value": value, "type": kind, "data": data}


def test_a_multi_string_packs_without_taking_the_process_down():
    """The case that aborted: the tester's own package names."""
    raw = pol.build([entry("Packages", "REG_MULTI_SZ", PACKAGES)])
    assert pol.parse(raw)[0]["data"] == PACKAGES


def test_a_multi_string_is_utf16_with_a_terminator_each_and_a_final_one():
    raw = pol.build([entry("Packages", "REG_MULTI_SZ", ["a", "bb"])])
    assert "a\0bb\0\0".encode("utf-16-le") in raw


def test_every_type_comes_back_as_it_went_in():
    binary = base64.b64encode(b"\x01\x02\x03").decode()
    entries = [
        entry("Text", "REG_SZ", "Grüße"),
        entry("Expand", "REG_EXPAND_SZ", "%SystemRoot%\\x"),
        entry("List", "REG_MULTI_SZ", ["eins", "zwei"]),
        entry("Number", "REG_DWORD", 7),
        entry("Big", "REG_QWORD", 2**40),
        entry("Blob", "REG_BINARY", binary),
    ]
    back = pol.parse(pol.build(entries))
    assert [item["data"] for item in back] == [
        "Grüße",
        "%SystemRoot%\\x",
        ["eins", "zwei"],
        7,
        2**40,
        binary,
    ]


def test_the_size_field_is_what_the_data_takes():
    """Written into the file; a wrong one makes every later entry unreadable."""
    raw = pol.build([entry("List", "REG_MULTI_SZ", ["a", "bb"]), entry("Text", "REG_SZ", "x")])
    sizes = [item["size"] for item in pol.parse(raw)]
    assert sizes == [pol.data_size(pol.REG_MULTI_SZ, ["a", "bb"]), pol.data_size(pol.REG_SZ, "x")]
