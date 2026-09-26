"""The lock the image installs from agrees with what pyproject.toml declares.

The image installs its dependencies with ``pip install --require-hashes -r
backend/requirements.lock``: exactly those versions, byte for byte. That is
only worth something while the lock still satisfies what the project says it
needs — a floor raised in pyproject.toml and forgotten in the lock would ship
the old version anyway, and nothing would say so.

So two things are checked, and deliberately not a third:

* every runtime dependency declared in pyproject.toml has a pin in the lock
  that its specifier accepts;
* every pin in the lock carries at least one hash, so --require-hashes can
  hold the build to it.

What is not checked is whether the lock is the *newest* resolution. Doing that
would mean re-resolving against PyPI on every push and failing whenever
anything upstream released — which is noise, not a finding. Newer versions
come in by regenerating the lock, deliberately:

    uv pip compile backend/pyproject.toml --generate-hashes --python-version 3.13 \\
        --python-platform x86_64-unknown-linux-gnu -o backend/requirements.lock

Needs ``packaging``, which the lint job has through pip-audit.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "backend" / "pyproject.toml"
LOCK = ROOT / "backend" / "requirements.lock"

# The image: Debian trixie, Python 3.13, amd64. Markers are judged for it.
TARGET = {
    "python_version": "3.13",
    "python_full_version": "3.13.5",
    "sys_platform": "linux",
    "platform_system": "Linux",
    "platform_machine": "x86_64",
    "os_name": "posix",
    "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
    "extra": "",
}

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)")


def pins(text: str) -> tuple[dict[str, str], list[str]]:
    """The pinned versions by canonical name, and the pins without a hash."""
    found: dict[str, str] = {}
    unhashed: list[str] = []
    current: str | None = None
    hashed = False
    for line in text.splitlines():
        stripped = line.strip()
        match = _PIN.match(stripped)
        if match:
            if current is not None and not hashed:
                unhashed.append(current)
            current = canonicalize_name(match.group(1))
            found[current] = match.group(2)
            hashed = False
        elif stripped.startswith("--hash="):
            hashed = True
    if current is not None and not hashed:
        unhashed.append(current)
    return found, unhashed


def problems() -> list[str]:
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
    if not LOCK.exists():
        return [f"{LOCK.relative_to(ROOT)} is missing; the image installs from it"]
    locked, unhashed = pins(LOCK.read_text(encoding="utf-8"))

    found: list[str] = []
    for text in declared:
        requirement = Requirement(text)
        if requirement.marker is not None and not requirement.marker.evaluate(TARGET):
            continue
        name = canonicalize_name(requirement.name)
        version = locked.get(name)
        if version is None:
            found.append(f"{requirement.name} is declared and not in the lock")
        elif not requirement.specifier.contains(Version(version), prereleases=True):
            found.append(
                f"{requirement.name}: the lock has {version}, pyproject.toml asks for "
                f"{requirement.specifier}"
            )
    for name in unhashed:
        found.append(f"{name} is pinned without a hash; --require-hashes would refuse the build")
    return found


def main() -> int:
    found = problems()
    if found:
        print("The lock and pyproject.toml disagree:\n", file=sys.stderr)
        for problem in found:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nRegenerate the lock (the command is at the top of scripts/check_lock.py).",
            file=sys.stderr,
        )
        return 1
    locked, _ = pins(LOCK.read_text(encoding="utf-8"))
    print(f"lock agrees with pyproject.toml — {len(locked)} pins, all hashed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
