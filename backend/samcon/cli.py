"""samconctl — diagnostics for the container.

Runs inside the running container (`docker compose exec samcon samconctl ...`)
and answers the questions that come up when SAMCON cannot reach a domain:
which DCs are discovered, whether Kerberos works, whether LDAPS validates.

It is deliberately read-only. Nothing here changes the directory.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Any

from samcon import __version__


def _settings() -> Any:
    from samcon.config import get_settings

    return get_settings()


def cmd_config(args: argparse.Namespace) -> int:
    settings = _settings()
    data = settings.model_dump()
    # Nothing secret lives in the settings today; guard against that changing.
    for key in list(data):
        if "password" in key or "secret" in key:
            data[key] = "***"
    print(json.dumps(data, indent=2, default=str))
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    from samcon.ad.connection import discover_dcs
    from samcon.core.errors import SamconError

    settings = _settings()
    target = settings.default_target
    if target is None:
        print(
            "No default domain is configured (SAMCON_REALM is empty).\n"
            "Use `samconctl probe <address>` to inspect a specific server.",
            file=sys.stderr,
        )
        return 1

    try:
        hosts = discover_dcs(target)
    except SamconError as exc:
        print(f"FAILED: {exc.message}", file=sys.stderr)
        if exc.hint:
            print(f"  hint: {exc.hint}", file=sys.stderr)
        if exc.detail:
            print(f"  detail: {exc.detail}", file=sys.stderr)
        return 1

    source = "SAMCON_DC_HOSTS" if settings.dc_hosts else "DNS SRV records"
    print(f"realm  : {settings.realm}")
    print(f"source : {source}")
    for index, host in enumerate(hosts, start=1):
        print(f"  {index}. {host}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Identify the domain behind an address, without credentials."""
    from samcon.ad import discovery
    from samcon.core.errors import SamconError

    settings = _settings()
    try:
        identity = discovery.probe(
            args.server, settings, insecure=args.insecure, use_cache=False
        )
    except SamconError as exc:
        _report(exc)
        return 1

    print(json.dumps(identity.describe(), indent=2, default=str))

    if identity.ldaps_reachable and identity.ldaps_certificate_trusted is False:
        print(
            "\nNOTE: the LDAPS certificate does not validate against the configured CA.\n"
            "      Sign in with the certificate check disabled, or supply the CA file.",
            file=sys.stderr,
        )
    if identity.dc_hostname and identity.dc_hostname_resolves is False:
        print(
            f"\nWARNING: {identity.dc_hostname} does not resolve from this container.\n"
            "         Kerberos issues tickets for that name, so signing in will fail.\n"
            "         Use the DC as the container's DNS server, or add to compose:\n"
            f'             extra_hosts: ["{identity.dc_hostname}:{identity.host}"]',
            file=sys.stderr,
        )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Full path check: target resolution, ticket, LDAPS bind, rootDSE."""
    from dataclasses import asdict

    from samcon.ad import targets
    from samcon.ad.connection import connect
    from samcon.auth import kerberos
    from samcon.core.errors import SamconError

    settings = _settings()

    print("1/4 resolving the target domain ...", flush=True)
    try:
        target = targets.resolve_target(
            settings, server=args.server, realm=args.realm, insecure=args.insecure
        )
    except SamconError as exc:
        _report(exc)
        return 1
    print(f"    ok, realm {target.realm} via {', '.join(target.kdcs) or 'DNS'}")

    username = args.user or f"Administrator@{target.realm}"
    password = args.password or getpass.getpass(f"Password for {username}: ")
    principal = kerberos.parse_principal(username, target.realm)
    ccache = Path(settings.ccache_dir) / "samconctl-check"

    print(f"2/4 obtaining a ticket for {principal.full} ...", flush=True)
    try:
        kerberos.acquire_ticket(principal, password, ccache, settings, target)
    except SamconError as exc:
        _report(exc)
        return 1
    expiry = kerberos.ticket_expiry(ccache)
    print(f"    ok, expires {expiry.isoformat() if expiry else 'unknown'}")

    print("3/4 binding to the directory (LDAP+seal, then LDAPS) ...", flush=True)
    try:
        conn = connect(target, settings, ccache)
    except SamconError as exc:
        _report(exc)
        kerberos.destroy_ticket(ccache)
        return 1
    print(f"    ok, bound to {conn.info.dc_hostname} via {conn.host}")

    print("4/4 reading the rootDSE ...", flush=True)
    print(json.dumps(asdict(conn.info), indent=2, default=str))

    kerberos.destroy_ticket(ccache)
    print("\nall checks passed")
    return 0


def cmd_sysvol(args: argparse.Namespace) -> int:
    """Open the SYSVOL share and say which form of the call Samba accepted.

    Group policy is the only part of SAMCON that needs SMB as well as LDAP, and
    Samba's SMB client refuses some combinations of loadparm and credentials
    with one status that names neither. This tries them one at a time and
    reports each result, so a failure says which combination to change.
    """
    from samcon.ad import targets
    from samcon.ad.connection import connect
    from samcon.auth import kerberos
    from samcon.core.errors import SamconError
    from samcon.gpo import sysvol

    settings = _settings()

    try:
        target = targets.resolve_target(
            settings, server=args.server, realm=args.realm, insecure=args.insecure
        )
    except SamconError as exc:
        _report(exc)
        return 1

    username = args.user or f"Administrator@{target.realm}"
    password = args.password or getpass.getpass(f"Password for {username}: ")
    principal = kerberos.parse_principal(username, target.realm)
    ccache = Path(settings.ccache_dir) / "samconctl-sysvol"

    print(f"1/3 obtaining a ticket for {principal.full} ...", flush=True)
    try:
        kerberos.acquire_ticket(principal, password, ccache, settings, target)
    except SamconError as exc:
        _report(exc)
        return 1
    print("    ok")

    print("2/3 binding to the directory ...", flush=True)
    try:
        conn = connect(target, settings, ccache)
    except SamconError as exc:
        _report(exc)
        kerberos.destroy_ticket(ccache)
        return 1
    host = conn.info.dc_hostname or conn.host
    print(f"    ok, bound to {host}")

    print(f"3/3 opening \\\\{host}\\sysvol ...", flush=True)
    from samba.samba3 import libsmb_samba_internal as libsmb

    succeeded = None
    for label, build in sysvol._connection_variants(conn):
        try:
            lp, creds = build()
            client = libsmb.Conn(host, sysvol.SHARE, lp=lp, creds=creds)
        except Exception as exc:  # noqa: BLE001 — reporting every form is the point
            print(f"    {label}: {type(exc).__name__}: {exc}")
            continue

        print(f"    {label}: ok")
        if succeeded is None:
            succeeded = (label, client)

    if succeeded is None:
        print("\nno form of the SMB connection worked", file=sys.stderr)
        kerberos.destroy_ticket(ccache)
        return 1

    label, client = succeeded
    share = sysvol.SysvolConnection(client, host, conn.info.dns_domain)
    entries = share.listdir(conn.info.dns_domain)
    print(f"\nusing: {label}")
    print(f"contents of \\\\{host}\\sysvol\\{conn.info.dns_domain}:")
    for entry in entries:
        kind = "dir " if entry["is_directory"] else "file"
        print(f"  {kind}  {entry['name']}")

    kerberos.destroy_ticket(ccache)
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    settings = _settings()
    path = Path(settings.audit_file)
    if not path.exists():
        print(f"no audit log at {path}", file=sys.stderr)
        return 1

    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[-args.lines :]:
        if args.raw:
            print(line)
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            print(line)
            continue
        parts = [
            entry.get("ts", ""),
            entry.get("result", ""),
            entry.get("actor") or "-",
            entry.get("action", ""),
            entry.get("target") or "",
        ]
        print("  ".join(str(part) for part in parts))
    return 0


def _report(exc: Any) -> None:
    print(f"FAILED: {exc.message}", file=sys.stderr)
    if getattr(exc, "hint", None):
        print(f"  hint  : {exc.hint}", file=sys.stderr)
    if getattr(exc, "detail", None):
        print(f"  detail: {exc.detail}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="samconctl", description="SAMCON diagnostics")
    parser.add_argument("--version", action="version", version=f"SAMCON {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="show the effective configuration").set_defaults(
        func=cmd_config
    )
    sub.add_parser("discover", help="list the domain controllers SAMCON would use").set_defaults(
        func=cmd_discover
    )

    probe = sub.add_parser(
        "probe", help="identify the domain behind an address, without credentials"
    )
    probe.add_argument("server", help="IP address or host name of a domain controller")
    probe.add_argument(
        "--insecure",
        action="store_true",
        help="do not validate the LDAPS certificate while probing",
    )
    probe.set_defaults(func=cmd_probe)

    check = sub.add_parser("check", help="end-to-end check: Kerberos, LDAPS, rootDSE")
    check.add_argument("--server", help="IP address or host name; defaults to the configured realm")
    check.add_argument("--realm", help="Kerberos realm; discovered from the server when omitted")
    check.add_argument("--user", help="user@REALM to authenticate as")
    check.add_argument(
        "--password",
        help="password (omit to be prompted — safer, it stays out of the shell history)",
    )
    check.add_argument(
        "--insecure", action="store_true", help="do not validate the LDAPS certificate"
    )
    check.set_defaults(func=cmd_check)

    sysvol_cmd = sub.add_parser(
        "sysvol", help="open the SYSVOL share and report which SMB call form works"
    )
    sysvol_cmd.add_argument("--server", help="IP address or host name of a domain controller")
    sysvol_cmd.add_argument(
        "--realm", help="Kerberos realm; discovered from the server when omitted"
    )
    sysvol_cmd.add_argument("--user", help="user@REALM to authenticate as")
    sysvol_cmd.add_argument("--password", help="password (omit to be prompted)")
    sysvol_cmd.add_argument(
        "--insecure", action="store_true", help="do not validate the LDAPS certificate"
    )
    sysvol_cmd.set_defaults(func=cmd_sysvol)

    audit = sub.add_parser("audit", help="tail the audit log")
    audit.add_argument("-n", "--lines", type=int, default=20)
    audit.add_argument("--raw", action="store_true", help="print raw JSON lines")
    audit.set_defaults(func=cmd_audit)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
