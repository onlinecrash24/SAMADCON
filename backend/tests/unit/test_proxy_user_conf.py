"""The nginx half of believing an identity provider's user name.

The proxy in front names the user in a header of its own choosing —
Remote-User for Authelia, X-authentik-username for Authentik. nginx in the
container passes it to the application as X-Samadcon-Idp-User, and only for a
request that arrived from a proxy named in SAMADCON_TRUSTED_PROXIES. From
anyone else, and when nothing is configured, the value is empty, and an empty
proxy_set_header drops the header: whatever a browser sends as
X-Samadcon-Idp-User never gets through.

The configuration is written by a small script the entrypoint calls before
nginx starts, so it can be run here on its own: installed in the test image,
from the repository elsewhere. Only a machine without a POSIX shell skips it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALLED = Path("/usr/local/bin/samadcon-proxy-user-conf")
IN_REPOSITORY = Path(__file__).resolve().parents[3] / "docker" / "proxy-user-conf.sh"
SCRIPT = INSTALLED if INSTALLED.exists() else IN_REPOSITORY
SHELL = shutil.which("sh")

needs_sh = pytest.mark.skipif(SHELL is None, reason="needs a POSIX shell")


def run(**env: str) -> subprocess.CompletedProcess[str]:
    assert SCRIPT.exists(), f"{SCRIPT} is missing"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in ("SAMADCON_PROXY_USER_HEADER", "SAMADCON_TRUSTED_PROXIES")
    }
    environment.update(env)
    return subprocess.run(
        [SHELL, str(SCRIPT)], capture_output=True, text=True, env=environment, check=False
    )


@needs_sh
def test_nothing_configured_believes_no_one():
    result = run()
    assert result.returncode == 0
    assert "$samadcon_idp_user" in result.stdout
    assert "$http_" not in result.stdout


@needs_sh
def test_a_header_and_a_proxy_are_believed_from_that_proxy_only():
    result = run(
        SAMADCON_PROXY_USER_HEADER="Remote-User",
        SAMADCON_TRUSTED_PROXIES="172.29.0.1, 10.0.0.0/8",
    )
    assert result.returncode == 0
    out = result.stdout
    # The hop that connected, before real_ip replaced it with the browser.
    assert "geo $realip_remote_addr $samadcon_trusted_hop" in out
    assert "172.29.0.1 1;" in out
    assert "10.0.0.0/8 1;" in out
    assert "default 0;" in out
    # nginx's name for the header: lower case, dashes as underscores.
    assert "1 $http_remote_user;" in out
    assert 'default "";' in out


@needs_sh
def test_authentiks_header_name_becomes_its_variable():
    result = run(
        SAMADCON_PROXY_USER_HEADER="X-authentik-username",
        SAMADCON_TRUSTED_PROXIES="172.29.0.1",
    )
    assert "1 $http_x_authentik_username;" in result.stdout


@needs_sh
def test_a_header_without_a_trusted_proxy_believes_no_one():
    result = run(SAMADCON_PROXY_USER_HEADER="Remote-User")
    assert result.returncode == 0
    assert "$http_" not in result.stdout


@needs_sh
@pytest.mark.parametrize("bad", ["Remote User", "Remote-User;", "x}; include /etc/passwd", "a$b"])
def test_a_header_name_that_is_not_a_token_is_refused(bad):
    """It would be written into nginx's configuration as it stands."""
    result = run(SAMADCON_PROXY_USER_HEADER=bad, SAMADCON_TRUSTED_PROXIES="172.29.0.1")
    assert result.returncode != 0
    assert result.stdout == ""
    assert "SAMADCON_PROXY_USER_HEADER" in result.stderr


@needs_sh
@pytest.mark.parametrize("bad", ["172.29.0.1; evil", "proxy.example.com", "1.2.3.4}"])
def test_a_proxy_that_is_not_an_address_is_refused(bad):
    result = run(SAMADCON_PROXY_USER_HEADER="Remote-User", SAMADCON_TRUSTED_PROXIES=bad)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "SAMADCON_TRUSTED_PROXIES" in result.stderr


def test_the_api_location_always_sets_the_header():
    """Set unconditionally, so an empty value drops whatever the browser sent."""
    template = (Path(__file__).resolve().parents[3] / "docker" / "nginx.conf.template")
    if not template.exists():
        template = Path("/etc/samadcon/nginx.conf.template")
    text = template.read_text(encoding="utf-8")
    assert "include ${SAMADCON_CONF_DIR}/proxy-user.conf;" in text
    assert "proxy_set_header   X-Samadcon-Idp-User $samadcon_idp_user;" in text
