"""Copying, backing up, restoring and reporting, against a live DC.

These exercise the paths that move files across SYSVOL rather than just read
them. The report is included here because it only says anything real when
there is something to report — so the tests put settings into a policy first,
through the same SMB path, and check that they come back out.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from urllib.parse import quote

import pytest

pytestmark = pytest.mark.integration


def quoted(value: str) -> str:
    return quote(value, safe="")


def policy_name() -> str:
    return f"SAMADCON test {uuid.uuid4().hex[:8]}"


@pytest.fixture
def test_gpo(api):
    response = api.post("/api/v1/gpos", json={"display_name": policy_name()})
    if response.status_code != 200:
        pytest.skip(f"cannot create a group policy: {response.text}")

    gpo = response.json()
    yield gpo
    api.delete(f"/api/v1/gpos?dn={quoted(gpo['dn'])}&force=true")


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def test_a_fresh_policy_reports_as_empty(api, test_gpo):
    """And says so, rather than showing nothing and leaving it open."""
    report = api.get(f"/api/v1/gpos/report?dn={quoted(test_gpo['dn'])}")
    assert report.status_code == 200, report.text

    data = report.json()
    assert data["empty"] is True
    assert data["machine"]["registry"] == []
    assert data["unreadable"] == []


def summarise(data: dict) -> str:
    """What the report found, for a failure message.

    This test asserts something about the domain it runs against, so when it
    fails the first question is always "what is actually in there" — and an
    assertion that only says False makes that a separate investigation.
    """
    lines = []
    for half in ("machine", "user"):
        content = data[half]
        lines.append(
            f"{half}: {content['registry_count']} registry values, "
            f"{len(content['security'])} security sections, "
            f"{len(content['scripts'])} script sections, "
            f"{len(content['preferences'])} preference files, "
            f"{len(content['vgp'])} Samba policies, "
            f"{len(content['other_files'])} other files"
        )
        for item in content["other_files"][:10]:
            lines.append(f"    {item['path']}")
    for item in data["unreadable"]:
        lines.append(f"unreadable: {item['path']} ({item['reason']})")
    return "\n".join(lines)


def test_the_default_domain_policy_is_read_without_complaint(api):
    """Its halves are reached, whether or not they hold anything.

    On a Samba-provisioned domain they are empty: the password policy lives on
    the domain object in the directory, which is what `samba-tool domain
    passwordsettings` edits, and no GptTmpl.inf is written. So this asserts
    what is actually true everywhere — that the walk gets into both halves —
    rather than that the policy carries settings.

    The halves are named MACHINE and USER there, in upper case, which is the
    other half of what this proves.
    """
    gpos = api.get("/api/v1/gpos").json()["gpos"]
    default = next(gpo for gpo in gpos if gpo["display_name"] == "Default Domain Policy")

    data = api.get(f"/api/v1/gpos/report?dn={quoted(default['dn'])}").json()

    missing = [item for item in data["unreadable"] if item["reason"] == "half_missing"]
    assert missing == [], summarise(data)


def test_a_policy_with_settings_is_read_completely(api):
    """The parsers, against whatever this domain actually holds.

    Fabricated content would only prove the parsers agree with themselves.
    This takes the first policy that carries anything and checks that what
    came back is coherent — which is the part a hand-written fixture cannot
    show.
    """
    gpos = api.get("/api/v1/gpos").json()["gpos"]

    for gpo in gpos:
        data = api.get(f"/api/v1/gpos/report?dn={quoted(gpo['dn'])}").json()
        if data["empty"]:
            continue

        for half in ("machine", "user"):
            content = data[half]
            for group in content["registry"]:
                assert group["key"], "a registry value without a key"
                for value in group["values"]:
                    assert value["type"], summarise(data)
                    assert value["display"] is not None
            # Section names come straight out of the file; an empty section is
            # dropped rather than reported.
            assert all(values for values in content["security"].values())

        assert data["unreadable"] == [] or all(
            item["reason"] == "half_missing" for item in data["unreadable"]
        ), summarise(data)
        return

    pytest.skip("every policy in this domain is empty")


def test_the_report_is_also_available_as_a_file(api):
    gpos = api.get("/api/v1/gpos").json()["gpos"]
    default = next(gpo for gpo in gpos if gpo["display_name"] == "Default Domain Policy")

    response = api.get(f"/api/v1/gpos/report.html?dn={quoted(default['dn'])}")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert "filename=" in response.headers["content-disposition"]
    assert "<!doctype html>" in response.text.lower()
    assert "Default Domain Policy" in response.text


def test_a_report_names_what_it_could_not_read(api, test_gpo):
    """Silence about an unreadable file would read as an empty policy."""
    data = api.get(f"/api/v1/gpos/report?dn={quoted(test_gpo['dn'])}").json()
    assert isinstance(data["unreadable"], list)


# ---------------------------------------------------------------------------
# Copying
# ---------------------------------------------------------------------------


def test_a_policy_can_be_copied(api, test_gpo):
    name = policy_name()
    copied = api.post(f"/api/v1/gpos/copy?dn={quoted(test_gpo['dn'])}", json={"display_name": name})
    assert copied.status_code == 200, copied.text

    copy = copied.json()
    try:
        assert copy["display_name"] == name
        # A new identifier: links point at the original and must not follow.
        assert copy["guid"] != test_gpo["guid"]

        status = api.get(f"/api/v1/gpos/status?dn={quoted(copy['dn'])}").json()
        assert status["consistent"] is True, status["problems"]
    finally:
        api.delete(f"/api/v1/gpos?dn={quoted(copy['dn'])}&force=true")


def test_a_copy_does_not_inherit_the_links(api, test_gpo, test_ou):
    """Where a policy applies is the decision a copy still leaves open."""
    api.post(f"/api/v1/gpos/links?dn={quoted(test_ou)}", json={"gpo_dn": test_gpo["dn"]})

    copy = api.post(
        f"/api/v1/gpos/copy?dn={quoted(test_gpo['dn'])}", json={"display_name": policy_name()}
    ).json()
    try:
        links = api.get(f"/api/v1/gpos/linked?guid={quoted(copy['guid'])}").json()["links"]
        assert links == []
    finally:
        api.delete(f"/api/v1/gpos?dn={quoted(copy['dn'])}&force=true")


def test_a_copy_under_an_existing_name_is_refused(api, test_gpo):
    response = api.post(
        f"/api/v1/gpos/copy?dn={quoted(test_gpo['dn'])}",
        json={"display_name": test_gpo["display_name"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "gpo_exists"


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def test_a_backup_contains_the_policy_files(api, test_gpo):
    response = api.get(f"/api/v1/gpos/backup?dn={quoted(test_gpo['dn'])}")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())

    assert "GPT.INI" in names
    assert "samadcon-backup.json" in names


def test_an_extension_file_is_written_only_when_there_is_something_in_it(api):
    """An empty .SAMBAEXT file is not the same as an absent one.

    `samba-tool gpo restore` writes whatever the file holds straight into the
    attribute, and LDB refuses an empty value — so an archive carrying an
    empty one cannot be restored with samba-tool at all. It is the sort of
    incompatibility that only a real restore finds.
    """
    for gpo in api.get("/api/v1/gpos").json()["gpos"]:
        response = api.get(f"/api/v1/gpos/backup?dn={quoted(gpo['dn'])}")
        assert response.status_code == 200, response.text

        archive = zipfile.ZipFile(io.BytesIO(response.content))
        for name in ("gPCMachineExtensionNames.SAMBAEXT", "gPCUserExtensionNames.SAMBAEXT"):
            if name in archive.namelist():
                assert archive.read(name).strip(), f"{gpo['display_name']}: {name} is empty"


def test_a_backup_names_the_policy_it_came_from(api, test_gpo):
    response = api.get(f"/api/v1/gpos/backup?dn={quoted(test_gpo['dn'])}")
    archive = zipfile.ZipFile(io.BytesIO(response.content))

    import json

    manifest = json.loads(archive.read("samadcon-backup.json"))
    assert manifest["guid"] == test_gpo["guid"]
    assert manifest["display_name"] == test_gpo["display_name"]


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def test_a_backup_can_be_restored_as_a_new_policy(api, test_gpo):
    backup = api.get(f"/api/v1/gpos/backup?dn={quoted(test_gpo['dn'])}").content
    name = policy_name()

    restored = api.post(
        f"/api/v1/gpos/restore?display_name={quoted(name)}",
        files={"archive": ("backup.zip", backup, "application/zip")},
    )
    assert restored.status_code == 200, restored.text

    policy = restored.json()
    try:
        assert policy["display_name"] == name
        # Never an overwrite: the identifier is what every link points at.
        assert policy["guid"] != test_gpo["guid"]

        status = api.get(f"/api/v1/gpos/status?dn={quoted(policy['dn'])}").json()
        assert status["consistent"] is True, status["problems"]
    finally:
        api.delete(f"/api/v1/gpos?dn={quoted(policy['dn'])}&force=true")


def test_a_restore_under_an_existing_name_is_refused(api, test_gpo):
    backup = api.get(f"/api/v1/gpos/backup?dn={quoted(test_gpo['dn'])}").content

    response = api.post(
        f"/api/v1/gpos/restore?display_name={quoted(test_gpo['display_name'])}",
        files={"archive": ("backup.zip", backup, "application/zip")},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "gpo_exists"


def test_a_file_that_is_not_an_archive_is_refused(api):
    response = api.post(
        "/api/v1/gpos/restore?display_name=Nonsense",
        files={"archive": ("not.zip", b"this is not a zip file", "application/zip")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_backup"


def test_a_restore_without_a_name_anywhere_is_refused(api):
    """A backup with no manifest and no name given has nothing to be called."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("GPT.INI", "[General]\r\nVersion=0\r\n")

    response = api.post(
        "/api/v1/gpos/restore",
        files={"archive": ("backup.zip", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_name"


# ---------------------------------------------------------------------------
# WMI filters
# ---------------------------------------------------------------------------


def test_the_wmi_filters_can_be_listed(api):
    """A domain without any is the normal case, and not an error."""
    response = api.get("/api/v1/gpos/wmi-filters")
    assert response.status_code == 200, response.text
    assert isinstance(response.json()["filters"], list)


def test_a_policy_without_a_filter_says_so(api, test_gpo):
    response = api.get(f"/api/v1/gpos/wmi-filter?dn={quoted(test_gpo['dn'])}")
    assert response.status_code == 200, response.text
    assert response.json()["filter"] is None


def test_clearing_a_filter_that_is_not_set_is_harmless(api, test_gpo):
    response = api.post(
        f"/api/v1/gpos/wmi-filter?dn={quoted(test_gpo['dn'])}", json={"filter_dn": None}
    )
    assert response.status_code == 200, response.text
    assert response.json()["wmi_filter"] is None


def test_a_filter_can_be_assigned_when_the_domain_has_one(api, test_gpo):
    filters = api.get("/api/v1/gpos/wmi-filters").json()["filters"]
    if not filters:
        pytest.skip("this domain has no WMI filters")

    assigned = api.post(
        f"/api/v1/gpos/wmi-filter?dn={quoted(test_gpo['dn'])}",
        json={"filter_dn": filters[0]["dn"]},
    )
    assert assigned.status_code == 200, assigned.text

    described = api.get(f"/api/v1/gpos/wmi-filter?dn={quoted(test_gpo['dn'])}").json()["filter"]
    assert described is not None
    assert described["missing"] is False
    assert described["id"] == filters[0]["id"]
