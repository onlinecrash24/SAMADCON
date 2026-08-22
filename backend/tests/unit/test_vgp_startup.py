"""Unix/Scripts/Startup: the elements, and the hash that held it back.

Two sources settle this, both read off the pinned Samba rather than recalled.
``vgp_startup_scripts_ext`` gives the element names and the defaults it
substitutes; ``cmd_add_startup`` gives the digest:

    hash.text = hashlib.md5(script_data).hexdigest().upper()

and ``gp_file_applier.apply`` gives the reason it matters — it compares that
value against the one cached from the last application, never against the
script. A hash that is stable but unrelated to the content therefore means a
changed script is never re-applied.
"""

from __future__ import annotations

import hashlib
from typing import Any

from samadcon.gpo import vgp

# A manifest in the shape cmd_add_startup writes, with one entry carrying
# everything optional and one carrying nothing.
MANIFEST = """<?xml version='1.0' encoding='UTF-8'?>
<vgppolicy>
  <policysetting>
    <version>1</version>
    <name>Unix Scripts</name>
    <description>Represents Unix scripts to run on Group Policy clients</description>
    <data>
      <listelement>
        <script>backup.sh</script>
        <hash>0123456789ABCDEF0123456789ABCDEF</hash>
        <parameters>--full /srv</parameters>
        <run_as>backup</run_as>
        <run_once/>
      </listelement>
      <listelement>
        <script>plain.sh</script>
        <hash>FEDCBA9876543210FEDCBA9876543210</hash>
      </listelement>
    </data>
  </policysetting>
</vgppolicy>
"""


def entries() -> list[dict[str, Any]]:
    return vgp.parse("startup", MANIFEST)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_the_elements_are_read() -> None:
    first = entries()[0]

    assert first["script"] == "backup.sh"
    assert first["parameters"] == "--full /srv"
    assert first["run_as"] == "backup"
    assert first["run_once"] is True


def test_run_once_is_presence_and_not_text() -> None:
    """`run_once = listelement.find('run_once') is not None` — the element has
    no content, and having it is the whole statement."""
    assert entries()[0]["run_once"] is True
    assert entries()[1]["run_once"] is False


def test_the_defaults_the_extension_substitutes() -> None:
    """It does not fail on an absent run_as or parameters; it fills in root and
    an empty string. Reading them the same way keeps the console honest about
    what a client will do."""
    second = entries()[1]

    assert second["run_as"] == "root"
    assert second["parameters"] == ""


def test_the_hash_is_not_offered_to_the_caller() -> None:
    """It is derived from the script. Surfacing it would invite setting one,
    and a wrong one is the failure this kind waited on."""
    assert "hash" not in entries()[0]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def rendered(items: list[dict[str, Any]]) -> str:
    return vgp.render("startup", items).decode("utf-8")


def test_the_optional_elements_are_left_out_when_there_is_nothing_to_say() -> None:
    """cmd_add_startup writes parameters, run_as and run_once only when it has
    them, so the same input gives the same file here as there."""
    text = rendered([{"script": "plain.sh", "hash": "AB", "run_as": "root"}])

    assert "<parameters" not in text
    assert "<run_as" not in text
    assert "<run_once" not in text


def test_root_is_written_as_an_absent_element() -> None:
    """The reader substitutes root for an absent run_as. Writing it back
    explicitly would turn reading and saving an unchanged policy into a
    change, and the version would climb for nothing."""
    text = rendered([{"script": "a.sh", "hash": "AB", "run_as": "root"}])

    assert "run_as" not in text


def test_a_policy_survives_a_round_trip_unchanged() -> None:
    """The strongest thing these tests can say without a share: what was read
    renders back to something that reads the same."""
    once = entries()
    twice = vgp.parse("startup", rendered([{**item, "hash": "AB"} for item in once]))

    assert [dict(item) for item in twice] == [dict(item) for item in once]


def test_the_name_and_description_are_the_ones_samba_tool_writes() -> None:
    kind = vgp.kind_for("startup")

    assert kind.name == "Unix Scripts"
    assert kind.description == "Represents Unix scripts to run on Group Policy clients"
    assert kind.directory == "Unix\\Scripts\\Startup"


# ---------------------------------------------------------------------------
# The digest
# ---------------------------------------------------------------------------


class Share:
    """Just enough share to hand back one file's bytes."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def read(self, path: str) -> bytes:
        return self.files[path.rsplit("\\", 1)[-1]]


def test_the_digest_is_md5_of_the_script_upper_case() -> None:
    """Quoted from cmd_add_startup: md5(script_data).hexdigest().upper()."""
    body = b"#!/bin/sh\necho hello\n"
    items = [{"script": "hello.sh"}]

    vgp._fill_hashes(Share({"hello.sh": body}), "base", vgp.kind_for("startup"), items)

    assert items[0]["hash"] == hashlib.md5(body).hexdigest().upper()


def test_changing_the_script_changes_the_digest() -> None:
    """The reason it must come from the bytes. gp_file_applier compares this
    against the value cached at the last application — if it did not move when
    the script did, the new script would never run."""
    kind = vgp.kind_for("startup")
    before: list[dict[str, Any]] = [{"script": "s.sh"}]
    after: list[dict[str, Any]] = [{"script": "s.sh"}]

    vgp._fill_hashes(Share({"s.sh": b"one"}), "base", kind, before)
    vgp._fill_hashes(Share({"s.sh": b"two"}), "base", kind, after)

    assert before[0]["hash"] != after[0]["hash"]


def test_a_kind_without_payload_digests_is_left_alone() -> None:
    items: list[dict[str, Any]] = [{"source": "motd.txt"}]

    vgp._fill_hashes(Share({}), "base", vgp.kind_for("files"), items)

    assert "hash" not in items[0]
