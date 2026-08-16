"""Delegation templates.

ADUC's delegation wizard exists because nobody assembles an access mask by
hand: the common tasks — let the service desk reset passwords, let an
assistant maintain a group's membership — each map to a specific combination
of rights, object types and extended-right GUIDs that is tedious to get right
and easy to get subtly wrong.

Each template below is one such task, expressed the way an administrator
thinks about it. They apply to containers and inherit to the objects inside,
which is what makes them useful in the first place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from samadcon.ad import rights
from samadcon.core.errors import NotFound

# Extended rights, by their well-known GUIDs (MS-ADTS 5.1.3.2.1). These are
# stable across every Active Directory and Samba domain.
RIGHT_RESET_PASSWORD = "00299570-246d-11d0-a768-00aa006e0529"
RIGHT_CHANGE_PASSWORD = "ab721a53-1e2f-11d0-9819-00aa0040529b"

# Schema GUIDs for the classes a delegation applies to.
CLASS_USER = "bf967aba-0de6-11d0-a285-00aa003049e2"
CLASS_GROUP = "bf967a9c-0de6-11d0-a285-00aa003049e2"
CLASS_COMPUTER = "bf967a86-0de6-11d0-a285-00aa003049e2"
CLASS_ORGANIZATIONAL_UNIT = "bf967aa5-0de6-11d0-a285-00aa003049e2"

# Attribute GUIDs used by the membership template.
ATTR_MEMBER = "bf9679c0-0de6-11d0-a285-00aa003049e2"
ATTR_LOCKOUT_TIME = "28630ebf-41d5-11d1-a9c1-0000f80367c1"
ATTR_PWD_LAST_SET = "bf967a0a-0de6-11d0-a285-00aa003049e2"


@dataclass(frozen=True)
class AcePlan:
    """One ACE a template will create."""

    mask: int
    object_guid: str | None = None
    applies_to_guid: str | None = None


@dataclass(frozen=True)
class Template:
    id: str
    aces: list[AcePlan] = field(default_factory=list)
    # Whether the task only makes sense on a container.
    container_only: bool = True


TEMPLATES: tuple[Template, ...] = (
    Template(
        id="reset_user_passwords",
        aces=[
            # The extended right itself …
            AcePlan(
                mask=rights.SEC_ADS_CONTROL_ACCESS,
                object_guid=RIGHT_RESET_PASSWORD,
                applies_to_guid=CLASS_USER,
            ),
            # … plus the ability to force a change at next logon, which is what
            # a help desk reset means in practice.
            AcePlan(
                mask=rights.SEC_ADS_WRITE_PROP,
                object_guid=ATTR_PWD_LAST_SET,
                applies_to_guid=CLASS_USER,
            ),
        ],
    ),
    Template(
        id="unlock_users",
        aces=[
            AcePlan(
                mask=rights.SEC_ADS_READ_PROP | rights.SEC_ADS_WRITE_PROP,
                object_guid=ATTR_LOCKOUT_TIME,
                applies_to_guid=CLASS_USER,
            )
        ],
    ),
    Template(
        id="manage_group_membership",
        aces=[
            AcePlan(
                mask=rights.SEC_ADS_READ_PROP | rights.SEC_ADS_WRITE_PROP,
                object_guid=ATTR_MEMBER,
                applies_to_guid=CLASS_GROUP,
            )
        ],
    ),
    Template(
        id="create_delete_users",
        aces=[
            AcePlan(
                mask=rights.SEC_ADS_CREATE_CHILD | rights.SEC_ADS_DELETE_CHILD,
                object_guid=CLASS_USER,
            ),
            # Without full control over the objects themselves, creating one is
            # of little use — this is what ADUC's equivalent task grants.
            AcePlan(mask=rights.SEC_ADS_FULL_CONTROL, applies_to_guid=CLASS_USER),
        ],
    ),
    Template(
        id="create_delete_groups",
        aces=[
            AcePlan(
                mask=rights.SEC_ADS_CREATE_CHILD | rights.SEC_ADS_DELETE_CHILD,
                object_guid=CLASS_GROUP,
            ),
            AcePlan(mask=rights.SEC_ADS_FULL_CONTROL, applies_to_guid=CLASS_GROUP),
        ],
    ),
    Template(
        id="join_computers",
        aces=[
            AcePlan(
                mask=rights.SEC_ADS_CREATE_CHILD | rights.SEC_ADS_DELETE_CHILD,
                object_guid=CLASS_COMPUTER,
            ),
            AcePlan(mask=rights.SEC_ADS_FULL_CONTROL, applies_to_guid=CLASS_COMPUTER),
        ],
    ),
    Template(
        id="read_all",
        aces=[
            AcePlan(
                mask=rights.SEC_ADS_READ_PROP | rights.SEC_ADS_LIST | rights.SEC_STD_READ_CONTROL
            )
        ],
        container_only=False,
    ),
    Template(
        id="full_control",
        aces=[AcePlan(mask=rights.SEC_ADS_FULL_CONTROL)],
        container_only=False,
    ),
)

_BY_ID = {template.id: template for template in TEMPLATES}


def describe_templates() -> list[dict[str, Any]]:
    """The catalogue for the UI. Labels are translated on the client."""
    return [
        {
            "id": template.id,
            "container_only": template.container_only,
            "ace_count": len(template.aces),
        }
        for template in TEMPLATES
    ]


def find(template_id: str) -> Template:
    template = _BY_ID.get(template_id)
    if template is None:
        raise NotFound(
            "Unknown delegation task.",
            code="unknown_delegation_template",
            context={"template_id": template_id},
        )
    return template


def build_aces(template_id: str, trustee_sid: str) -> list[str]:
    """The SDDL ACEs a template grants to *trustee_sid*."""
    from samadcon.ad.sacl import build_ace

    template = find(template_id)
    return [
        build_ace(
            trustee_sid=trustee_sid,
            mask=plan.mask,
            object_guid=plan.object_guid,
            applies_to_guid=plan.applies_to_guid,
            # Delegation is about the objects inside the container, so every
            # entry inherits downwards.
            inherit_to_children=True,
        )
        for plan in template.aces
    ]
