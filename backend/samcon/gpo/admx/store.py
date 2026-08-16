"""The central store: administrative templates on SYSVOL.

``<realm>\\Policies\\PolicyDefinitions`` holds the ``.admx`` files and, one
directory per language, the ``.adml`` files that go with them. Every domain
member that edits policies reads the same set, which is the point of it being
central: a template installed once is available everywhere.

Two decisions:

* **Parsed once per domain and language, not per request.** A full Microsoft
  store is several hundred files; reading them over SMB for every click would
  make the editor unusable. The cache is invalidated by a fingerprint of the
  directory — names, sizes and whatever timestamp the SMB build reports —
  which is one listing rather than one read per file.
* **A missing central store is not an error.** A domain that has never had one
  is the normal state for Samba, and the editor says so instead of failing.
  Uploading templates is how it comes into being, which is also what
  ``samba-tool gpo admxload`` does.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from samcon.ad.connection import DirectoryConnection
from samcon.core.errors import Conflict, InvalidRequest, NotFound
from samcon.gpo import sysvol
from samcon.gpo.admx import parser
from samcon.gpo.admx.model import Catalogue

logger = logging.getLogger(__name__)

STORE_DIR = "Policies\\PolicyDefinitions"

# The language every Microsoft template ships with, and the fallback when the
# one that was asked for is not installed.
FALLBACK_LANGUAGE = "en-US"

# A central store is a few hundred files. The ceiling is a guard against a
# directory that is not one at all.
MAX_TEMPLATES = 2000

# Anything else in there is not ours to interpret.
ADMX_SUFFIX = ".admx"
ADML_SUFFIX = ".adml"


@dataclass
class _Cached:
    fingerprint: str
    catalogue: Catalogue
    loaded_at: datetime


# Shared between sessions on purpose: the templates are the same for everyone
# signed in to the same domain, and parsing them is the expensive part. Keyed
# by realm so two domains never see each other's.
_CACHE: dict[tuple[str, str], _Cached] = {}
_LOCK = threading.Lock()


def store_path(realm: str) -> str:
    return sysvol.join(realm, STORE_DIR)


# ---------------------------------------------------------------------------
# Looking at what is there
# ---------------------------------------------------------------------------


def describe(conn: DirectoryConnection) -> dict[str, Any]:
    """What the central store holds, without parsing any of it."""
    share = sysvol.sysvol_for(conn)
    base = store_path(conn.info.dns_domain)

    if not share.is_directory(base):
        return {
            "present": False,
            "path": base,
            "templates": [],
            "languages": [],
            "language": None,
        }

    entries = share.listdir(base)
    templates = sorted(
        (
            {"name": entry["name"], "size": entry["size"]}
            for entry in entries
            if not entry["is_directory"] and entry["name"].lower().endswith(ADMX_SUFFIX)
        ),
        key=lambda item: item["name"].lower(),
    )
    languages = sorted(
        entry["name"] for entry in entries if entry["is_directory"]
    )

    return {
        "present": True,
        "path": base,
        "templates": templates,
        "languages": languages,
        "language": choose_language(languages, None),
    }


def choose_language(available: list[str], wanted: str | None) -> str | None:
    """Which language directory to read the text from.

    An exact match first, then one for the same language in another region —
    ``de-AT`` will do when ``de-DE`` was asked for and is missing, because the
    text is the same in all but a handful of places. English is the last
    resort because every template ships it; a policy tree in a language nobody
    asked for beats one with no labels at all.
    """
    if not available:
        return None

    lowered = {name.lower(): name for name in available}

    if wanted:
        target = wanted.strip().lower()
        if target in lowered:
            return lowered[target]
        prefix = target.split("-")[0]
        for name in sorted(lowered):
            if name.split("-")[0] == prefix:
                return lowered[name]

    if FALLBACK_LANGUAGE.lower() in lowered:
        return lowered[FALLBACK_LANGUAGE.lower()]
    for name in sorted(lowered):
        if name.startswith("en"):
            return lowered[name]
    return lowered[sorted(lowered)[0]]


def _fingerprint(entries: list[dict[str, Any]], language: str | None) -> str:
    """What has to change before the cache is stale.

    Built from the listing rather than from the files: one round trip instead
    of one per template. A file replaced by another of the same size and
    timestamp would slip through, which is a trade the alternative does not
    justify — and the refresh button is there for it.
    """
    parts = [language or ""]
    for entry in sorted(entries, key=lambda item: item["name"].lower()):
        parts.append(f"{entry['name']}:{entry['size']}:{entry.get('changed') or ''}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def catalogue_for(
    conn: DirectoryConnection, *, language: str | None = None, refresh: bool = False
) -> Catalogue:
    """The parsed templates for this domain, from the cache where possible."""
    share = sysvol.sysvol_for(conn)
    realm = conn.info.dns_domain
    base = store_path(realm)

    if not share.is_directory(base):
        raise NotFound(
            "This domain has no central store of administrative templates.",
            code="no_central_store",
            hint="Upload a template package to create one.",
            context={"path": base},
        )

    entries = share.listdir(base)
    languages = [entry["name"] for entry in entries if entry["is_directory"]]
    chosen = choose_language(languages, language)
    fingerprint = _fingerprint(entries, chosen)
    cache_key = (realm.lower(), (chosen or "").lower())

    if not refresh:
        with _LOCK:
            cached = _CACHE.get(cache_key)
        if cached is not None and cached.fingerprint == fingerprint:
            return cached.catalogue

    catalogue = _load(share, base, entries, chosen)

    with _LOCK:
        _CACHE[cache_key] = _Cached(fingerprint, catalogue, datetime.now(UTC))
    logger.info(
        "loaded %d policies from the central store of %s (%s)",
        len(catalogue.policies),
        realm,
        chosen or "no language",
    )
    return catalogue


def _load(
    share: sysvol.SysvolConnection,
    base: str,
    entries: list[dict[str, Any]],
    language: str | None,
) -> Catalogue:
    catalogue = Catalogue(language=language or "")

    admx_files = [
        entry
        for entry in entries
        if not entry["is_directory"] and entry["name"].lower().endswith(ADMX_SUFFIX)
    ]
    if len(admx_files) > MAX_TEMPLATES:
        catalogue.note(
            base, f"more than {MAX_TEMPLATES} templates; only the first were read"
        )
        admx_files = admx_files[:MAX_TEMPLATES]

    text_files = _language_files(share, base, language)

    for entry in sorted(admx_files, key=lambda item: item["name"].lower()):
        name = entry["name"]
        try:
            raw = share.read(entry["path"])
        except Exception as exc:  # noqa: BLE001
            catalogue.note(name, f"could not be read: {exc}")
            continue

        strings = _strings_for(share, text_files, name, catalogue)
        try:
            parser.parse_admx(raw, strings, catalogue, source=name)
        except Exception as exc:  # noqa: BLE001 — one bad template, not all
            catalogue.note(name, f"could not be parsed: {exc}")

    return catalogue


def _language_files(
    share: sysvol.SysvolConnection, base: str, language: str | None
) -> dict[str, str]:
    """The ``.adml`` files of the chosen language, by lower-case name."""
    if not language:
        return {}
    try:
        entries = share.listdir(sysvol.join(base, language))
    except Exception:
        logger.warning("cannot list the %s texts", language, exc_info=True)
        return {}

    return {
        entry["name"].lower(): entry["path"]
        for entry in entries
        if not entry["is_directory"] and entry["name"].lower().endswith(ADML_SUFFIX)
    }


def _strings_for(
    share: sysvol.SysvolConnection,
    text_files: dict[str, str],
    admx_name: str,
    catalogue: Catalogue,
) -> parser.Strings:
    """The text for one template.

    A template without one still loads: the policies exist and write the same
    values, only the labels are missing. Refusing it would turn a language
    problem into missing settings.
    """
    adml_name = admx_name[: -len(ADMX_SUFFIX)].lower() + ADML_SUFFIX
    path = text_files.get(adml_name)
    if path is None:
        catalogue.note(admx_name, "no text file for the chosen language")
        return parser.Strings()

    try:
        return parser.parse_adml(share.read(path))
    except Exception as exc:  # noqa: BLE001
        catalogue.note(adml_name, f"could not be parsed: {exc}")
        return parser.Strings()


def forget(realm: str | None = None) -> None:
    """Drop the cache, for one domain or entirely."""
    with _LOCK:
        if realm is None:
            _CACHE.clear()
            return
        for key in [item for item in _CACHE if item[0] == realm.lower()]:
            del _CACHE[key]


def cache_state() -> list[dict[str, Any]]:
    with _LOCK:
        return [
            {
                "realm": realm,
                "language": language,
                "policies": entry.catalogue.summary()["policies"],
                "loaded_at": entry.loaded_at.isoformat(),
            }
            for (realm, language), entry in _CACHE.items()
        ]


# ---------------------------------------------------------------------------
# Putting templates there
# ---------------------------------------------------------------------------


def upload(
    conn: DirectoryConnection, files: dict[str, bytes], *, overwrite: bool = False
) -> dict[str, Any]:
    """Add templates to the central store, creating it if needed.

    Names decide where a file goes: ``.admx`` into the store itself,
    ``.adml`` into the language directory it came in — the caller passes those
    as ``de-DE/example.adml``. That mirrors how the packages are shipped and
    means a whole package can be handed over unchanged.
    """
    share = sysvol.sysvol_for(conn)
    base = store_path(conn.info.dns_domain)

    # Everything is checked before anything is written. Windows reads the
    # store as a whole and gives up on **every** template when one file is
    # unreadable, so a package must land completely or not at all: a
    # definition written without the text file that belongs to it breaks the
    # domain's policy reporting just as thoroughly as a malformed file does.
    planned: list[tuple[str, bytes]] = []
    for name, data in files.items():
        relative = _safe_name(name)
        if relative is None:
            continue

        parser.validate(data, relative)

        if not overwrite and share.exists(sysvol.join(base, relative)):
            raise Conflict(
                "This template is already in the central store.",
                code="template_exists",
                hint="Replace it deliberately if that is what you mean.",
                context={"name": relative},
            )

        planned.append((relative, data))

    if not planned:
        raise InvalidRequest(
            "None of these files is an administrative template.",
            code="no_templates",
            hint="Expected .admx files and .adml files in a language directory.",
        )

    accepted: list[str] = []
    for relative, data in planned:
        target = sysvol.join(base, relative)
        parent = target.rsplit("\\", 1)[0]
        share.makedirs(parent)
        try:
            share.write(target, data)
        except Conflict as exc:
            if exc.code != "file_in_use":
                raise
            # Not another administrator: Windows clients keep the templates
            # they read open with a lease that denies writing, and hold it long
            # after the policy refresh that opened it. That also defeats the
            # remove-and-recreate fallback in the SMB layer, because the lease
            # denies the removal too. Saying so is the difference between a
            # message one can act on and one that sends the reader looking for
            # a colleague who is not there.
            raise Conflict(
                "A client has this template open and Windows will not let it be replaced.",
                code="file_in_use",
                hint=(
                    "A Windows client reading the central store holds it. "
                    "It lets go on its own after a while; closing the session "
                    "on the domain controller ends it immediately."
                ),
                detail=exc.detail,
                context={"name": relative, "path": target},
            ) from exc
        accepted.append(relative)

    forget(conn.info.dns_domain)
    logger.info(
        "added %d templates to the central store of %s",
        len(accepted),
        conn.info.dns_domain,
    )
    return {"path": base, "added": accepted}


def _safe_name(name: str) -> str | None:
    """Where a file goes inside the store, or nothing if it does not belong.

    Only two shapes are accepted: a bare ``.admx``, or a ``.adml`` one
    directory deep. Anything else — a path that climbs out, a nested tree, a
    file of another kind — is dropped rather than reshaped, because this
    writes onto a share every domain member reads.
    """
    cleaned = name.replace("\\", "/").strip().lstrip("/")
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None

    lowered = parts[-1].lower()
    if len(parts) == 1 and lowered.endswith(ADMX_SUFFIX):
        return parts[0]
    if len(parts) == 2 and lowered.endswith(ADML_SUFFIX):
        return "\\".join(parts)
    return None
