"""The domain's password and lockout policy, written.

A router of its own because diagnostics, which shows the policy, is read-only
by design. On a Samba DC these attributes of the domain object are the policy
for domain accounts — the Default Domain Policy is not copied onto them, as a
Windows DC would — so this is what `samba-tool domain passwordsettings set`
does, from the console.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from samadcon.ad import password_policy
from samadcon.ad.access import ad_write
from samadcon.api.common import Audit
from samadcon.auth.deps import VerifiedSession, VerifiedWorker
from samadcon.schemas.requests import PasswordPolicyRequest

router = APIRouter(prefix="/password-policy", tags=["password-policy"])


@router.put("")
async def set_password_policy(
    payload: PasswordPolicyRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
) -> dict[str, Any]:
    """Replace the given parts of the policy; fields left out stay as they are."""
    request = payload.model_dump(exclude_none=True)
    with audit.operation("domain.password_policy", **request) as record:
        result = await ad_write(
            worker,
            session,
            password_policy.set_password_policy,
            label="domain.password_policy",
            **request,
        )
        record["changes"] = result["applied"]
    return result["policy"]
