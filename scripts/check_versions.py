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
  by someone putting a literal ``version`` back into ``pyproject.toml``.

Imports nothing from ``samadcon``: this runs in the lint job, which has no
samba bindings, and parsing beats importing for a value that must be a literal
anyway.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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

    # Set by the workflow only on a tag build; empty every other time.
    tag = (os.environ.get("EXPECTED_TAG") or "").strip().lstrip("v")
    if tag and tag != version:
        found.append(
            f"the tag says {tag!r}, {INIT.name} says {version!r} — "
            f"either the tag is wrong or the version was never raised"
        )

    return found


def main() -> int:
    version = source_version()
    found = problems(version)

    if found:
        print("The version does not agree with itself:\n", file=sys.stderr)
        for problem in found:
            print(f"  - {problem}", file=sys.stderr)
        print(
            f"\nThe version lives in {INIT.relative_to(ROOT)} and nowhere else. "
            f"Raise it there and in frontend/package.json.",
            file=sys.stderr,
        )
        return 1

    where = "everywhere" if not os.environ.get("EXPECTED_TAG") else "everywhere, tag included"
    print(f"version {version} — agreed {where}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
