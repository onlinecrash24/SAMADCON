"""Every error code the backend can send has words in the interface's German.

The interface translates an error by its stable code and falls back to the
server's English sentence when it has none. That fallback is right for a code
it has never heard of, and wrong as a habit: by September 2026, 97 of the 199
codes the backend raised had no German entry, and an administrator working in
German met them in English — a refused template among them, found on a test
against a real domain controller.

So this lists every code the backend raises and fails on any the German
catalogue lacks. Codes are read from the syntax tree, not grepped, because a
raise spans lines and a code sits wherever the keyword falls:

* ``code="..."`` in any call — the exception constructors;
* the tables in ``core/errors.py`` that map LDAP results and NT status values
  to a class, a code, a message and a hint;
* ``code = "..."`` on the exception classes themselves, the default a raise
  without its own code gets.

English needs no check here: the catalogue is typed, so a German key without
an English one does not compile.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend" / "samadcon"
MESSAGES = ROOT / "frontend" / "src" / "i18n" / "messages.ts"
ERRORS = BACKEND / "core" / "errors.py"


def raised_codes() -> dict[str, str]:
    """Every code, with one place it comes from."""
    found: dict[str, str] = {}

    def note(code: object, path: Path, line: int) -> None:
        if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]*", code):
            found.setdefault(code, f"{path.relative_to(ROOT).as_posix()}:{line}")

    for path in sorted(BACKEND.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == "code" and isinstance(keyword.value, ast.Constant):
                        note(keyword.value.value, path, node.lineno)
            elif isinstance(node, ast.ClassDef):
                for statement in node.body:
                    target = None
                    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                        target, value = statement.targets[0], statement.value
                    elif isinstance(statement, ast.AnnAssign):
                        target, value = statement.target, statement.value
                    if (
                        isinstance(target, ast.Name)
                        and target.id == "code"
                        and isinstance(value, ast.Constant)
                    ):
                        note(value.value, path, statement.lineno)
            elif path == ERRORS and isinstance(node, ast.Tuple) and len(node.elts) >= 3:
                # (ExceptionClass, "code", "message", hint)
                first, second = node.elts[0], node.elts[1]
                if isinstance(first, ast.Name) and isinstance(second, ast.Constant):
                    note(second.value, path, node.lineno)
    return found


def german_keys() -> set[str]:
    text = MESSAGES.read_text(encoding="utf-8")
    german = text[: text.index("export const en")]
    return set(re.findall(r"^\s*'error\.([a-z0-9_]+)'\s*:", german, flags=re.M))


def main() -> int:
    codes = raised_codes()
    known = german_keys()
    missing = sorted(code for code in codes if code not in known)
    if missing:
        where = MESSAGES.relative_to(ROOT).as_posix()
        print(f"{len(missing)} error code(s) without a German entry in {where}:")
        for code in missing:
            print(f"  error.{code}   ({codes[code]})")
        return 1
    print(f"every error code has German words — {len(codes)} codes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
