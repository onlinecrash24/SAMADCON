"""A policy's folders deeper than SAMADCON walks are said so, not dropped.

Copying and backing up a GPO walked its SYSVOL folder eight levels deep and
stopped there without a word: whatever lay below was simply not in the copy
or the backup. The report did the same. Found by an outside review.
"""

from __future__ import annotations

from typing import Any

import pytest

from samadcon.core.errors import InvalidRequest
from samadcon.gpo import report, transfer

BASE = "domain\\Policies\\{GUID}"


class Share:
    """A SYSVOL folder from a list of file paths relative to BASE."""

    def __init__(self, files: list[str], empty_dirs: tuple[str, ...] = ()) -> None:
        self.files = files
        self.empty_dirs = empty_dirs

    def listdir(self, path: str) -> list[dict[str, Any]]:
        prefix = "" if path == BASE else path[len(BASE) + 1 :] + "\\"
        children: dict[str, bool] = {}
        for item in [*self.files, *self.empty_dirs]:
            if not item.startswith(prefix):
                continue
            rest = item[len(prefix) :].split("\\")
            is_dir = len(rest) > 1 or item in self.empty_dirs
            children[rest[0]] = children.get(rest[0], False) or is_dir
        return [
            {"name": name, "path": f"{path}\\{name}", "is_directory": is_dir}
            for name, is_dir in sorted(children.items())
        ]


def nested(levels: int) -> str:
    """A file *levels* deep: level 1 sits directly in the GPO folder."""
    return "\\".join([f"d{i}" for i in range(1, levels)] + ["file.txt"])


def test_eight_levels_are_copied_whole():
    entries = transfer._entries(Share([nested(8)]), BASE)
    assert any(entry["path"].endswith("file.txt") for entry in entries)


def test_a_ninth_level_stops_the_copy_rather_than_leaving_it_out():
    with pytest.raises(InvalidRequest) as caught:
        transfer._entries(Share([nested(9)]), BASE)
    assert caught.value.code == "gpo_too_deep"


def test_an_empty_folder_at_the_limit_loses_nothing_and_passes():
    empty = "\\".join(f"d{i}" for i in range(1, 9))
    transfer._entries(Share([nested(3)], empty_dirs=(empty,)), BASE)


def test_the_report_says_what_it_did_not_read():
    skipped: list[dict[str, Any]] = []
    files = report._walk(Share([nested(9), nested(2)]), BASE, skipped=skipped)
    assert any(path.endswith("file.txt") for path in files)
    assert len(skipped) == 1
    assert "d8" in skipped[0]["path"]
