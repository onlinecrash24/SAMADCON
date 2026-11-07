"""Every page carries the security headers, not only the API.

nginx inherits ``add_header`` into a location only when that location sets
none of its own. ``/`` and ``/assets/`` set Cache-Control, and so lost all
five headers of the server block: the React page went out without CSP, HSTS
or X-Frame-Options, while ``/api/v1/health`` had them. Measured by Rowie
against 0.6.28 (``GET /`` answered with ``cache-control: no-cache`` only).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

HEADERS = (
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Content-Security-Policy",
)


def _template() -> str:
    path = Path(__file__).resolve().parents[3] / "docker" / "nginx.conf.template"
    if not path.exists():
        path = Path("/etc/samadcon/nginx.conf.template")
    return path.read_text(encoding="utf-8")


def _block(text: str, start: int) -> str:
    """The text from *start* to the brace that closes the block opened there."""
    depth = 0
    for index in range(text.index("{", start), len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError("unbalanced braces")


def _headers(block: str) -> dict[str, str]:
    return dict(re.findall(r"^\s*add_header\s+(\S+)\s+(.+?);\s*$", block, re.M))


def _https_server() -> str:
    text = _template()
    for match in re.finditer(r"^\s*server\s*\{", text, re.M):
        block = _block(text, match.start())
        if "listen 8443" in block:
            return block
    raise AssertionError("no server block listens on 8443")


def _locations(server: str) -> dict[str, str]:
    return {
        match.group(1): _block(server, match.start())
        for match in re.finditer(r"location\s+(\S+(?:\s+\S+)?)\s*\{", server)
    }


def test_the_https_server_sets_all_five():
    outside = _https_server()
    for block in _locations(outside).values():
        outside = outside.replace(block, "")
    assert set(_headers(outside)) >= set(HEADERS)


@pytest.mark.parametrize("location", ["/", "/assets/"])
def test_a_location_with_its_own_headers_repeats_all_five(location):
    server = _https_server()
    outside = server
    blocks = _locations(server)
    for block in blocks.values():
        outside = outside.replace(block, "")
    wanted = {name: _headers(outside)[name] for name in HEADERS}

    own = _headers(blocks[location])
    assert own, f"{location} sets no header of its own; the test assumes it does"
    assert {name: own.get(name) for name in HEADERS} == wanted


def test_every_location_either_inherits_or_repeats_them():
    server = _https_server()
    outside = server
    blocks = _locations(server)
    for block in blocks.values():
        outside = outside.replace(block, "")
    for location, block in blocks.items():
        own = _headers(block)
        if own:
            missing = [name for name in HEADERS if name not in own]
            assert missing == [], f"{location} drops {missing}"
