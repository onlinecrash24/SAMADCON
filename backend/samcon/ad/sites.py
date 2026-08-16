"""Sites, subnets, site links and the servers in them.

All of this lives in the configuration partition, which is replicated across
the whole forest — a change here reaches every domain, not just the one the
administrator signed in to. That is why this module is deliberately narrow: it
edits the topology an administrator is expected to maintain (sites, subnets,
links, and which site a DC belongs to) and only reads the parts the KCC
generates for itself.

The layout under ``CN=Sites,CN=Configuration,…``::

    CN=<site>                       site
      CN=NTDS Site Settings         nTDSSiteSettings   (ISTG, options)
      CN=Servers                    serversContainer
        CN=<server>                 server             (dNSHostName)
          CN=NTDS Settings          nTDSDSA            (GC flag, NC list)
            CN=<guid>               nTDSConnection     (replication partner)
    CN=Subnets
      CN=192.168.1.0/24             subnet             (siteObject)
    CN=Inter-Site Transports
      CN=IP / CN=SMTP
        CN=<link>                   siteLink           (siteList, cost)
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

from samcon.ad import values
from samcon.ad.connection import SCOPE_ONELEVEL, SCOPE_SUBTREE, DirectoryConnection
from samcon.core.errors import Conflict, InvalidRequest, NotFound

logger = logging.getLogger(__name__)

# nTDSDSA options (MS-ADTS 6.1.1.2.2.1.2.1.1).
NTDSDSA_OPT_IS_GC = 0x00000001

# nTDSSiteSettings options: the two halves of "let the KCC do its work".
NTDSSETTINGS_OPT_IS_AUTO_TOPOLOGY_DISABLED = 0x00000001
NTDSSETTINGS_OPT_IS_INTER_SITE_AUTO_TOPOLOGY_DISABLED = 0x00000010

# nTDSConnection options.
NTDSCONN_OPT_IS_GENERATED = 0x00000001
NTDSCONN_OPT_USE_NOTIFY = 0x00000010

# siteLink options.
SITELINK_OPT_USE_NOTIFY = 0x00000001

# The transports a site link can use. SMTP is present in the schema but has
# been unusable for domain replication since Windows 2000; IP is the default
# everywhere and the only one RSAT offers for new links.
TRANSPORTS = ("IP", "SMTP")

SITE_ATTRS = ["distinguishedName", "name", "description", "location", "whenChanged"]
SUBNET_ATTRS = ["distinguishedName", "name", "description", "location", "siteObject"]
SERVER_ATTRS = ["distinguishedName", "name", "dNSHostName", "serverReference"]
LINK_ATTRS = [
    "distinguishedName",
    "name",
    "description",
    "cost",
    "replInterval",
    "options",
    "siteList",
]


# ---------------------------------------------------------------------------
# Where things live
# ---------------------------------------------------------------------------


def sites_dn(conn: DirectoryConnection) -> str:
    return f"CN=Sites,{conn.info.config_dn}"


def subnets_dn(conn: DirectoryConnection) -> str:
    return f"CN=Subnets,{sites_dn(conn)}"


def transports_dn(conn: DirectoryConnection) -> str:
    return f"CN=Inter-Site Transports,{sites_dn(conn)}"


def transport_dn(conn: DirectoryConnection, transport: str) -> str:
    name = transport.strip().upper()
    if name not in TRANSPORTS:
        raise InvalidRequest(
            f"Unknown transport '{transport}'.",
            code="unknown_transport",
            context={"supported": list(TRANSPORTS)},
        )
    return f"CN={name},{transports_dn(conn)}"


def servers_dn(site_dn: str) -> str:
    return f"CN=Servers,{site_dn}"


def site_of_server(server_dn: str) -> str | None:
    """The site a server object belongs to: two levels up from the server."""
    servers = values.parent_dn(server_dn)
    return values.parent_dn(servers) if servers else None


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------


def list_sites(conn: DirectoryConnection) -> list[dict[str, Any]]:
    """Every site, with how much is in it."""
    result = conn.search(
        sites_dn(conn), scope=SCOPE_ONELEVEL, expression="(objectClass=site)", attrs=SITE_ATTRS
    )

    subnets_by_site = _subnet_counts(conn)
    sites: list[dict[str, Any]] = []
    for entry in result:
        dn = values.as_str(entry, "distinguishedName") or str(entry.dn)
        sites.append(
            {
                **_site_summary(entry, dn),
                "server_count": _count(conn, servers_dn(dn), "(objectClass=server)"),
                "subnet_count": subnets_by_site.get(dn.lower(), 0),
            }
        )

    sites.sort(key=lambda site: site["name"].lower())
    return sites


def _site_summary(entry: Any, dn: str) -> dict[str, Any]:
    return {
        "dn": dn,
        "name": values.as_str(entry, "name") or values.name_from_dn(dn),
        "description": values.as_str(entry, "description"),
        "location": values.as_str(entry, "location"),
    }


def _count(conn: DirectoryConnection, base: str, expression: str) -> int:
    try:
        return len(conn.search(base, scope=SCOPE_ONELEVEL, expression=expression, attrs=["1.1"]))
    except Exception:
        # A site without a Servers container is unusual but not a reason to
        # fail the whole listing.
        logger.debug("cannot count %s under %s", expression, base, exc_info=True)
        return 0


def _subnet_counts(conn: DirectoryConnection) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        result = conn.search(
            subnets_dn(conn),
            scope=SCOPE_ONELEVEL,
            expression="(objectClass=subnet)",
            attrs=["siteObject"],
        )
    except Exception:
        logger.debug("no subnets container", exc_info=True)
        return counts

    for entry in result:
        site = values.as_str(entry, "siteObject")
        if site:
            counts[site.lower()] = counts.get(site.lower(), 0) + 1
    return counts


def get_site(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """One site with its servers, subnets and topology settings."""
    entry = conn.get(dn, attrs=SITE_ATTRS)
    if entry is None:
        raise NotFound("The site does not exist.", code="site_not_found", context={"dn": dn})

    detail = _site_summary(entry, values.as_str(entry, "distinguishedName") or dn)
    detail["when_changed"] = values.as_generalized_time(entry, "whenChanged")
    detail["servers"] = list_servers(conn, dn)
    detail["subnets"] = [
        subnet for subnet in list_subnets(conn) if (subnet["site_dn"] or "").lower() == dn.lower()
    ]
    detail["settings"] = _site_settings(conn, dn)
    return detail


def _site_settings(conn: DirectoryConnection, site_dn: str) -> dict[str, Any]:
    """NTDS Site Settings: who generates the topology, and whether it runs."""
    entry = conn.get(
        f"CN=NTDS Site Settings,{site_dn}",
        attrs=["options", "interSiteTopologyGenerator", "schedule"],
    )
    if entry is None:
        return {"present": False}

    options = values.as_int(entry, "options", 0) or 0
    istg = values.as_str(entry, "interSiteTopologyGenerator")
    return {
        "present": True,
        "options": options,
        # The ISTG attribute points at an NTDS Settings object; the server it
        # belongs to is what an administrator recognises.
        "topology_generator": values.name_from_dn(values.parent_dn(istg) or "") if istg else None,
        "auto_topology_disabled": bool(options & NTDSSETTINGS_OPT_IS_AUTO_TOPOLOGY_DISABLED),
        "inter_site_auto_topology_disabled": bool(
            options & NTDSSETTINGS_OPT_IS_INTER_SITE_AUTO_TOPOLOGY_DISABLED
        ),
    }


def create_site(conn: DirectoryConnection, name: str, *, description: str | None = None) -> dict:
    """Create a site, together with the two children it needs to work.

    A bare site object is not a working site: without ``NTDS Site Settings``
    the KCC has nowhere to record the topology generator, and without the
    ``Servers`` container a DC cannot be moved into it. ``samba-tool sites
    create`` builds the same three objects, in the same order.
    """
    import ldb

    site_name = _validate_site_name(name)
    dn = f"CN={values.escape_rdn_value(site_name)},{sites_dn(conn)}"
    if conn.exists(dn):
        raise Conflict(
            "A site with this name already exists.",
            code="site_exists",
            context={"site": site_name},
        )

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["objectClass"] = ldb.MessageElement(["top", "site"], ldb.FLAG_MOD_ADD, "objectClass")
    if description:
        message["description"] = ldb.MessageElement(description, ldb.FLAG_MOD_ADD, "description")
    conn.add(message)

    settings = ldb.Message()
    settings.dn = ldb.Dn(conn.samdb, f"CN=NTDS Site Settings,{dn}")
    settings["objectClass"] = ldb.MessageElement(
        ["top", "applicationSiteSettings", "nTDSSiteSettings"], ldb.FLAG_MOD_ADD, "objectClass"
    )
    conn.add(settings)

    servers = ldb.Message()
    servers.dn = ldb.Dn(conn.samdb, servers_dn(dn))
    servers["objectClass"] = ldb.MessageElement(
        ["top", "serversContainer"], ldb.FLAG_MOD_ADD, "objectClass"
    )
    conn.add(servers)

    return get_site(conn, dn)


def _validate_site_name(name: str) -> str:
    """Check a site name against what DNS can carry.

    Site names end up as labels in the ``_sites`` DNS records that clients use
    to find a nearby DC, so a name with a space or a slash produces a site no
    client can be pointed at. Windows enforces the same rule at creation time.
    """
    site_name = (name or "").strip()
    if not site_name:
        raise InvalidRequest("The name is missing.", code="missing_name")
    if len(site_name) > 63:
        raise InvalidRequest("The name is too long.", code="name_too_long", context={"max": 63})
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if set(site_name) - allowed:
        raise InvalidRequest(
            "A site name may contain only letters, digits, hyphens and underscores.",
            code="invalid_site_name",
            hint="The name is used as a DNS label in the _sites records.",
            context={"name": site_name},
        )
    return site_name


def update_site(
    conn: DirectoryConnection,
    dn: str,
    *,
    description: str | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    if not conn.exists(dn):
        raise NotFound("The site does not exist.", code="site_not_found", context={"dn": dn})
    return conn.modify_attributes(dn, {"description": description, "location": location})


def rename_site(conn: DirectoryConnection, dn: str, new_name: str) -> dict[str, Any]:
    site_name = _validate_site_name(new_name)
    target = f"CN={values.escape_rdn_value(site_name)},{sites_dn(conn)}"
    if target.lower() == dn.lower():
        return get_site(conn, dn)
    if conn.exists(target):
        raise Conflict(
            "A site with this name already exists.",
            code="site_exists",
            context={"site": site_name},
        )

    conn.rename(dn, target)
    return get_site(conn, target)


def delete_site(conn: DirectoryConnection, dn: str) -> None:
    """Delete a site. Refused while DCs are still in it.

    Deleting a site out from under a domain controller leaves it unreachable
    through the topology: its connections point at a site that no longer
    exists, and clients looking it up by site find nothing.
    """
    if not conn.exists(dn):
        raise NotFound("The site does not exist.", code="site_not_found", context={"dn": dn})

    servers = list_servers(conn, dn)
    if servers:
        raise Conflict(
            "The site still contains domain controllers.",
            code="site_not_empty",
            hint="Move the servers to another site first.",
            context={"servers": [server["name"] for server in servers]},
        )

    subnets = [s for s in list_subnets(conn) if (s["site_dn"] or "").lower() == dn.lower()]
    if subnets:
        raise Conflict(
            "The site is still assigned to subnets.",
            code="site_in_use",
            hint="Assign the subnets to another site first.",
            context={"subnets": [subnet["name"] for subnet in subnets]},
        )

    conn.delete(dn, recursive=True)


# ---------------------------------------------------------------------------
# Subnets
# ---------------------------------------------------------------------------


def normalise_subnet(name: str) -> str:
    """Check a subnet name and return it in the form AD stores.

    The name *is* the prefix — ``192.168.1.0/24`` — and it has to be the
    network address, not a host inside it. ``192.168.1.5/24`` would be accepted
    as an object name and then never match a client, which is the kind of
    mistake that is only found months later when someone wonders why logons go
    to the wrong site.
    """
    text = (name or "").strip()
    if not text:
        raise InvalidRequest("The subnet is missing.", code="missing_subnet")

    # Without one, Python would read a bare address as a single host — a subnet
    # that matches exactly one machine, which nobody means to type.
    if "/" not in text:
        raise InvalidRequest(
            "The subnet needs a prefix length.",
            code="invalid_subnet",
            hint="For example 192.168.1.0/24.",
            context={"value": text},
        )

    try:
        network = ipaddress.ip_network(text, strict=True)
    except ValueError as exc:
        message = str(exc)
        if "has host bits set" in message:
            try:
                corrected = ipaddress.ip_network(text, strict=False)
            except ValueError:
                corrected = None
            raise InvalidRequest(
                "The subnet must be given as a network address with a prefix length.",
                code="invalid_subnet",
                hint=f"Did you mean {corrected}?" if corrected else None,
                context={"value": text},
            ) from exc
        raise InvalidRequest(
            "Not a valid subnet.",
            code="invalid_subnet",
            hint="Expected something like 192.168.1.0/24 or 2001:db8::/64.",
            context={"value": text},
        ) from exc

    return str(network)


def list_subnets(conn: DirectoryConnection) -> list[dict[str, Any]]:
    try:
        result = conn.search(
            subnets_dn(conn),
            scope=SCOPE_ONELEVEL,
            expression="(objectClass=subnet)",
            attrs=SUBNET_ATTRS,
        )
    except NotFound:
        return []

    subnets = []
    for entry in result:
        site_dn = values.as_str(entry, "siteObject")
        subnets.append(
            {
                "dn": values.as_str(entry, "distinguishedName") or str(entry.dn),
                "name": values.as_str(entry, "name") or "",
                "description": values.as_str(entry, "description"),
                "location": values.as_str(entry, "location"),
                "site_dn": site_dn,
                "site": values.name_from_dn(site_dn) if site_dn else None,
            }
        )

    subnets.sort(key=_subnet_sort_key)
    return subnets


def _subnet_sort_key(subnet: dict[str, Any]) -> tuple[int, Any]:
    """Sort by address, so neighbouring networks end up next to each other.

    Text sorting would put 192.168.10.0/24 before 192.168.9.0/24.
    """
    try:
        network = ipaddress.ip_network(subnet["name"], strict=False)
    except ValueError:
        return (2, subnet["name"].lower())
    return (0 if network.version == 4 else 1, (int(network.network_address), network.prefixlen))


def create_subnet(
    conn: DirectoryConnection,
    name: str,
    *,
    site_dn: str | None = None,
    description: str | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    import ldb

    subnet = normalise_subnet(name)
    dn = f"CN={values.escape_rdn_value(subnet)},{subnets_dn(conn)}"
    if conn.exists(dn):
        raise Conflict(
            "This subnet already exists.", code="subnet_exists", context={"subnet": subnet}
        )
    if site_dn and not conn.exists(site_dn):
        raise NotFound("The site does not exist.", code="site_not_found", context={"dn": site_dn})

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["objectClass"] = ldb.MessageElement(["top", "subnet"], ldb.FLAG_MOD_ADD, "objectClass")
    if site_dn:
        message["siteObject"] = ldb.MessageElement(site_dn, ldb.FLAG_MOD_ADD, "siteObject")
    if description:
        message["description"] = ldb.MessageElement(description, ldb.FLAG_MOD_ADD, "description")
    if location:
        message["location"] = ldb.MessageElement(location, ldb.FLAG_MOD_ADD, "location")
    conn.add(message)

    return _one_subnet(conn, dn)


def update_subnet(
    conn: DirectoryConnection,
    dn: str,
    *,
    site_dn: str | None = None,
    description: str | None = None,
    location: str | None = None,
    clear_site: bool = False,
) -> dict[str, Any]:
    """Change a subnet's site or its labels.

    *clear_site* exists because "no site" is a real state — a subnet the
    administrator has entered but not yet assigned — and cannot be expressed by
    leaving *site_dn* out.
    """
    if not conn.exists(dn):
        raise NotFound("The subnet does not exist.", code="subnet_not_found", context={"dn": dn})
    if site_dn and not conn.exists(site_dn):
        raise NotFound("The site does not exist.", code="site_not_found", context={"dn": site_dn})

    changes: dict[str, Any] = {"description": description, "location": location}
    if clear_site:
        changes["siteObject"] = None
    elif site_dn:
        changes["siteObject"] = site_dn

    return conn.modify_attributes(dn, changes)


def delete_subnet(conn: DirectoryConnection, dn: str) -> None:
    if not conn.exists(dn):
        raise NotFound("The subnet does not exist.", code="subnet_not_found", context={"dn": dn})
    conn.delete(dn)


def _one_subnet(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    entry = conn.get(dn, attrs=SUBNET_ATTRS)
    if entry is None:
        raise NotFound("The subnet does not exist.", code="subnet_not_found", context={"dn": dn})
    site_dn = values.as_str(entry, "siteObject")
    return {
        "dn": values.as_str(entry, "distinguishedName") or dn,
        "name": values.as_str(entry, "name") or "",
        "description": values.as_str(entry, "description"),
        "location": values.as_str(entry, "location"),
        "site_dn": site_dn,
        "site": values.name_from_dn(site_dn) if site_dn else None,
    }


# ---------------------------------------------------------------------------
# Servers and their replication connections
# ---------------------------------------------------------------------------


def list_servers(conn: DirectoryConnection, site_dn: str) -> list[dict[str, Any]]:
    """The domain controllers registered in a site."""
    try:
        result = conn.search(
            servers_dn(site_dn),
            scope=SCOPE_ONELEVEL,
            expression="(objectClass=server)",
            attrs=SERVER_ATTRS,
        )
    except NotFound:
        return []

    servers = []
    for entry in result:
        dn = values.as_str(entry, "distinguishedName") or str(entry.dn)
        servers.append({**_server_summary(entry, dn), **_ntds_summary(conn, dn)})

    servers.sort(key=lambda server: server["name"].lower())
    return servers


def _server_summary(entry: Any, dn: str) -> dict[str, Any]:
    return {
        "dn": dn,
        "name": values.as_str(entry, "name") or values.name_from_dn(dn),
        "dns_name": values.as_str(entry, "dNSHostName"),
        "computer_dn": values.as_str(entry, "serverReference"),
    }


def _ntds_summary(conn: DirectoryConnection, server_dn: str) -> dict[str, Any]:
    """What the NTDS Settings object says about a server.

    Its absence is meaningful rather than an error: a server object without one
    is not a domain controller — it is a member server someone registered here,
    or the leftovers of a demoted DC.
    """
    ntds_dn = f"CN=NTDS Settings,{server_dn}"
    entry = conn.get(
        ntds_dn,
        attrs=["distinguishedName", "options", "msDS-Behavior-Version", "objectGUID"],
    )
    if entry is None:
        return {"is_dc": False, "is_global_catalog": False, "ntds_dn": None}

    options = values.as_int(entry, "options", 0) or 0
    return {
        "is_dc": True,
        "ntds_dn": values.as_str(entry, "distinguishedName") or ntds_dn,
        "is_global_catalog": bool(options & NTDSDSA_OPT_IS_GC),
        "functional_level": values.as_int(entry, "msDS-Behavior-Version"),
        "guid": values.guid_to_str(values.as_bytes(entry, "objectGUID")),
    }


def move_server(conn: DirectoryConnection, server_dn: str, target_site_dn: str) -> dict[str, Any]:
    """Move a domain controller into another site.

    The site membership of a DC *is* the position of its server object in the
    tree; there is no attribute to set. Clients pick their DC by site, so this
    changes who they talk to.
    """
    entry = conn.get(server_dn, attrs=SERVER_ATTRS)
    if entry is None:
        raise NotFound(
            "The server does not exist.", code="server_not_found", context={"dn": server_dn}
        )
    if not conn.exists(target_site_dn):
        raise NotFound(
            "The site does not exist.", code="site_not_found", context={"dn": target_site_dn}
        )

    target_servers = servers_dn(target_site_dn)
    if not conn.exists(target_servers):
        raise InvalidRequest(
            "The target site has no Servers container.",
            code="site_incomplete",
            hint="It was created without one; a site made here always has it.",
            context={"dn": target_servers},
        )

    name = values.rdn_of(server_dn)
    target_dn = f"{name},{target_servers}"
    if target_dn.lower() == server_dn.lower():
        return _server_summary(entry, server_dn)
    if conn.exists(target_dn):
        raise Conflict(
            "A server with this name already exists in the target site.",
            code="server_exists",
            context={"dn": target_dn},
        )

    conn.rename(server_dn, target_dn)
    moved = conn.get(target_dn, attrs=SERVER_ATTRS)
    return {**_server_summary(moved, target_dn), **_ntds_summary(conn, target_dn)}


def list_connections(conn: DirectoryConnection, server_dn: str) -> list[dict[str, Any]]:
    """Replication connections into a server.

    Read-only on purpose. Most of these are the KCC's own work — it recreates
    what it needs and removes what it does not, so editing them by hand is
    undone at the next run. Seeing them is what matters for diagnosis.
    """
    try:
        result = conn.search(
            f"CN=NTDS Settings,{server_dn}",
            scope=SCOPE_ONELEVEL,
            expression="(objectClass=nTDSConnection)",
            attrs=["distinguishedName", "name", "fromServer", "options", "enabledConnection"],
        )
    except NotFound:
        return []

    connections = []
    for entry in result:
        from_server = values.as_str(entry, "fromServer")
        # fromServer points at NTDS Settings; the server above it is the name
        # an administrator knows.
        source_dn = values.parent_dn(from_server) if from_server else None
        options = values.as_int(entry, "options", 0) or 0
        connections.append(
            {
                "dn": values.as_str(entry, "distinguishedName") or str(entry.dn),
                "name": values.as_str(entry, "name") or "",
                "from_server": values.name_from_dn(source_dn) if source_dn else None,
                "from_site": values.name_from_dn(site_of_server(source_dn) or "")
                if source_dn
                else None,
                "generated": bool(options & NTDSCONN_OPT_IS_GENERATED),
                "notify": bool(options & NTDSCONN_OPT_USE_NOTIFY),
                "enabled": values.as_bool(entry, "enabledConnection", True),
            }
        )

    connections.sort(key=lambda item: (item["from_site"] or "", item["from_server"] or ""))
    return connections


def find_server(conn: DirectoryConnection, name: str) -> dict[str, Any]:
    """Locate a server object by name across all sites."""
    result = conn.search(
        sites_dn(conn),
        scope=SCOPE_SUBTREE,
        expression=f"(&(objectClass=server)(name={values.escape_filter(name)}))",
        attrs=SERVER_ATTRS,
    )
    if not result.entries:
        raise NotFound(
            "The server does not exist.", code="server_not_found", context={"name": name}
        )

    entry = result.entries[0]
    dn = values.as_str(entry, "distinguishedName") or str(entry.dn)
    site_dn = site_of_server(dn)
    return {
        **_server_summary(entry, dn),
        **_ntds_summary(conn, dn),
        "site_dn": site_dn,
        "site": values.name_from_dn(site_dn) if site_dn else None,
    }


# ---------------------------------------------------------------------------
# Site links
# ---------------------------------------------------------------------------


def list_site_links(conn: DirectoryConnection) -> list[dict[str, Any]]:
    """Site links across both transports."""
    links: list[dict[str, Any]] = []
    site_names = {site["dn"].lower(): site["name"] for site in list_sites(conn)}

    for transport in TRANSPORTS:
        try:
            result = conn.search(
                transport_dn(conn, transport),
                scope=SCOPE_ONELEVEL,
                expression="(objectClass=siteLink)",
                attrs=LINK_ATTRS,
            )
        except NotFound:
            continue

        for entry in result:
            links.append(_link_summary(entry, transport, site_names))

    links.sort(key=lambda link: (link["transport"], link["name"].lower()))
    return links


def _link_summary(entry: Any, transport: str, site_names: dict[str, str]) -> dict[str, Any]:
    dn = values.as_str(entry, "distinguishedName") or str(entry.dn)
    members = values.as_list(entry, "siteList")
    options = values.as_int(entry, "options", 0) or 0
    return {
        "dn": dn,
        "name": values.as_str(entry, "name") or values.name_from_dn(dn),
        "description": values.as_str(entry, "description"),
        "transport": transport,
        "cost": values.as_int(entry, "cost", 100),
        # In minutes, as both RSAT and the schema count it.
        "replication_interval": values.as_int(entry, "replInterval", 180),
        "notify": bool(options & SITELINK_OPT_USE_NOTIFY),
        "site_dns": members,
        "sites": [
            site_names.get(member.lower(), values.name_from_dn(member)) for member in members
        ],
    }


def get_site_link(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    entry = conn.get(dn, attrs=LINK_ATTRS)
    if entry is None:
        raise NotFound("The site link does not exist.", code="link_not_found", context={"dn": dn})
    site_names = {site["dn"].lower(): site["name"] for site in list_sites(conn)}
    return _link_summary(entry, _transport_of(dn), site_names)


def _transport_of(link_dn: str) -> str:
    """Which transport container a link sits in."""
    parent = values.parent_dn(link_dn) or ""
    name = values.name_from_dn(parent).upper()
    return name if name in TRANSPORTS else "IP"


def create_site_link(
    conn: DirectoryConnection,
    name: str,
    *,
    site_dns: list[str],
    transport: str = "IP",
    cost: int = 100,
    replication_interval: int = 180,
    description: str | None = None,
) -> dict[str, Any]:
    """Create a site link between two or more sites."""
    import ldb

    link_name = (name or "").strip()
    if not link_name:
        raise InvalidRequest("The name is missing.", code="missing_name")

    members = _validate_members(conn, site_dns)
    _validate_cost(cost)
    _validate_interval(replication_interval)

    container = transport_dn(conn, transport)
    dn = f"CN={values.escape_rdn_value(link_name)},{container}"
    if conn.exists(dn):
        raise Conflict(
            "A site link with this name already exists.",
            code="link_exists",
            context={"link": link_name},
        )

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["objectClass"] = ldb.MessageElement(
        ["top", "siteLink"], ldb.FLAG_MOD_ADD, "objectClass"
    )
    message["siteList"] = ldb.MessageElement(members, ldb.FLAG_MOD_ADD, "siteList")
    message["cost"] = ldb.MessageElement(str(cost), ldb.FLAG_MOD_ADD, "cost")
    message["replInterval"] = ldb.MessageElement(
        str(replication_interval), ldb.FLAG_MOD_ADD, "replInterval"
    )
    if description:
        message["description"] = ldb.MessageElement(description, ldb.FLAG_MOD_ADD, "description")
    conn.add(message)

    return get_site_link(conn, dn)


def update_site_link(
    conn: DirectoryConnection,
    dn: str,
    *,
    site_dns: list[str] | None = None,
    cost: int | None = None,
    replication_interval: int | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    if not conn.exists(dn):
        raise NotFound("The site link does not exist.", code="link_not_found", context={"dn": dn})

    changes: dict[str, Any] = {"description": description}
    if site_dns is not None:
        changes["siteList"] = _validate_members(conn, site_dns)
    if cost is not None:
        _validate_cost(cost)
        changes["cost"] = str(cost)
    if replication_interval is not None:
        _validate_interval(replication_interval)
        changes["replInterval"] = str(replication_interval)

    return conn.modify_attributes(dn, changes)


def delete_site_link(conn: DirectoryConnection, dn: str) -> None:
    if not conn.exists(dn):
        raise NotFound("The site link does not exist.", code="link_not_found", context={"dn": dn})
    conn.delete(dn)


def _validate_members(conn: DirectoryConnection, site_dns: list[str]) -> list[str]:
    """A link needs at least two distinct, existing sites.

    A link with one site is silently ignored by the KCC — it describes no
    path — so it is better refused than accepted and wondered about later.
    """
    seen: list[str] = []
    for dn in site_dns or []:
        if any(dn.lower() == existing.lower() for existing in seen):
            continue
        if not conn.exists(dn):
            raise NotFound("The site does not exist.", code="site_not_found", context={"dn": dn})
        seen.append(dn)

    if len(seen) < 2:
        raise InvalidRequest(
            "A site link has to connect at least two sites.",
            code="too_few_sites",
            context={"given": len(seen)},
        )
    return seen


def _validate_cost(cost: int) -> None:
    # The schema's range; RSAT offers the same one.
    if cost < 1 or cost > 32767:
        raise InvalidRequest(
            "The cost must be between 1 and 32767.",
            code="invalid_cost",
            context={"value": cost},
        )


def _validate_interval(minutes: int) -> None:
    """Replication interval, in minutes.

    Below 15 the DC rounds up to 15 anyway, so a smaller number is not a
    setting but a misunderstanding.
    """
    if minutes < 15 or minutes > 10080:
        raise InvalidRequest(
            "The replication interval must be between 15 minutes and 7 days (10080 minutes).",
            code="invalid_interval",
            context={"value": minutes},
        )


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def topology(conn: DirectoryConnection) -> dict[str, Any]:
    """Everything the Sites console shows at once.

    One call rather than four: the four lists reference each other by DN, and
    fetching them separately means the front end has to stitch them back
    together from possibly inconsistent snapshots.
    """
    sites = list_sites(conn)
    for site in sites:
        site["servers"] = list_servers(conn, site["dn"])

    return {
        "sites": sites,
        "subnets": list_subnets(conn),
        "links": list_site_links(conn),
        "sites_dn": sites_dn(conn),
    }


def server_count(conn: DirectoryConnection) -> int:
    """How many domain controllers the forest has, across all sites."""
    result = conn.search(
        sites_dn(conn),
        scope=SCOPE_SUBTREE,
        expression="(objectClass=nTDSDSA)",
        attrs=["1.1"],
    )
    return len(result)
