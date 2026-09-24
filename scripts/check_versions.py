"""The version is stated once. This checks that nothing says otherwise.

v0.5.2 shipped reporting itself as 0.5.1: three files carried the number and
the release commit raised two of them. Every installation then showed the wrong
version on its sign-in screen, at ``/api/v1/health``, and to ``samadconctl
--version``. It was found by a reader, not by the project.

Two of those three files no longer disagree by construction —
``pyproject.toml`` reads the attribute out of ``samadcon/__init__.py``. What is
left is checked here:

* ``frontend/package.json``, which npm requires to carry a version and which
  nothing reads at runtime — precisely the kind of field that drifts, because
  being wrong costs nothing until someone believes it;
* the git tag, on a tag build. This catches the case the structural fix cannot:
  tagging v0.5.4 and forgetting to raise anything at all;
* that the single-source arrangement is still in place, so it cannot be undone
  by someone putting a literal ``version`` back into ``pyproject.toml``;
* that the two copies of the deployment compose file still describe the same
  stack. One is in the project root, where ``docker compose`` finds it without
  being told; the other sits under ``docker/`` beside the Dockerfile. Two files
  holding one thing is exactly the arrangement the version check exists for, so
  it is checked here rather than remembered.

Imports nothing from ``samadcon``: this runs in the lint job, which has no
samba bindings, and parsing beats importing for a value that must be a literal
anyway.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = (ROOT / "docker-compose.yml", ROOT / "docker" / "docker-compose.yml")
INIT = ROOT / "backend" / "samadcon" / "__init__.py"
PYPROJECT = ROOT / "backend" / "pyproject.toml"
PACKAGE_JSON = ROOT / "frontend" / "package.json"


def source_version() -> str:
    """The one place the version is written, read without importing it."""
    tree = ast.parse(INIT.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__version__":
                value = ast.literal_eval(node.value)
                if not isinstance(value, str):
                    raise SystemExit(
                        f"{INIT}: __version__ is not a string literal. setuptools "
                        f"reads this attribute statically; anything else sends it "
                        f"back to importing the module, and the samba bindings are "
                        f"not available at build time."
                    )
                return value
    raise SystemExit(f"{INIT}: no __version__ found")


def problems(version: str) -> list[str]:
    found: list[str] = []

    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    if "version" in project:
        found.append(
            f"{PYPROJECT} carries a literal version ({project['version']!r}) again. "
            f"It should declare dynamic = [\"version\"] and read the attribute out "
            f"of {INIT.name} — two files holding the number is how the last one "
            f"went wrong."
        )
    elif "version" not in project.get("dynamic", []):
        found.append(f"{PYPROJECT}: neither a literal version nor dynamic = [\"version\"]")

    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    if package.get("version") != version:
        found.append(
            f"{PACKAGE_JSON} says {package.get('version')!r}, "
            f"{INIT.name} says {version!r}"
        )

    found.extend(compose_problems())

    # Set by the workflow only on a tag build; empty every other time.
    tag = (os.environ.get("EXPECTED_TAG") or "").strip().lstrip("v")
    if tag and tag != version:
        found.append(
            f"the tag says {tag!r}, {INIT.name} says {version!r} — "
            f"either the tag is wrong or the version was never raised"
        )

    return found


def _body(text: str) -> str:
    """Everything from ``services:`` on — the file without its header.

    The two headers differ on purpose: each says where the other one is. Below
    that, the files are one file, comments included, because the comments are
    where the settings are explained and a reader of either copy should get
    the same explanation.
    """
    normalised = text.replace("\r\n", "\n")
    # Anchored at the start of a line, which includes the very first one: one
    # copy has a header above `services:` and the other begins with it, and
    # searching for "\nservices:" made that missing newline look like a
    # difference in the stack. It did, once, before this line was written.
    found = re.search(r"^services:", normalised, re.MULTILINE)
    return normalised[found.start():] if found else normalised


def compose_problems() -> list[str]:
    """The two deployment compose files must be the same file.

    Compared as text rather than as parsed YAML, for two reasons: the lint job
    installs ruff and pip-audit and nothing else, so there is no YAML parser to
    reach for; and a comment that drifted would pass a parsed comparison while
    telling the two readers different things.
    """
    root, copy = COMPOSE
    if not copy.exists():
        return [f"{copy} is missing; it is the copy of {root.name} kept beside the Dockerfile"]
    if _body(root.read_text(encoding="utf-8")) != _body(copy.read_text(encoding="utf-8")):
        return [
            f"{root} and {copy} have drifted apart below their headers. "
            f"They are two copies of one file on purpose — change both, or "
            f"copy one over the other from `services:` down."
        ]
    return []


def main() -> int:
    version = source_version()
    found = problems(version)

    if found:
        print("Something that has to agree with itself does not:\n", file=sys.stderr)
        for problem in found:
            print(f"  - {problem}", file=sys.stderr)
        print(
            f"\nThe version lives in {INIT.relative_to(ROOT)} and nowhere else — "
            f"raise it there and in frontend/package.json. The two deployment "
            f"compose files are one file in two places.",
            file=sys.stderr,
        )
        return 1

    where = "everywhere" if not os.environ.get("EXPECTED_TAG") else "everywhere, tag included"
    print(f"version {version} — agreed {where}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
