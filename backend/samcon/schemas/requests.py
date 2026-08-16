"""Request bodies for the v1 API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    # Reject unknown fields: a typo in a field name must not be swallowed and
    # then silently do nothing.
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(StrictModel):
    username: str = Field(
        min_length=1, max_length=256, description="user, user@REALM or DOMAIN\\user"
    )
    password: str = Field(min_length=1, max_length=512)

    # Which domain to sign in to. All optional: with none of them set, the
    # container's configured default is used.
    server: str | None = Field(
        default=None,
        max_length=253,
        description="Address of a domain controller — IP or host name",
    )
    realm: str | None = Field(
        default=None,
        max_length=253,
        description="Kerberos realm; discovered from the server when omitted",
    )
    profile_id: str | None = Field(
        default=None, max_length=64, description="Id of a configured server profile"
    )
    insecure: bool = Field(
        default=False,
        description=(
            "Skip LDAPS certificate validation for this session. The connection "
            "stays encrypted; only the server's identity goes unverified."
        ),
    )


class ProbeRequest(StrictModel):
    """Ask a server which domain it belongs to, before signing in."""

    host: str | None = Field(default=None, max_length=253)
    profile_id: str | None = Field(default=None, max_length=64)
    insecure: bool = False


# ---------------------------------------------------------------------------
# Generic directory operations
# ---------------------------------------------------------------------------


class MoveRequest(StrictModel):
    target_dn: str = Field(min_length=3, description="DN of the destination container")


class RenameRequest(StrictModel):
    name: str = Field(min_length=1, max_length=256)


class AttributeUpdateRequest(StrictModel):
    """Raw attribute editor. Values are replaced; null deletes the attribute."""

    attributes: dict[str, Any]


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class CreateUserRequest(StrictModel):
    parent_dn: str = Field(min_length=3)
    sam_account_name: str = Field(min_length=1, max_length=20)
    common_name: str | None = Field(default=None, max_length=64)
    password: str | None = Field(default=None, max_length=512)
    must_change_password: bool = False
    enabled: bool = True
    attributes: dict[str, Any] = Field(default_factory=dict)
    flags: dict[str, bool] = Field(default_factory=dict)


class UpdateUserRequest(StrictModel):
    attributes: dict[str, Any] | None = None
    flags: dict[str, bool] | None = None


class SetPasswordRequest(StrictModel):
    password: str = Field(min_length=1, max_length=512)
    must_change: bool = False


class MustChangePasswordRequest(StrictModel):
    must_change: bool


class AccountExpiryRequest(StrictModel):
    expires_at: datetime | None = Field(
        default=None, description="null clears the expiry date"
    )


class EnabledRequest(StrictModel):
    enabled: bool


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


class CreateGroupRequest(StrictModel):
    parent_dn: str = Field(min_length=3)
    name: str = Field(min_length=1, max_length=64)
    sam_account_name: str | None = Field(default=None, max_length=64)
    scope: str = Field(default="global", pattern="^(global|domain_local|universal)$")
    security: bool = True
    description: str | None = None


class UpdateGroupRequest(StrictModel):
    attributes: dict[str, Any] | None = None
    scope: str | None = Field(default=None, pattern="^(global|domain_local|universal)$")
    security: bool | None = None


class MembersRequest(StrictModel):
    members: list[str] = Field(min_length=1, description="DNs to add or remove")


# ---------------------------------------------------------------------------
# Computers
# ---------------------------------------------------------------------------


class CreateComputerRequest(StrictModel):
    parent_dn: str = Field(min_length=3)
    name: str = Field(min_length=1, max_length=15)
    description: str | None = None
    location: str | None = None
    enabled: bool = True


class UpdateComputerRequest(StrictModel):
    attributes: dict[str, Any] | None = None
    flags: dict[str, bool] | None = None


# ---------------------------------------------------------------------------
# Organizational units
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------


class DnsRecordBase(StrictModel):
    zone: str = Field(min_length=1, max_length=253, description="Zone name, e.g. example.lan")
    name: str = Field(
        min_length=1,
        max_length=253,
        description="Record name; relative to the zone or fully qualified, '@' for the zone itself",
    )
    type: str = Field(
        min_length=1, max_length=10, description="A, AAAA, CNAME, NS, PTR, MX, SRV or TXT"
    )


class CreateDnsRecordRequest(DnsRecordBase):
    # Type-specific; validated against the record type in samcon.ad.dnsrecords.
    data: dict[str, Any]
    ttl: int | None = Field(default=None, ge=0, le=2147483647)


class UpdateDnsRecordRequest(DnsRecordBase):
    """A node holds several records without identifiers, so the values it
    currently has are what identifies the one to replace."""

    old_data: dict[str, Any]
    data: dict[str, Any]
    ttl: int | None = Field(default=None, ge=0, le=2147483647)


class DeleteDnsRecordRequest(DnsRecordBase):
    data: dict[str, Any]


class CreateDnsZoneRequest(StrictModel):
    name: str = Field(min_length=1, max_length=253)
    partition: str = Field(default="domain", pattern="^(domain|forest|legacy)$")


# ---------------------------------------------------------------------------
# Sites and services
# ---------------------------------------------------------------------------


class CreateSiteRequest(StrictModel):
    name: str = Field(min_length=1, max_length=63)
    description: str | None = Field(default=None, max_length=1024)


class UpdateSiteRequest(StrictModel):
    description: str | None = Field(default=None, max_length=1024)
    location: str | None = Field(default=None, max_length=1024)


class RenameSiteRequest(StrictModel):
    name: str = Field(min_length=1, max_length=63)


class CreateSubnetRequest(StrictModel):
    # Validated as a network prefix in samcon.ad.sites; a pattern here would
    # only duplicate that check badly.
    name: str = Field(min_length=4, max_length=64, description="e.g. 192.168.1.0/24")
    site_dn: str | None = Field(default=None, max_length=1024)
    description: str | None = Field(default=None, max_length=1024)
    location: str | None = Field(default=None, max_length=1024)


class UpdateSubnetRequest(StrictModel):
    site_dn: str | None = Field(default=None, max_length=1024)
    description: str | None = Field(default=None, max_length=1024)
    location: str | None = Field(default=None, max_length=1024)
    clear_site: bool = Field(
        default=False, description="Detach the subnet from its site; site_dn cannot express this"
    )


class MoveServerRequest(StrictModel):
    site_dn: str = Field(min_length=3, max_length=1024)


class SiteLinkBase(StrictModel):
    cost: int | None = Field(default=None, ge=1, le=32767)
    replication_interval: int | None = Field(
        default=None, ge=15, le=10080, description="Minutes between replication attempts"
    )
    description: str | None = Field(default=None, max_length=1024)


class CreateSiteLinkRequest(SiteLinkBase):
    name: str = Field(min_length=1, max_length=64)
    site_dns: list[str] = Field(min_length=2, description="At least two sites")
    transport: str = Field(default="IP", pattern="^(IP|SMTP)$")


class UpdateSiteLinkRequest(SiteLinkBase):
    site_dns: list[str] | None = Field(default=None, min_length=2)


# ---------------------------------------------------------------------------
# Group policy
# ---------------------------------------------------------------------------


class CreateGpoRequest(StrictModel):
    display_name: str = Field(min_length=1, max_length=255)


class UpdateGpoRequest(StrictModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    machine_enabled: bool | None = Field(
        default=None, description="Whether clients read the computer half at all"
    )
    user_enabled: bool | None = None


class AddGpoLinkRequest(StrictModel):
    gpo_dn: str = Field(min_length=3, max_length=1024)
    enabled: bool = True
    enforced: bool = Field(
        default=False, description="Survives a block on inheritance further down"
    )


class UpdateGpoLinkRequest(StrictModel):
    gpo_dn: str = Field(min_length=3, max_length=1024)
    enabled: bool | None = None
    enforced: bool | None = None
    order: int | None = Field(
        default=None, ge=1, description="Link order as GPMC counts it; 1 takes precedence"
    )


class RemoveGpoLinkRequest(StrictModel):
    gpo_dn: str = Field(min_length=3, max_length=1024)


class BlockInheritanceRequest(StrictModel):
    block: bool


class CopyGpoRequest(StrictModel):
    display_name: str = Field(min_length=1, max_length=255)


class ApplyPolicyRequest(StrictModel):
    policy: str = Field(min_length=1, max_length=512, description="The policy's namespaced id")
    half: str = Field(pattern="^(Machine|User)$")
    state: str = Field(pattern="^(not_configured|enabled|disabled)$")
    # Keyed by element id; validated against the template in samcon.gpo.admx.
    values: dict[str, Any] = Field(default_factory=dict)
    expected_version: int | None = Field(
        default=None,
        ge=0,
        description="The versionNumber the form was filled in from; a mismatch is refused",
    )


class ScriptEntry(StrictModel):
    """One command and its arguments, as one numbered pair in the file."""

    command: str = Field(min_length=1, max_length=1024)
    parameters: str = Field(default="", max_length=4096)


class SetScriptsRequest(StrictModel):
    """The complete list for one event and one engine.

    Not one entry at a time: the numbering in the file is the execution order
    and has to run 0, 1, 2 without gaps, so reordering and removing are the
    same operation as adding — send the list as it should end up.
    """

    half: str = Field(pattern="^(Machine|User)$")
    event: str = Field(pattern="^(Startup|Shutdown|Logon|Logoff)$")
    engine: str = Field(default="cmd", pattern="^(cmd|powershell)$")
    scripts: list[ScriptEntry] = Field(default_factory=list, max_length=64)
    ps_first: bool | None = Field(
        default=None,
        description="Whether PowerShell scripts run before the others; null leaves it unsaid",
    )
    expected_version: int | None = Field(
        default=None,
        ge=0,
        description="The versionNumber the form was filled in from; a mismatch is refused",
    )


class SetVgpEntriesRequest(StrictModel):
    """The complete list for one Samba policy.

    Not one entry at a time: a manifest holds the whole list, and Samba
    applies what is in it. Sending the list as it should end up makes
    reordering and removing the same operation as adding.
    """

    policy: str = Field(min_length=1, max_length=32, pattern=r"^[a-z_]+$")
    entries: list[dict[str, Any]] = Field(default_factory=list, max_length=256)
    expected_version: int | None = Field(
        default=None,
        ge=0,
        description="The versionNumber the form was filled in from; a mismatch is refused",
    )


class SetPreferenceItemsRequest(StrictModel):
    """The complete list for one preference type of one half.

    The whole list rather than one item, for the same reason as the Samba
    policies: the file holds all of them, so reordering, removing and adding
    are one operation.

    What is *not* here is as deliberate: an item carries no filters and no
    unmodelled attributes on the way in. Those are read from the file that is
    already on SYSVOL and carried over by ``uid``, so a rename cannot quietly
    drop the item-level targeting that decides who a drive is mapped for.
    """

    type: str = Field(min_length=1, max_length=32, pattern=r"^[a-z_]+$")
    half: Literal["Machine", "User"]
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=256)
    expected_version: int | None = Field(
        default=None,
        ge=0,
        description="The versionNumber the form was filled in from; a mismatch is refused",
    )


class SetRestrictedGroupRequest(StrictModel):
    """Add or remove a restricted group.

    Its own request because a restricted group is two keys, not one:
    ``__Members`` and ``__Memberof``. Removing it clears both in a single
    write — two writes would raise the policy version in between, and the
    second would be refused as somebody else's change.
    """

    sid: str = Field(min_length=3, max_length=190)
    present: bool
    expected_version: int | None = Field(
        default=None,
        ge=0,
        description="The versionNumber the form was filled in from; a mismatch is refused",
    )


class SetSecurityValueRequest(StrictModel):
    """One setting in ``GptTmpl.inf``.

    *value* is a string for a plain setting and a list of SIDs for a user
    right or a restricted group; null means "not defined", which in this file
    is an absent key rather than a zero.
    """

    # Backslashes and dots stay allowed — [Registry Values] keys are registry
    # paths. What is refused is anything that would end the line or start a
    # section: samcon.gpo.security.check_safe explains why, and enforces it
    # again where the file is actually built.
    section: str = Field(min_length=1, max_length=64, pattern=r"^[^\r\n\[\]=]+$")
    key: str = Field(min_length=1, max_length=256, pattern=r"^[^\r\n\[\]=]+$")
    value: str | list[str] | None = Field(default=None)
    expected_version: int | None = Field(
        default=None,
        ge=0,
        description="The versionNumber the form was filled in from; a mismatch is refused",
    )


class RedirectFolderRequest(StrictModel):
    """One folder, one group. Null *path* stops redirecting that pairing."""

    folder: str = Field(min_length=38, max_length=38, pattern=r"^\{[0-9A-Fa-f-]{36}\}$")
    sid: str = Field(min_length=3, max_length=184, pattern=r"^[Ss]-[\d-]+$")
    path: str | None = Field(default=None, max_length=1024)
    expected_version: int | None = Field(
        default=None,
        ge=0,
        description="The versionNumber the form was filled in from; a mismatch is refused",
    )


class AssignWmiFilterRequest(StrictModel):
    filter_dn: str | None = Field(
        default=None, max_length=1024, description="Null clears the assignment"
    )


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


class AddAceRequest(StrictModel):
    trustee_sid: str = Field(min_length=3, max_length=184, pattern=r"^S-\d+-\d+(-\d+)*$")
    mask: int = Field(gt=0, le=0xFFFFFFFF, description="Access mask; see samcon.ad.rights")
    deny: bool = False
    object_guid: str | None = Field(
        default=None, max_length=38, description="Extended right, class or attribute the ACE covers"
    )
    applies_to_guid: str | None = Field(
        default=None, max_length=38, description="Object class the ACE is inherited to"
    )
    inherit_to_children: bool = False
    expected_sddl: str | None = Field(
        default=None,
        description="The DACL as it was read; the write is refused if it changed since",
    )


class RemoveAceRequest(StrictModel):
    index: int = Field(ge=0, description="Position of the entry as returned by GET /security/acl")
    expected_sddl: str | None = None


class DelegateRequest(StrictModel):
    template_id: str = Field(min_length=1, max_length=64)
    trustee_sid: str = Field(min_length=3, max_length=184, pattern=r"^S-\d+-\d+(-\d+)*$")
    expected_sddl: str | None = None


class DeleteProtectionRequest(StrictModel):
    protect: bool


class CreateOURequest(StrictModel):
    parent_dn: str = Field(min_length=3)
    name: str = Field(min_length=1, max_length=64)
    description: str | None = None
    protect_from_deletion: bool = True


class UpdateOURequest(StrictModel):
    attributes: dict[str, Any] | None = None
    protect_from_deletion: bool | None = None
