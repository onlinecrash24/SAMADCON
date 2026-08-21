"""The dependency list, in the two shapes an audit needs.

A reader found `python-multipart>=0.0.9` and was right that the floor was too
low. What made it worth a check rather than a fix is that an audit of the
*installed* packages would never have found it: `>=0.0.9` resolves to the
newest release, which is fine, so a fresh build was never exposed. The floor
was the problem, and nothing was looking at floors.

So this prints the same dependencies two ways, and CI audits both:

``--declared`` (the default)
    The constraints as written. Audited, this answers "is what a build gets
    today safe?" — the question that matters to whoever pulls the image.

``--floors``
    Every ``>=`` pinned to ``==``. Audited, this answers "do the constraints
    permit anything vulnerable?" — the question the reader was really asking,
    and the one nothing else in this repository asks.

Running both found two more floors than the report did, and then something
worse: at their floors the dependencies could not be installed together at
all. Nobody had ever resolved that combination.

Reads pyproject.toml directly rather than importing samadcon, because the lint
job has no samba bindings.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "backend" / "pyproject.toml"


def dependencies() -> list[str]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]


def at_floors(requirement: str) -> str:
    """``fastapi>=0.141.1`` becomes ``fastapi==0.141.1``.

    Only ``>=`` is rewritten. A dependency written any other way is passed
    through untouched rather than guessed at — a wrong pin here would audit
    something the project never declared.
    """
    return requirement.replace(">=", "==", 1) if ">=" in requirement else requirement


def main(argv: list[str]) -> int:
    floors = "--floors" in argv
    for requirement in dependencies():
        print(at_floors(requirement) if floors else requirement)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
