"""Runtime configuration.

Everything is driven by SAMCON_* environment variables; the entrypoint derives
the Samba configuration from the same values before the application starts.

A realm is no longer required here: administrators can point SAMCON at a
domain when they sign in. Configuring one only sets the default that the
sign-in form pre-fills.
"""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)


class ServerProfile(BaseModel):
    """A pre-configured domain, offered in the sign-in form.

    Loaded from the JSON file named by SAMCON_SERVERS_FILE::

        [
          {
            "id": "prod",
            "label": "Production",
            "hosts": ["dc1.example.lan", "dc2.example.lan"],
            "realm": "EXAMPLE.LAN",
            "ca_file": "/etc/samcon/ca/example.pem"
          }
        ]

    Only ``id`` and ``hosts`` are required — the realm is discovered from the
    server if it is not given.
    """

    id: str
    label: str | None = None
    hosts: list[str] = Field(default_factory=list)
    realm: str | None = None
    ca_file: Path | None = None
    insecure: bool = False

    @field_validator("hosts", mode="before")
    @classmethod
    def _accept_single_host(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("realm", mode="after")
    @classmethod
    def _upper_realm(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SAMCON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Default domain (optional) ----------------------------------------
    # Empty is fine: the sign-in form then asks for a server address.
    realm: str = Field(default="", description="Default Kerberos realm, e.g. EXAMPLE.LAN")
    workgroup: str = Field(default="", description="NetBIOS name; derived from the realm if empty")
    # NoDecode is essential: without it pydantic-settings tries to json.loads
    # the environment value before any validator runs, and a plain
    # "dc1,dc2" blows up at startup.
    dc_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Explicit DC list, comma-separated; empty means DNS SRV discovery",
    )
    servers_file: Path | None = Field(
        default=None, description="JSON file with pre-configured server profiles"
    )
    allow_custom_servers: bool = Field(
        default=True,
        description="Whether administrators may type an arbitrary server address",
    )

    # --- LDAP -------------------------------------------------------------
    ldap_ca_file: Path | None = Field(
        default=None, description="CA bundle validating the DCs' LDAPS certificates"
    )
    ldap_insecure: bool = Field(
        default=False,
        description="Lab only: skip LDAPS certificate validation",
    )
    ldap_timeout_seconds: int = 30
    ldap_page_size: int = 500

    # --- Sessions ---------------------------------------------------------
    ccache_dir: Path = Path("/dev/shm/samcon-ccache")
    session_idle_minutes: int = 60
    login_max_attempts: int = 5
    login_lockout_minutes: int = 5
    cookie_name: str = "samcon_session"
    cookie_secure: bool = True

    # --- Samba ------------------------------------------------------------
    smb_conf: Path = Path("/etc/samcon/smb.conf")
    krb5_config: Path = Path("/etc/samcon/krb5.conf")
    samba_log_level: int = 0

    # --- Runtime ----------------------------------------------------------
    log_level: str = "INFO"
    audit_file: Path = Path("/var/log/samcon/audit.jsonl")
    worker_threads: int = 8
    operation_timeout_seconds: int = 120
    dev_mode: bool = False
    version: str = "0.1.0"

    @field_validator("realm", mode="after")
    @classmethod
    def _upper_realm(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("ldap_ca_file", "servers_file", mode="before")
    @classmethod
    def _empty_path_is_none(cls, value: object) -> object:
        """Treat an empty environment variable as "not set".

        docker compose substitutes an unset variable with an empty string, and
        pydantic would turn that into ``Path(".")`` — which would make us pass
        the working directory to Samba as the CA bundle.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("dc_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        # Compose passes a comma-separated string; pydantic would otherwise
        # try to read it as JSON.
        if isinstance(value, str):
            return [host.strip() for host in value.split(",") if host.strip()]
        return value

    @field_validator("log_level", mode="after")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.strip().upper()

    @property
    def netbios_name(self) -> str:
        return self.workgroup.strip().upper() or (self.realm.split(".")[0] if self.realm else "")

    @property
    def base_dn(self) -> str:
        """Default naming context derived from the realm.

        Only a fallback: the real value is read from the DC's rootDSE, which is
        authoritative and handles domains whose DN does not mirror the realm.
        """
        if not self.realm:
            return ""
        return ",".join(f"DC={label}" for label in self.realm.lower().split("."))

    @property
    def tls_verify_peer(self) -> str:
        """Value for smb.conf's `tls verify peer`.

        Only an explicit SAMCON_LDAP_INSECURE=1 turns validation off — dev_mode
        deliberately does not, so a lab setup cannot silently become the
        production default. Individual connections can still opt out, which is
        a per-session decision the administrator makes knowingly.
        """
        return "no_check" if self.ldap_insecure else "ca_and_name"

    # -- connection targets -------------------------------------------------

    @property
    def default_target(self):
        """The container's configured domain, or None if it has none."""
        from samcon.ad.target import ConnectionTarget

        if not self.realm:
            return None
        return ConnectionTarget(
            realm=self.realm,
            hosts=tuple(self.dc_hosts),
            label=None,
            ca_file=self.ldap_ca_file,
            insecure=self.ldap_insecure,
            profile_id="default",
        )

    def load_profiles(self) -> list[ServerProfile]:
        """Read the server profiles.

        A broken profile file must not stop the application from starting —
        administrators can still type a server address. It is logged loudly
        instead.
        """
        if self.servers_file is None:
            return []
        if not self.servers_file.exists():
            logger.warning("server profile file not found: %s", self.servers_file)
            return []

        try:
            raw = json.loads(self.servers_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.error("cannot read server profiles from %s: %s", self.servers_file, exc)
            return []

        if isinstance(raw, dict):
            raw = raw.get("servers", [])
        if not isinstance(raw, list):
            logger.error("%s must contain a list of server profiles", self.servers_file)
            return []

        profiles: list[ServerProfile] = []
        for entry in raw:
            try:
                profiles.append(ServerProfile.model_validate(entry))
            except Exception as exc:  # noqa: BLE001 — skip the bad one, keep the rest
                logger.error("ignoring invalid server profile %r: %s", entry, exc)
        return profiles


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
