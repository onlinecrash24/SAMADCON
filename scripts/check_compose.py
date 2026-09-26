"""The deployment stack, as Docker Compose itself reads it.

check_versions.py compares the compose files as text: the two copies agree,
and .env.example names what they read. It cannot say what a line *means* to
Compose, and one line needs exactly that:

    "${SAMADCON_BIND:+${SAMADCON_BIND}:}${SAMADCON_HTTPS_PORT}:8443"

In 0.5.2 the port was bound to 127.0.0.1 unless SAMADCON_BIND said otherwise.
The published-image stack later bound every interface, and when the source
build's compose file went, SAMADCON_BIND went with it — a value left in an old
.env stopped doing anything, and nobody was told. It is back, in a form that
keeps "unset" meaning what it has meant since: every interface, IPv4 and IPv6.
A default of 0.0.0.0 would have looked the same and published on IPv4 alone.

That form is documented Compose interpolation, nested. It was not run on the
machine it was written on, which had no Docker — so it is run here, on every
push, by the only thing whose opinion counts: ``docker compose config``.

Needs Docker Compose v2. Without it the check says so and passes, unless
REQUIRE_DOCKER is set, which the CI job does.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STACKS = (ROOT / "docker-compose.yml", ROOT / "docker" / "docker-compose.yml")
ENV_EXAMPLE = ROOT / ".env.example"

# (what SAMADCON_BIND is set to, the host address Compose must end up with)
# None for the first means unset; None for the second means no address at all,
# which is every interface.
CASES = (
    (None, None),
    ("", None),
    ("127.0.0.1", "127.0.0.1"),
    ("192.168.1.5", "192.168.1.5"),
)


def binding(stack: Path, bind: str | None) -> tuple[str | None, str]:
    """The host address and port Compose publishes 8443 on."""
    env = {key: value for key, value in os.environ.items() if key != "SAMADCON_BIND"}
    if bind is not None:
        env["SAMADCON_BIND"] = bind
    result = subprocess.run(
        [
            "docker", "compose",
            "--file", str(stack),
            "--env-file", str(ENV_EXAMPLE),
            "config", "--format", "json",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"{stack}: docker compose config failed:\n{result.stderr}")

    ports = json.loads(result.stdout)["services"]["samadcon"]["ports"]
    published = [port for port in ports if int(port["target"]) == 8443]
    if len(published) != 1:
        raise SystemExit(f"{stack}: expected one port for 8443, found {ports}")
    return published[0].get("host_ip") or None, str(published[0]["published"])


def main() -> int:
    if shutil.which("docker") is None or subprocess.run(
        ["docker", "compose", "version"], capture_output=True, check=False
    ).returncode != 0:
        if os.environ.get("REQUIRE_DOCKER"):
            print("docker compose is required here and is not available", file=sys.stderr)
            return 1
        print("docker compose not available — skipped")
        return 0

    found: list[str] = []
    for stack in STACKS:
        for bind, expected in CASES:
            address, port = binding(stack, bind)
            label = "unset" if bind is None else repr(bind)
            if address != expected or port != "8443":
                found.append(
                    f"{stack.relative_to(ROOT)} with SAMADCON_BIND {label}: "
                    f"published on {address or 'every interface'}:{port}, "
                    f"expected {expected or 'every interface'}:8443"
                )
            else:
                where = address or "every interface"
                print(f"{stack.relative_to(ROOT)}, SAMADCON_BIND {label}: {where}:{port}")

    if found:
        print("\nThe stack does not bind where it says it does:\n", file=sys.stderr)
        for problem in found:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
