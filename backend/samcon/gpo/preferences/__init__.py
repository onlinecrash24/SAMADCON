"""Group policy preferences — the "Einstellungen" branch of the editor.

One XML file per type per half, each with its own extension GUID. Drive maps,
registry values, files and folders came first; shortcuts, environment
variables and printers followed and brought the three cases that shaped the
model — a status line that is not the name, an action that is not the first
attribute, and one file holding three kinds of element.

The remaining types (scheduled tasks, local users and groups, services) follow
the same shape and are added as reference files for them appear.
"""

from samcon.gpo.preferences.catalogue import (
    ACTIONS,
    TYPES,
    ItemKind,
    PreferenceType,
    type_for,
)
from samcon.gpo.preferences.store import read, read_all, write

__all__ = [
    "ACTIONS",
    "TYPES",
    "ItemKind",
    "PreferenceType",
    "read",
    "read_all",
    "type_for",
    "write",
]
