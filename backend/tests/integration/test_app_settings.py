"""SAMADCON's settings in the domain, against a live Samba AD DC.

The object is CN=SAMADCON,CN=Program Data; it holds one JSON document in
msDS-Settings. The test restores what it found, so a domain that had
settings keeps them.
"""

from __future__ import annotations

import pytest

from tests.integration.conftest import unique

pytestmark = pytest.mark.integration


def _save(api, fields: list[str]) -> dict:
    current = api.get("/api/v1/settings").json()
    saved = api.put(
        "/api/v1/settings",
        json={"required_user_fields": fields, "expected": current["stamp"]},
    )
    assert saved.status_code == 200, saved.text
    return saved.json()


def test_mandatory_mail_is_stored_in_the_domain_and_enforced(api, test_ou):
    before = api.get("/api/v1/settings").json()
    assert before["dn"].startswith("CN=SAMADCON,CN=Program Data,")
    previous = before["settings"]["users"]["required_fields"]

    try:
        after = _save(api, ["mail"])
        assert after["exists"] is True
        assert after["settings"]["users"]["required_fields"] == ["mail"]

        sam = unique("rq")
        refused = api.post(
            "/api/v1/users",
            json={"parent_dn": test_ou, "sam_account_name": sam, "enabled": False},
        )
        assert refused.status_code == 400
        assert refused.json()["code"] == "required_field_missing"

        created = api.post(
            "/api/v1/users",
            json={
                "parent_dn": test_ou,
                "sam_account_name": sam,
                "enabled": False,
                "attributes": {"mail": f"{sam}@test.lan"},
            },
        )
        assert created.status_code == 200, created.text
        assert created.json()["attributes"]["mail"] == f"{sam}@test.lan"
    finally:
        _save(api, previous)


def test_a_stale_save_is_refused(api):
    current = api.get("/api/v1/settings").json()
    stale = api.put(
        "/api/v1/settings",
        json={
            "required_user_fields": current["settings"]["users"]["required_fields"],
            "expected": current["stamp"] + "-old",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "settings_changed"
