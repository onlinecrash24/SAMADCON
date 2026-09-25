"""Template packages as administrators actually have them.

Microsoft ships its administrative templates as an MSI. Installed on Windows
it lands in ``...\\Microsoft Group Policy\\<release>\\PolicyDefinitions``, and
an administrator who zips that folder — or picks it in a browser — hands over
``PolicyDefinitions/x.admx`` and ``PolicyDefinitions/de-de/x.adml``.

The central store takes exactly two shapes, ``x.admx`` and ``<lang>/x.adml``,
and :func:`samadcon.gpo.admx.store._safe_name` drops everything else rather
than reshape it, because it writes onto a share every domain member reads.
That gate stays as strict as it is. The reshaping happens here, once, by one
rule: find the single directory that holds the ``.admx`` files, and express
every path relative to it. What does not fit that rule is counted and left
out, not guessed at.

Measured against the Windows 11 25H2 package (v2.0): 5284 files, 233
templates, 22 language directories, 97 MB unpacked — of which one language
is about 3.7 MB. That is why the languages are chosen rather than taken
whole: SYSVOL is replicated to every domain controller.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from samadcon.core.errors import InvalidRequest

TEMPLATE_SUFFIXES = (".admx", ".adml")

# Well above a full Microsoft package with every language (97 MB), well below
# what would hurt: this is read into memory before anything is written.
MAX_UNPACKED_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 20_000

# msiextract takes about two seconds for the Windows 11 package.
MSI_TIMEOUT_SECONDS = 120

_ZIP_MAGIC = b"PK\x03\x04"
# An MSI is an OLE compound file.
_MSI_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


@dataclass
class Package:
    """What an upload amounts to, in the shape the store takes."""

    files: dict[str, bytes] = field(default_factory=dict)
    #: Every language directory the package carried, spelled as Windows does.
    languages: list[str] = field(default_factory=list)
    #: The ones that went into :attr:`files`.
    imported_languages: list[str] = field(default_factory=list)
    #: Asked for, and not in the package.
    missing_languages: list[str] = field(default_factory=list)
    #: Members that were not templates, or not where templates belong.
    ignored: int = 0


def canonical_language(name: str) -> str:
    """``de-de`` → ``de-DE``: how Windows names the directory locally.

    Microsoft's MSI writes every directory but ``en-US`` in lower case. The
    store reads either, but an administrator looking at SYSVOL expects the
    spelling Windows uses, and so does every guide that tells them where to
    look. Anything not shaped like language-region is left as it is.
    """
    parts = name.split("-")
    if (
        len(parts) == 2
        and parts[0].isalpha()
        and 2 <= len(parts[0]) <= 3
        and parts[1].isalpha()
        and len(parts[1]) == 2
    ):
        return f"{parts[0].lower()}-{parts[1].upper()}"
    return name


def _parts(name: str) -> tuple[str, ...] | None:
    """A member name as path components, or nothing if it is not a safe one."""
    cleaned = name.replace("\\", "/").strip()
    if cleaned.startswith("/"):
        return None
    parts = tuple(part for part in cleaned.split("/") if part not in ("", "."))
    if not parts or any(part == ".." or ":" in part for part in parts):
        return None
    return parts


def reshape(members: dict[str, bytes], languages: Iterable[str] | None = None) -> Package:
    """Express a package relative to the directory that holds its templates.

    ``languages`` limits which ``.adml`` directories are taken; ``None`` takes
    all of them. The ``.admx`` files always come along — without them the
    text files describe nothing.
    """
    # Read once: an iterable handed in may be a generator, and it is needed twice.
    requested = None if languages is None else [canonical_language(item) for item in languages]
    wanted = None if requested is None else {item.lower() for item in requested}

    found: dict[tuple[str, ...], bytes] = {}
    ignored = 0
    for name, data in members.items():
        parts = _parts(name)
        if parts is None or not parts[-1].lower().endswith(TEMPLATE_SUFFIXES):
            ignored += 1
            continue
        found[parts] = data

    admx_homes = {parts[:-1] for parts in found if parts[-1].lower().endswith(".admx")}
    if len(admx_homes) > 1:
        raise InvalidRequest(
            "This package holds templates in more than one folder.",
            code="ambiguous_package",
            hint="Upload one PolicyDefinitions folder at a time.",
            context={"folders": sorted("/".join(home) or "." for home in admx_homes)[:5]},
        )

    if admx_homes:
        root = admx_homes.pop()
    else:
        # Text files alone: a language added to templates already installed.
        text_homes = {
            parts[:-2]
            for parts in found
            if parts[-1].lower().endswith(".adml") and len(parts) >= 2
        }
        if len(text_homes) != 1:
            raise InvalidRequest(
                "None of these files is an administrative template.",
                code="no_templates",
                hint="Expected .admx files, and .adml files in language folders beside them.",
            )
        root = text_homes.pop()

    package = Package(ignored=ignored)
    seen: set[str] = set()
    taken: set[str] = set()
    for parts, data in sorted(found.items()):
        if parts[: len(root)] != root:
            package.ignored += 1
            continue
        rest = parts[len(root) :]
        if len(rest) == 1 and rest[0].lower().endswith(".admx"):
            package.files[rest[0]] = data
        elif len(rest) == 2 and rest[1].lower().endswith(".adml"):
            language = canonical_language(rest[0])
            seen.add(language)
            if wanted is None or language.lower() in wanted:
                package.files[f"{language}/{rest[1]}"] = data
                taken.add(language)
        else:
            package.ignored += 1

    package.languages = sorted(seen)
    package.imported_languages = sorted(taken)
    if requested is not None:
        present = {item.lower() for item in seen}
        package.missing_languages = sorted(
            {item for item in requested if item.lower() not in present}
        )
    return package


def unpack_zip(data: bytes) -> dict[str, bytes]:
    """The template members of a ZIP, bounded before a byte is inflated."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise InvalidRequest(
            "This file is not a template package.", code="invalid_package"
        ) from exc

    members = [
        info
        for info in archive.infolist()
        if not info.is_dir() and info.filename.lower().endswith(TEMPLATE_SUFFIXES)
    ]
    _check_bounds(len(members), sum(info.file_size for info in members))
    # file_size is what the archive claims; zipfile stops reading a member at
    # that size and checks its CRC, so a member cannot inflate past it.
    return {info.filename: archive.read(info) for info in members}


def unpack_msi(data: bytes) -> dict[str, bytes]:
    """The templates inside one of Microsoft's MSI packages.

    ``msiextract`` from msitools resolves the MSI's own tables, so files come
    out under their real names and directories — 7-Zip shows only the keys the
    cabinet stores them under (``staging_de_de_Search.adml``). The cabinet in
    Microsoft's packages is MSZIP, which libgcab reads.
    """
    tool = shutil.which("msiextract")
    if tool is None:
        raise InvalidRequest(
            "This installation cannot open MSI packages.",
            code="msi_unsupported",
            hint=(
                "The image needs msiextract (Debian package msitools). Until then, "
                "install the MSI on Windows and upload its PolicyDefinitions folder."
            ),
        )

    with tempfile.TemporaryDirectory(prefix="samadcon-msi-") as work:
        source = Path(work) / "package.msi"
        source.write_bytes(data)
        target = Path(work) / "out"
        target.mkdir()
        try:
            subprocess.run(
                [tool, "-C", str(target), str(source)],
                check=True,
                capture_output=True,
                timeout=MSI_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise InvalidRequest(
                "Unpacking this MSI took too long.", code="invalid_package"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise InvalidRequest(
                "This MSI could not be unpacked.",
                code="invalid_package",
                detail=(exc.stderr or b"").decode("utf-8", "replace")[:500],
            ) from exc

        paths = [
            path
            for path in target.rglob("*")
            if path.is_file() and path.name.lower().endswith(TEMPLATE_SUFFIXES)
        ]
        _check_bounds(len(paths), sum(path.stat().st_size for path in paths))
        return {path.relative_to(target).as_posix(): path.read_bytes() for path in paths}


def _check_bounds(count: int, size: int) -> None:
    if count > MAX_MEMBERS or size > MAX_UNPACKED_BYTES:
        raise InvalidRequest(
            "This package is larger than a template package can be.",
            code="upload_too_large",
            context={"files": count, "bytes": size, "limit_bytes": MAX_UNPACKED_BYTES},
        )


def open_package(
    uploads: Iterable[tuple[str, bytes]], languages: Iterable[str] | None = None
) -> Package:
    """Everything an upload carried, reshaped for the store.

    Each upload is an MSI, a ZIP or a single template; a browser's folder
    upload arrives as many single templates whose names carry the path. They
    are recognised by their first bytes rather than their names, because a
    name is whatever the browser chose to send.
    """
    members: dict[str, bytes] = {}
    for name, data in uploads:
        if data.startswith(_MSI_MAGIC):
            members.update(unpack_msi(data))
        elif data.startswith(_ZIP_MAGIC):
            members.update(unpack_zip(data))
        else:
            members[name] = data
    return reshape(members, languages)
