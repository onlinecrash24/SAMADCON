<p align="center">
  <img src="docs/brand/samadcon-3a-transparent.svg"
       alt="SAMADCON — the Samba AD console" width="560">
</p>

<p align="center"><em><a href="README.de.md">Deutsche Fassung</a></em></p>

A browser-based management console for Samba AD DC domains. It replaces the Windows RSAT tools
(ADUC, DNS Manager, Sites & Services, GPMC) with a Docker container — **group policy editor
included**, which comparable projects leave out.

SAMADCON speaks nothing but standard protocols: **LDAPS, Kerberos and SMB**. The container does
not have to run on a domain controller and never touches its file system directly.

> Status: all five milestones are built and verified against a real Samba AD domain — see
> [Milestones](#milestones). Released as 0.5.x: usable today, with the interface still
> changing between versions. What changed in each release is in the
> [changelog](CHANGELOG.md).

<p align="center">
  <a href="docs/screenshots/SAMADCON_GPO_Editor.png">
    <img src="docs/screenshots/SAMADCON_GPO_Editor.png" width="900" alt="The SAMADCON group policy editor: a policy window open over the console on its Administrative templates tab, listing the printer settings of the computer configuration with their state and scope, the policy tree behind it.">
  </a>
</p>

## Why

RSAT requires a domain-joined Windows client. In a pure Linux environment it is simply not
available, and `samba-tool`, being a command-line tool, covers only part of the daily work.

## What it looks like

The window above is the part comparable projects leave out: administrative templates, security
settings, the Samba/VGP tree, preferences, scripts and folder redirection, each on its own tab
of one policy — and the window floats over the console with a taskbar of its own, the way an
MMC snap-in does.

<p align="center">
  <a href="docs/screenshots/SAMADCON_Users_and_Computers.png">
    <img src="docs/screenshots/SAMADCON_Users_and_Computers.png" width="900" alt="The Users and Computers console: the directory tree on the left, the objects of an organisational unit in the middle, and the selected user's properties on the right.">
  </a>
</p>

**Users and Computers** — tree, object list, and the properties of whatever is selected: the
arrangement ADUC uses. Each console is a tab of its own, because in RSAT each of them is a
separate program rather than a branch of one tree.

<p align="center">
  <a href="docs/screenshots/SAMADCON_right_click.png">
    <img src="docs/screenshots/SAMADCON_right_click.png" width="900" alt="The group policy link tree with a link's context menu open, offering to disable the link, to enforce it, or to remove it.">
  </a>
</p>

**Group Policy Management** — the tree says which policies apply where, and a link's own menu
sets its two switches and removes it. Right-click works on the objects themselves, not only on
a toolbar somewhere above them.

<p align="center">
  <img src="docs/screenshots/SAMADCON_link_GPO.gif" width="900" alt="A policy dragged from the list onto an organisational unit in the tree; the console asks for confirmation and the link then appears under that unit.">
</p>

**Linking by dragging** — drop a policy onto an organisational unit and it asks before it
links. One policy can be linked to as many units as you like.

The screenshots are of a live Samba AD domain, not a mock-up.

## Security model

Every administrator signs in with their **own AD account**. SAMADCON obtains a Kerberos TGT per
session into a session-private credential cache on tmpfs and runs **every** LDAP and SMB
operation with that account's rights:

- The tool itself needs **no** privileged service account.
- AD delegation, security filtering and server-side auditing keep working.
- The password is used to obtain the ticket and for nothing else — **never stored, never logged**.
- Every write also lands in the local audit log: who, what, DN, attribute diff.

## Multiple domains

The domain is chosen **at sign-in**, not when the container starts. The sign-in form offers:

- **free entry** of an IP address or host name,
- **pre-configured domains** from `SAMADCON_SERVERS_FILE` (see
  [servers.example.json](docker/servers/servers.example.json)),
- the container's **default domain**, if one is configured.

**The shipped stack turns free entry off.** It writes `SAMADCON_ALLOW_CUSTOM_SERVERS: "0"`
into the compose file itself, because one instance per domain is the arrangement it is
written for: the sign-in form then shows the configured domain and nothing else, and the
backend refuses a typed address as well. It is a fixed value rather than a `${VAR}`, so
changing it means editing the file — a Portainer environment field cannot reach it. Set it
to `1` for an instance meant to reach several domains; everything below describes that case.

Given an IP address, SAMADCON works the domain out for itself: an anonymous rootDSE read returns
the realm, the domain controller's FQDN and the naming contexts. That step is necessary because
Kerberos issues tickets for `ldap/dc1.example.lan@EXAMPLE.LAN` — a bare address yields neither an
SPN nor a realm. A Kerberos configuration naming exactly that address as the KDC is then written,
so signing in works even without matching DNS records. Several realms are supported side by side.

That holds for the path where an **address** is given. Sign in with a **domain name** and SAMADCON
has to find a controller first, which it does through SRV records — and those need a resolver that
serves the domain. A container whose resolver does not know it fails with
`NT_STATUS_NO_LOGON_SERVERS`, having never reached a DC to be refused by. Point `dns:` at the
domain's own resolver, or name the controllers in `SAMADCON_DC_HOSTS` and skip discovery
altogether.

### Transport

SAMADCON connects in two stages, both encrypted:

1. **LDAP (389) with GSSAPI sign & seal** — the Kerberos session key encrypts the traffic, with no
   certificate involved. This is the path `samba-tool` and the Windows tools take, and the one
   best supported in Samba's client stack.
2. **LDAPS (636)** as a fallback, for when port 389 is closed.

`seal` is *required*, not requested: a server that cannot do it fails the connection rather than
quietly dropping to plain text.

The sign-in form reports in advance whether the LDAPS certificate can be validated. Against a
self-signed Samba certificate the check can be turned off **per session** — which affects stage 2
only. The ordinary case needs neither a certificate nor a CA file.

## Quick start

Every release is built and pushed to the GitHub container registry. Nothing has to be cloned
or built:

```bash
docker pull ghcr.io/onlinecrash24/samadcon:latest
```

**Which tag.**

| Tag | What it is |
|---|---|
| `latest` | The newest release. Moves when one is tagged, which is what the examples below use. |
| `0.5.16` | One release, and it never changes. **Pin this where an upgrade should be a decision.** |
| `0.5` | The newest release of that minor series. |
| `dev` | The tip of the DEV branch: what is being worked on, before a release. |
| `sha-<short>` | One commit. Every build carries one. |

Only a push to `DEV` and a version tag build an image; a push to `main` builds nothing. So
`latest` is the newest *release*, not the newest commit on the default branch, and `dev` is
the only tag that moves with day-to-day work.

`latest` is the right default: it is a release, it was tested, and it does not go stale the
way a version written into a document does. Pin a version where an upgrade should be a
decision rather than a side effect of pulling. Take `dev` only to try something that is not
released yet, and expect it to change under you.

Three ways to run it follow. The first is the shortest thing that works. The second is the
same stack with its settings moved out into a `.env`, and it is the file this repository
ships. The third builds the image from source.

### 1 · The shortest stack

Paste this into a Portainer stack, or save it as `docker-compose.yml` in an empty directory
and run `docker compose up -d`. Three values have to be changed — the name the console is
reached under, the realm, and the domain controller — and nothing has to be prepared on the
host:

```yaml
services:
  samadcon:
    image: ghcr.io/onlinecrash24/samadcon:latest
    container_name: samadcon
    restart: unless-stopped
    environment:
      # The name people type. It becomes the CN and the SAN of the self-signed
      # certificate, and that is the only thing it does.
      SAMADCON_PUBLIC_HOST: "samadcon.example.lan"
      # The Kerberos realm, upper case.
      SAMADCON_REALM: "EXAMPLE.LAN"
      # The domain controller. An IP is fine: its own name is read from the rootDSE.
      SAMADCON_DC_HOSTS: "192.168.1.1"
      # INFO names what happens; DEBUG is for tracking a problem down.
      SAMADCON_LOG_LEVEL: "INFO"
      # Only the domain above; the sign-in form loses its free address
      # field. 1 for an instance that should reach several domains.
      SAMADCON_ALLOW_CUSTOM_SERVERS: "0"
    ports:
      # Every interface, which is what a browser on another machine needs.
      # Use "127.0.0.1:8443:8443" when a reverse proxy runs on this host.
      - "8443:8443"
    # The resolver has to serve the domain, because Kerberos finds its KDC and
    # the console finds the other controllers through SRV records — in nearly
    # every domain that is the controller above, and the realm in lower case.
    dns:
      - "192.168.1.1"
    dns_search:
      - "example.lan"
    volumes:
      # A certificate of your own goes in here; without one a self-signed one is
      # made on first start.
      - samadcon-tls:/etc/samadcon/tls
      # CA bundles for validating the DCs' LDAPS certificates. Optional: the
      # primary path is LDAP with Kerberos encryption and needs no certificate.
      - samadcon-ca:/etc/samadcon/ca
      - samadcon-cache:/var/cache/samadcon
      - samadcon-data:/var/lib/samadcon
      # The audit trail should outlive the container.
      - samadcon-logs:/var/log/samadcon
    # Kerberos credential caches live in /dev/shm and never reach a disk.
    shm_size: 64m
    tmpfs:
      # uid/gid are required: a tmpfs mount belongs to root by default.
      - /run/samadcon:mode=0700,uid=1000,gid=1000,size=8m
    # Nothing here needs to become more privileged than it starts.
    security_opt:
      - no-new-privileges:true
    # nginx listens on 8443, above the privileged range — no capability needed.
    cap_drop:
      - ALL

volumes:
  samadcon-tls:
  samadcon-ca:
  samadcon-cache:
  samadcon-data:
  samadcon-logs:
```

The console is then at `https://<host>:8443`, with a self-signed certificate on first start.

Two things in that block are worth knowing rather than copying:

- **Named volumes, not bind mounts.** A stack pasted into Portainer's web editor has no
  directory of its own on the host: a relative path like `./tls` is resolved by the Docker
  daemon, not by Portainer, and Docker creates whatever is missing as a directory owned by
  root. The container runs as uid 1000 and could not write its certificate there. The image
  creates `/etc/samadcon/tls`, `/etc/samadcon/ca` and `/etc/samadcon/servers` and gives them
  to uid 1000, and Docker seeds a named volume from the image directory with that ownership
  — so the certificate lands where it belongs. To keep files on the host after all, use an
  **absolute** path: `/srv/samadcon/tls:/etc/samadcon/tls`. That works in a stack; a
  relative one does not.
- **`container_name` is a name you are choosing.** Without it, Portainer names the container
  after the stack and the service. With it, a second stack of the same image cannot start,
  and renaming the stack in Portainer does not reach the container. One deployment per host
  is the normal case, and there the fixed name is the more useful of the two.

If the host cannot be pointed at a resolver that serves the domain, one name can be nailed
down by hand:

```yaml
    extra_hosts:
      - "smb-ad.example.lan:192.168.1.1"
```

That is a last resort, not a replacement for `dns:`. The entry resolves that one name and
carries no SRV records, so the KDC and the other domain controllers are still found through
a resolver, or not at all.

### 2 · The same stack, with the settings in a `.env`

This is [`docker-compose.yml`](docker-compose.yml) as the repository ships it: the stack
above with every value replaced by its name, so that the stack and the settings are two
files — one that comes from here and is replaced on an update, one that belongs to your
domain and is not.

```yaml
services:
  samadcon:
    image: ghcr.io/onlinecrash24/samadcon:latest
    restart: unless-stopped
    container_name: samadcon
    environment:
      SAMADCON_PUBLIC_HOST: "${SAMADCON_PUBLIC_HOST}"
      # Only for a deployment that also publishes port 8080, where the redirect
      # from HTTP to HTTPS lives. Publishing 8443 alone, nothing reads it.
#      SAMADCON_PUBLIC_HTTPS_PORT: "${SAMADCON_PUBLIC_HTTPS_PORT:-8443}"
      SAMADCON_REALM: "${SAMADCON_REALM}"
      SAMADCON_DC_HOSTS: "${SAMADCON_DC_HOSTS}"
      SAMADCON_LOG_LEVEL: "${SAMADCON_LOG_LEVEL}"
      # Only the domain configured above. The sign-in form then shows that one
      # and nothing else. One instance per domain is the arrangement this stack
      # is written for, so it is a fixed value rather than a variable: set it
      # to 1 here, in the file, for an instance meant to reach several. A
      # Portainer environment field cannot reach it — those feed ${VAR} only.
      SAMADCON_ALLOW_CUSTOM_SERVERS: "0"
      # Only behind a reverse proxy, and then its host's address. Never 0.0.0.0/0.
      SAMADCON_TRUSTED_PROXIES: "${SAMADCON_TRUSTED_PROXIES}"
    ports:
      - "${SAMADCON_HTTPS_PORT}:8443"
    dns:
      - "${SAMADCON_DNS}"
    dns_search:
      - "${SAMADCON_DNS_SEARCH}"
    volumes:
      - samadcon-tls:/etc/samadcon/tls
      - samadcon-ca:/etc/samadcon/ca
      - samadcon-cache:/var/cache/samadcon
      - samadcon-data:/var/lib/samadcon
      - samadcon-logs:/var/log/samadcon
    shm_size: 64m
    tmpfs:
      - /run/samadcon:mode=0700,uid=1000,gid=1000,size=8m
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL

volumes:
  samadcon-tls:
  samadcon-ca:
  samadcon-cache:
  samadcon-data:
  samadcon-logs:
```

On a host with `docker compose`, the settings go in a `.env` beside it:

```bash
cp .env.example .env
$EDITOR .env
docker compose up -d
```

**In Portainer there is no `.env` file.** Type the same names into the stack's environment
fields, or upload one with *Load variables from .env file*. The compose file is not touched
either way, which is the whole point of writing it like this.

The names are in [`.env.example`](.env.example), and `scripts/check_versions.py` checks that
the two files still list the same ones — a variable added to the stack and forgotten in the
example is a setting nobody knows they can change, and one left in the example after the
stack stopped reading it is a setting that does nothing, which is worse.

**None of the values is optional here.** A name that is not set becomes an empty string, not
a default: an empty `dns:` leaves the container without a resolver, and an empty port turns
`"${SAMADCON_HTTPS_PORT}:8443"` into `":8443"`, which Docker reads as *any free host port*.
That is the trade for keeping the values out of the file. Example 1 above is the version for
a deployment that would rather have one file and no second step.

Do not put the domain administrator's password in either file. The console never takes one
from the environment; it asks whoever signs in, and acts with that person's own account.

### 3 · Building from source

There is no compose file for this. The image is built from `docker/Dockerfile`, with the
repository root as the build context — that is not a detail, the Dockerfile copies `backend/`
and `frontend/` out of it:

```bash
git clone https://github.com/onlinecrash24/SAMADCON.git
cd SAMADCON
docker build -f docker/Dockerfile -t samadcon:local .
```

Then run it. This is the stack from example 1 written as a `docker run`, with two differences:
it binds to loopback, because a build in progress is not something to publish on every
interface, and it publishes 8080 as well, which is the port that redirects HTTP to HTTPS and
the only place `SAMADCON_PUBLIC_HTTPS_PORT` is read:

```bash
docker run -d --name samadcon --restart unless-stopped \
  -p 127.0.0.1:8443:8443 \
  -p 127.0.0.1:8080:8080 \
  --dns 192.168.1.1 --dns-search example.lan \
  -e SAMADCON_PUBLIC_HOST=samadcon.example.lan \
  -e SAMADCON_PUBLIC_HTTPS_PORT=8443 \
  -e SAMADCON_REALM=EXAMPLE.LAN \
  -e SAMADCON_DC_HOSTS=192.168.1.1 \
  -e SAMADCON_LOG_LEVEL=DEBUG \
  -v samadcon-tls:/etc/samadcon/tls \
  -v samadcon-ca:/etc/samadcon/ca \
  -v samadcon-cache:/var/cache/samadcon \
  -v samadcon-data:/var/lib/samadcon \
  -v samadcon-logs:/var/log/samadcon \
  --shm-size 64m \
  --tmpfs /run/samadcon:mode=0700,uid=1000,gid=1000,size=8m \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  samadcon:local
```

Every `-e` may be left out: with no domain configured the sign-in form asks for a server
address and works the rest out itself. [What has to be configured](#what-has-to-be-configured)
lists the rest of them.

The interface then runs on `https://localhost:8443`. Without a mounted certificate the
container generates a self-signed one on first start.

Rebuilding is `docker build` again, then `docker rm -f samadcon` and the same `docker run`.
The named volumes survive that — the audit trail lives in `samadcon-logs`.

### Behind a reverse proxy

The stacks above publish on every interface, because a proxy on another machine has to be able
to reach it. With the proxy on this host, bind to loopback instead — `127.0.0.1:8443:8443` — and
then nothing outside the host can reach the console at all. (A source build run by hand binds to loopback — see
[Building from source](#3--building-from-source) — because that is the safe default while
working on it; the published-image stack publishes on every interface, because that is what
a stack on another machine needs.)

**A proxy on another machine** needs the opposite of loopback: SAMADCON has to answer on an
address the proxy host can reach. Everything else follows from four settings, and each of the
usual mistakes is one of them pointing at the wrong thing:

| Setting | What it has to be | Wrong when |
|---|---|---|
| The address in `ports:` (or in `-p`) | An address the proxy host can reach — the LAN address of this host, or none at all, which publishes on every interface | Left at `127.0.0.1`: the proxy gets connection refused |
| `SAMADCON_TRUSTED_PROXIES` | The proxy **host's** address, not its container's | The audit log keeps showing the proxy |
| `SAMADCON_PUBLIC_HOST` | The name people type in the browser | Only affects the self-signed certificate, which the proxy does not check |
| `SAMADCON_PUBLIC_HTTPS_PORT` | The port people reach, so `443` when the proxy serves 443 | Only affects the redirect on 8080, which nobody reaches through a proxy |

In the proxy, forward to **port 8443 over https**. Port 8080 serves a redirect and the health
check and nothing else, and sending credentials to it would put them on the wire in clear. The
certificate on 8443 is self-signed unless you mounted your own; proxies do not validate an
upstream certificate by default, and Nginx Proxy Manager does not.

The proxy's address is worth reading rather than guessing. A proxy that runs in Docker reaches
SAMADCON as its *host's* address, not the container's, because the host masquerades the
connection. Sign in once and look at `client_ip` in the audit log: the address you find there is
the one that belongs in `SAMADCON_TRUSTED_PROXIES`. Put it in, sign in again, and the same field
should now hold the browser's address instead.

A proxy has to be named, or the audit log loses the one thing it is for:

```yaml
SAMADCON_TRUSTED_PROXIES: "192.168.1.5"     # or "10.0.0.0/8, 192.168.1.5"
```

nginx sees only the machine that connected to it, which behind a proxy is the proxy. Without
this, every audit entry records the proxy's address, and two administrators working through the
same one become indistinguishable in exactly the record meant to tell them apart.

It is a list and not a switch because `X-Forwarded-For` is a plain header that any client can
send. Only a hop named here is believed; an address that is not on the list is treated as the
caller, whatever it claims. Leave it empty when there is no proxy — a wrong entry is worse than
none, since it lets that host claim to be anyone.

> **Never `0.0.0.0/0`, and never `::/0`.** That does not configure the setting generously, it
> switches it off: every host becomes a trusted hop, every client may state who it is, and the
> audit log fills with addresses the callers chose for themselves. It is worse than leaving the
> setting empty — an empty list records the proxy, which is merely uninformative, while a
> wide-open one records fiction that reads like fact.

Name the proxy's own address. Not the subnet it sits in "to be safe": every host in that subnet
inherits the right to claim any identity in your audit trail.

## Deployment

### What has to be on the target system

Nothing, when running the published image: it carries everything, and
[Quick start](#quick-start) is the whole procedure. What follows is for a build from source.

```
SAMADCON/
├── docker-compose.yml          for the published image; not used by a source build
├── .dockerignore               keeps node_modules and local secrets out of the image
├── docker/
│   ├── docker-compose.yml      the same file again, beside the rest of the docker assets
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── nginx.conf.template
│   └── supervisord.conf
├── backend/
│   ├── pyproject.toml
│   └── samadcon/
└── frontend/
    ├── package.json
    ├── package-lock.json
    ├── index.html
    ├── tsconfig.json
    ├── vite.config.ts
    ├── src/
    └── public/
```

`backend/tests/` is only needed when building with `--target test`.

Do not copy along: `frontend/node_modules`, `frontend/dist`, `backend/samadcon.egg-info`, any
`__pycache__`, `.venv`. The `.dockerignore` catches those and at the same time keeps certificates
and any local `.env` out of the image — configuration arrives at runtime, never in a layer.

### What has to be configured

Every setting is an environment variable, and every one of them has a default that works. They
reach the container through the stack's `environment:` block, through a `.env`, or through `-e`
on a `docker run` — the same names in all three cases. Nothing has to be set that is not listed
here as one an installation decides.

**The one value practically every installation changes:**

| Setting | Default | What for |
|---|---|---|
| `SAMADCON_PUBLIC_HOST` | `samadcon.local` | The name the console is reached under. It becomes the CN and the SAN of the self-signed certificate, and nothing else reads it. |

**The domain.** Both may stay empty: the sign-in form then asks for a server address and works
the domain out from it.

| Setting | Default | What for |
|---|---|---|
| `SAMADCON_REALM` | empty | The Kerberos realm, upper case. |
| `SAMADCON_DC_HOSTS` | empty | The controllers, comma-separated. An IP is fine: Kerberos issues tickets for `ldap/<hostname>@REALM` and has no principal for a bare address, so a configured address is probed like a typed one and the DC's own name comes from its rootDSE. |
| `SAMADCON_WORKGROUP` | the realm up to the first dot | The NetBIOS name, when that derivation is wrong. |
| `SAMADCON_SERVERS_FILE` | none | A JSON file of domains to offer in the sign-in form; see `docker/servers/servers.example.json`. |
| `SAMADCON_ALLOW_CUSTOM_SERVERS` | `1`, and `0` in the stack above | `0` allows only the configured domains: the sign-in form loses "Anderer Server ..." and its free address field, and the backend refuses a typed address too. The stack sets it as a literal, so it is changed in the file. If you do set it from the environment, do not set it empty — it is a boolean, and an empty value stops the container from starting. |

**LDAP.**

| Setting | Default | What for |
|---|---|---|
| `SAMADCON_LDAP_TRANSPORTS` | `ldap,ldaps` | Which transports may be tried, in order. Both encrypt — `ldap` with the Kerberos session key, sign-and-seal *required* rather than requested, `ldaps` with TLS. Settling on one is a policy decision, not a hardening step, and it removes the fallback. |
| `SAMADCON_LDAP_CA_FILE` | none | The CA that signed the DCs' certificates, for validating LDAPS. A Samba DC keeps its own at `/var/lib/samba/private/tls/ca.pem`. |
| `SAMADCON_LDAP_INSECURE` | `0` | Turns certificate validation off for every connection. Prefer the per-session checkbox in the sign-in form over this switch. |
| `SAMADCON_LDAP_TIMEOUT_SECONDS` | `30` | How long a single LDAP call may take. |
| `SAMADCON_LDAP_PAGE_SIZE` | `500` | Objects per page. The console walks every page; this only decides how many round trips that takes. |

**The web front end.**

| Setting | Default | What for |
|---|---|---|
| `SAMADCON_PUBLIC_HTTPS_PORT` | `443` | The port the redirect on 8080 sends people to. Read **only** when port 8080 is published; a deployment that publishes 8443 alone never reaches that server block. |
| `SAMADCON_TRUSTED_PROXIES` | empty | The reverse proxy in front of the container, if there is one. Without it every audit entry records the proxy instead of the administrator — see [Behind a reverse proxy](#behind-a-reverse-proxy). |

**Sessions.**

| Setting | Default | What for |
|---|---|---|
| `SAMADCON_TICKET_LIFETIME` | `10h` | How long a Kerberos ticket is good for. |
| `SAMADCON_RENEW_LIFETIME` | `7d` | How long it may be renewed. |
| `SAMADCON_SESSION_IDLE_MINUTES` | `60` | Idle time before a session is dropped. |
| `SAMADCON_LOGIN_MAX_ATTEMPTS` | `5` | Failed sign-ins per account before SAMADCON stops forwarding attempts to the DC — which is what keeps the web form from triggering AD account lockout. |
| `SAMADCON_LOGIN_LOCKOUT_MINUTES` | `5` | How long it then waits. |

**Logging.**

| Setting | Default | What for |
|---|---|---|
| `SAMADCON_LOG_LEVEL` | `INFO` | `INFO` names what happens; `DEBUG` is for tracking a problem down. |
| `SAMADCON_AUDIT_FILE` | `/var/log/samadcon/audit.jsonl` | Every write operation lands here: who, what, DN, attribute diff. |
| `SAMADCON_SAMBA_LOG_LEVEL` | `0` | Raise for Samba protocol traces. Noisy — leave at 0 outside a hunt. |
| `SAMADCON_DEV_MODE` | `0` | Extra diagnostics and a more talkative error surface. |

**A password is not among them.** There is no setting that takes one, in any of these tables.
The console asks whoever signs in and acts with that person's own account, which is also what
makes the audit trail worth keeping.

### The clock

Kerberos rejects a ticket whose timestamp is more than about five minutes out, and that is the
failure that looks most like a wrong password. SAMADCON does not leave you guessing: the sign-in
stops with `clock_skew` and says the clocks differ.

**There is no time-server setting here, and no NTP client in the image.** Both are deliberate. A
container has no clock of its own — it reads the host's — and `cap_drop: ALL` takes `CAP_SYS_TIME`
away, so a container that could set the time would be setting the *host's*. Synchronising from
inside is not a thing that can be made to work.

So synchronise the Docker host. In an AD domain the authoritative source is the PDC emulator,
which every domain member already follows:

```bash
timedatectl show -p NTPSynchronized     # on the Docker host, not in the container
chronyc sources                         # or: ntpq -p
```

The tolerance itself belongs to the domain, not to the container: *Kerberos Policy → Maximum
tolerance for computer clock synchronisation* (`MaxClockSkew`, in minutes), which the policy
editor shows and can change. Raising it is not the fix — it widens the window in which an
intercepted ticket is still accepted.

### Steps

For the published image, [Quick start](#quick-start) is the procedure and there is nothing to
add. From source:

```bash
docker build -f docker/Dockerfile -t samadcon:local .
docker run -d --name samadcon --restart unless-stopped \
  -p 127.0.0.1:8443:8443 -p 127.0.0.1:8080:8080 \
  --dns 192.168.1.1 --dns-search example.lan \
  -e SAMADCON_PUBLIC_HOST=samadcon.example.lan \
  -e SAMADCON_REALM=EXAMPLE.LAN -e SAMADCON_DC_HOSTS=192.168.1.1 \
  -v samadcon-tls:/etc/samadcon/tls -v samadcon-ca:/etc/samadcon/ca \
  -v samadcon-cache:/var/cache/samadcon -v samadcon-data:/var/lib/samadcon \
  -v samadcon-logs:/var/log/samadcon \
  --shm-size 64m \
  --tmpfs /run/samadcon:mode=0700,uid=1000,gid=1000,size=8m \
  --security-opt no-new-privileges:true --cap-drop ALL \
  samadcon:local
```

For a real certificate, copy `server.crt` and `server.key` into the `samadcon-tls` volume and
restart the container. A named volume is seeded from the image directory, which belongs to uid
1000, so there is nothing to prepare. A **bind mount** is the case that goes wrong: it belongs
to root, the container runs as uid 1000, and if the directory is not writable the entrypoint
falls back to the `samadcon-data` volume with a warning — the certificate is then not where you
look for it. So, if you do bind-mount one:

```bash
mkdir -p docker/tls docker/ca && chown -R 1000:1000 docker/tls
```

Check:

```bash
docker ps
```

The container has a health check on `/api/v1/health` and reports `healthy` after about twenty
seconds. If it does not, `docker logs samadcon` says why. The connection to the DC can be
checked without credentials:

```bash
docker exec samadcon samadconctl probe dc1.example.lan
```

Updating the published image is `docker compose pull && docker compose up -d`; from source it is
`docker build` again, then `docker rm -f samadcon` and the same `docker run`. The volumes
`samadcon-cache`, `samadcon-data` and `samadcon-logs` — the audit trail lives in the last one —
survive either.

## Testing against an existing Samba AD

The credentials come from the shell, not from a file — a domain administrator's password has no
business in a file that can be backed up by accident.

Unit tests need no domain and run anywhere. Three of them compare against files GPMC itself
produced, kept in `backend/tests/data/` with a note on
[where they came from](backend/tests/data/PROVENANCE.md) and what was changed to publish them.

The tests live in the image rather than in a mount, which is what the `test` build target is
for. They need no running server of their own — `TestClient` runs the application in-process —
so nothing has to be deployed first and the container goes away again:

```bash
docker build -f docker/Dockerfile --target test -t samadcon:test .
docker run --rm \
  --dns 192.168.1.10 --dns-search example.lan \
  -e TEST_DC_HOST=dc1.example.lan \
  -e TEST_REALM=EXAMPLE.LAN \
  -e TEST_ADMIN_USER=Administrator \
  -e TEST_ADMIN_PASSWORD=... \
  -e TEST_INSECURE=1 \
  -e SAMADCON_COOKIE_SECURE=0 \
  samadcon:test python -m pytest tests/integration -q
```

Without `TEST_DC_HOST` and `TEST_ADMIN_PASSWORD` the tests skip themselves. `SAMADCON_COOKIE_SECURE=0`
is not optional: `TestClient` speaks http, and a `Secure` cookie would be set and never sent
back. Passing the password on the command line rather than writing it into a file is the point
of doing it this way.

> A changed test is copied into the image at build time. After every change to the tests, build
> again before the next `docker exec`.

> The tests create objects and delete them again, each run inside its own OU
> `samadcon-test-<random>`. Run them against a test domain only.

If the connection does not come up, the CLI inside the container answers why — without
credentials:

```bash
docker run --rm samadcon:test samadconctl probe 192.168.1.10
```

And with a sign-in, all the way to the rootDSE:

```bash
docker run --rm samadcon:test samadconctl check --server 192.168.1.10 --insecure
```

## Milestones

| # | Scope | Status |
|---|---|---|
| 1 | Foundation, auth, users/groups/computers/OUs (the ADUC replacement) | done, verified against a real domain |
| 2 | DNS, Sites & Services, diagnostics (FSMO, replication, password policies) | done, verified against a real domain |
| 3 | GPMC basics: GPOs, links, filtering, backup/restore, report | done, verified against a real domain |
| 4 | Group policy editor: ADMX → security settings → Linux/VGP → preferences → scripts/folder redirection | complete; each of the five parts proven **applied** on a real client (4c through `samba-gpupdate --rsop`), preferences in all three waves. [What of that proof is in this repository](#the-policy-editor) — and what is not |
| 5 | Reports: findings about the domain and its policies, and a printable report | done; the [rules](#reports) run against a real domain, and each finding carries the values it was decided from |

Milestone 1 covers: Kerberos sessions, tree navigation, object lists and search (ANR), users
(create, edit, account options, password reset, unlock, expiry), groups (scope/type, members
including nested and primary), computers (including reading LAPS and resetting the account), OUs
(including deletion protection), move/rename/delete, the attribute editor, the ACL and delegation
editor, the audit log and the German/English interface.

The DNS part of milestone 2 works over LDAP rather than through the DCE/RPC interface
(`samba-tool dns`): zones from all three partitions — domain, forest and the old storage under
`CN=System` — records of types A, AAAA, CNAME, NS, PTR, MX, SRV and TXT to create, change and
delete, plus creating and deleting zones. A name in AD is **one** object holding all its records
in a multi-valued attribute; SAMADCON still shows one row per record and finds the one to change
by its current values. If the record no longer matches, somebody else changed it — the edit is
then refused rather than guessed at. Every change raises the zone's SOA serial and stamps the
written record with it, the way Samba does on its own write path; otherwise a secondary name
server would never learn that there is something to fetch.

**Sites and services** covers sites, subnets, site links and the servers per site: create, rename,
describe, delete, assign a subnet to a site or detach it, cost and replication interval of the
links, and moving domain controllers between sites. Replication connections are shown only — the
KCC builds those itself, and whatever is changed there by hand it undoes on its next run. Sites
live in the configuration partition and therefore apply forest-wide; deleting a site is refused
while a DC or a subnet still points at it.

**Group policy** is the first part that no longer runs over LDAP alone: a GPO is a directory
object *and* a directory tree on the SYSVOL share, and nothing enforces that the two agree.
SAMADCON creates them in the order `samba-tool gpo create` uses — object, files, then the SYSVOL
rights derived from the object — and rolls the earlier steps back on failure. Along with links
carrying order, enforcement and inheritance blocking, security filtering, and a consistency report
GPMC does not have: when the version in `GPT.INI` differs from `versionNumber`, clients either
never re-read the policy or re-read it at every sign-in — and nothing else tells you.

Create, copy, back up, restore and delete are all in the interface. Deleting asks first and is
refused while links still point at the policy — those live on the containers and have to be
removed there, which is how every console handles it.

When the container is pointed at an **IP address** through `SAMADCON_DC_HOSTS`, SAMADCON asks the
DC for its own name before signing in and connects through that by preference. This is not
cosmetic: Kerberos issues tickets for `ldap/<hostname>@REALM`, and for a bare address no such
principal exists. Without this step the sign-in fails at the bind, with
`NT_STATUS_INVALID_PARAMETER` and no hint about the name.

### The policy editor

**Administrative templates** (4a) are read from the central store on SYSVOL — `.admx` with the
matching `.adml`, parsed once per domain and cached — and the input forms are generated from them.
On write, Samba's `RegistryGroupPolicies` handles `Registry.pol`, `GPT.INI` and `versionNumber`;
SAMADCON contributes the two things it does not do: registering the client-side extension in
`gPCMachineExtensionNames`, and the ordering that attribute requires. A policy whose values are
written but whose CSE is not listed is read by nobody — visible in every console, applied
nowhere, with no error anywhere.

Proof is not the file's contents but the client: `gpresult /h` on a domain-joined Windows 11 lists
the policy under *Applied GPOs* with *Extensions Configured: Registry* and *Revision: AD (9),
SYSVOL (9)*, reports the registry CSE under *Component Status* as **Success**, and shows the
setting under *Administrative Templates* as **Enabled**. Formally correct files are not the same
thing as applied policies — that is the difference only this test sees.

**What of that is in this repository, and what is not.** The reference files GPMC produced are:
`backend/tests/data/` holds `fdeploy1.ini`, `scripts.ini` and `GptTmpl.inf`, and the unit tests
read them rather than a transcription of them. Their domain names, host names and SIDs were
replaced with example ones before publication, which is stated in
[`backend/tests/data/PROVENANCE.md`](backend/tests/data/PROVENANCE.md) along with what that
costs: a byte count no longer proves a file is what GPMC wrote.

The `gpresult` and `samba-gpupdate --rsop` reports are **not** here. Sanitising one is a great
deal harder than sanitising an INI file — a `gpresult` report carries the entire applied policy
set of a real machine. So that half of the proof rests on this description of it, and anyone who
wants it first-hand can reproduce it: create the policy in SAMADCON, run `gpresult /h` on a
joined client, and compare.

Two format details, cross-checked against a policy GPMC produced rather than derived from the
specification: an "off" that ADMX expresses as `<delete/>` writes a **real entry** `**del.<name>`
(REG_SZ, a single space) — the marker tells the client to throw away the value it may already
have. And in `versionNumber` the **computer version sits in the low word**, the user version in
the high one.

The policy tree follows the **interface language**: in German SAMADCON reads the strings from
`de-DE`, in English from `en-US`. The definitions themselves contain not one visible string —
every name in the tree comes from a language directory, which is why that is the whole
translation. If the wanted directory is missing, the server takes the same language from another
region, otherwise English — and **says so**: the editor then shows which language was actually
used and that the matching language pack is absent. A tree without labels would be the worse
answer; a silent fallback the more confusing one.

Setting a policy to *Enabled* fills empty inputs with the template's default values, the way GPMC
does. That is not cosmetic: whoever writes `defaultValue` means *that value*, and an empty field
writes nothing at all. Otherwise you enable a policy whose options stay unset, and the difference
only surfaces when a client behaves other than expected. Values already set are left alone.

**Importing templates.** *Import templates…* in the editor's bar takes the package the way an
administrator has it: Microsoft's MSI as it was downloaded (*Administrative Templates (.admx) for
Windows 11 …*), a ZIP of the `PolicyDefinitions` folder, or that folder picked directly. All three
end up in the same shape — the folder holding the `.admx` files becomes the store's root, and
`de-de` becomes `de-DE`, the way Windows spells it. The MSI is opened with `msiextract` from
msitools, which is in the image; the MSI's own tables name the files, so they come out under
their real names rather than the cabinet's internal keys.

The languages are chosen, German and English by default. The Windows 11 package carries 22 of
them and 97 MB; two are about 12, and SYSVOL is replicated to every domain controller. English
earns its place beyond itself: it is what a template falls back to when its translation is
missing, and the German set lacks one (`SecureBoot.adml`). Templates already in the store are
skipped by default, or replaced when asked — a newer Windows release imported over an older one
is the case this is for, and it was impossible while the only choice was to refuse the lot.

Measured on the Windows 11 25H2 package, v2.0: 5,284 files, 233 templates, 3,628 policies, every
file accepted. That last part needed a fix. Microsoft writes `Search.admx` in UTF-16 and declares
it `encoding='unicode'` — a name Windows reads and Python's codec registry does not have. Every
import of the package failed on that one file, with a server error rather than a message, since
the exception was not the parse error the check expected; and a store copied over from a Windows
DC silently lacked the file's 50 policies. Only that spelling is honoured, and only with the
byte-order mark that makes it unambiguous — guessing at an encoding is how a template ends up
with text nobody wrote.

Imported templates are validated **before** anything is written, so a malformed package lands
not at all: Windows reads the central store as one, and a single unreadable file makes it abandon
**every** administrative template in the domain — the group policy report then shows one parser
error domain-wide instead of the settings. So what is checked is what makes that difference:
well-formed XML, the right root element, the often-forgotten `<resources>`, for an `.admx` its own
namespace, and for an `.adml` the header the schema demands, `<displayName>` and `<description>`
before `<resources>`. Without the last, Windows reports *"Expected `<displayName>`, but found
`<resources>`"* — an error pointing at the element that is there instead of the one that is not.

A Windows client that has read the central store holds the templates open with a lease that
refuses writes, long after the policy refresh. An upload then runs into `file_in_use`, and the
usual workaround of deleting instead of overwriting does not help, because the lease refuses
deletion too. Visible with `smbstatus --locks` on the DC; the lease clears by itself, and
`smbcontrol smbd close-share sysvol` or a restart of `samba-ad-dc` ends it at once. Checking
first cannot stop a lease from cutting an import short half way; the error then lists what had
already been written.

**Security settings** (4b) live in `GptTmpl.inf`, an INI in UTF-16LE with a BOM: password and
lockout policy, Kerberos policy, the audit categories, user rights assignment and restricted
groups. Three details are copied from a file GPMC wrote rather than reasoned out, and each
contradicts one of the *other* policy formats this project writes — which is the whole argument
for reading a real file first. There is no preamble, where `scripts.ini` opens with a blank line.
Empty sections are written out, where `scripts.ini` omits them. And spaces surround the equals
sign everywhere except in `[Unicode]` and `[Version]`.

**Samba's own policies** (4c) are the ones `samba-gpupdate` applies on Linux domain members: sudo
rights, symbolic links, motd and issue, OpenSSH settings and host access control. Windows clients
ignore them entirely, so the proof for them runs through `samba-gpupdate --rsop` on a member
rather than through a `gpresult` report. No client-side extension is registered for them, and that
is deliberate: `samba-tool gpo manage` registers none either, and `samba-gpupdate` runs every
loaded extension against every applicable policy regardless.

**Preferences** (4d) cover ten types across three waves: drive maps, registry values, files,
folders, shortcuts, environment variables, printers, local users and groups, services and
scheduled tasks. Every type has its **own** CSE GUID, so each was proven applied separately — one
proof does not carry another. Two things the reference files contradicted outright: there is no
shared preferences tool GUID, every type brings its own; and every type registers **two** groups,
its own pair plus one in a shared `{00000000-…}` group that Windows calls *Group Policy
Infrastructure*.

Scheduled tasks are read, edited and removed but **not created** here. A task in the V2 format
carries a whole tree — registration info, principals, triggers, actions and eighteen settings —
and writing one from scratch without a reference for each part is exactly the guess this project
does not make. An existing task is preserved in full and stays editable.

An item's **item-level targeting** is displayed and left alone. Sending it back with every save
would mean a rename could drop the filter that decides who a drive is mapped for — silently, and
in the permissive direction. A stored password (`cpassword`, encrypted with a key Microsoft
published in 2014) is carried through where it exists and can never be introduced from here.

**Scripts** (4e) live in `scripts.ini` and `psscripts.ini` per half, **UTF-16LE with a BOM and
CRLF**. Saved as UTF-8 the client reads mojibake and runs nothing — without a word. Within a
section the entries are numbered pairs, and the numbers *are* the execution order: they must start
at zero without gaps, because Windows stops at the first missing index. Reordering, deleting and
adding are therefore the same operation — SAMADCON always writes an event's whole list.

Two details come from a file GPMC produced rather than from the specification, and both would
otherwise look in every diff like a change nobody made: between the BOM and the first section
there is a **blank line**, and an event without scripts gets **no section at all**, not an empty
one. The unit test for it compares our output with that file byte for byte.

When the last script of a half is removed, SAMADCON unregisters the client-side extension. Left
behind, every client would fetch the policy on every refresh and find nothing in it.

**Folder redirection** (also 4e) writes `User/Documents & Settings/fdeploy1.ini`, and its format
disagrees with every other one here: the file opens with a blank line, five spaces and another
blank line; the version section is spelled `[version]` in lower case; and an empty value is
written as `Key =` with no trailing space. Each of those was read off a GPMC file, and each was
wrong in the first attempt.

**Windows hides its policy files.** `scripts.ini`, `fdeploy1.ini` and `fdeploy.ini` carry the DOS
attribute `HIDDEN`, and `fdeploy.ini` `READONLY` as well. That has two consequences, neither of
which looks like what it is.

A directory listing has to **ask explicitly for hidden and system entries** — otherwise exactly
these files are missing without anything failing. The settings report then showed a policy as
emptier than it is. SAMADCON passes the same mask as Samba's own `ntacls` and `gpo` tools.

And `savefile()` opens for overwrite with normal attributes, which SMB **refuses with
`ACCESS_DENIED`** on a hidden file — a message that invites you to inspect ACLs that are perfectly
fine. SAMADCON opens with `FILE_OVERWRITE_IF` instead and names the attributes the file already
has; the disposition truncates by itself. No `truncate`: in the Python bindings that is an SMB1
call and fails against an SMB3 connection with `NT_STATUS_REVISION_MISMATCH`. If that fails too,
the file is replaced — which costs the attributes and is logged as a warning, because an editor
that cannot edit a GPMC-created policy at all is the worse outcome.

Both were found only against a real policy GPMC had produced. The integration tests create their
own GPOs, and those files have ordinary attributes — they check SAMADCON against SAMADCON. The
write paths are therefore additionally covered by unit tests, with a stand-in instead of a domain
controller.

The SMB connection needs an **s3 LoadParm** (`samba.samba3.param`), not the one from
`samba.param` that SamDB takes. With the wrong one `libsmb` answers `NT_STATUS_INVALID_PARAMETER_MIX`
without naming the parameter. `samadconctl sysvol` exercises that path on its own.

The **backup** is a ZIP holding the SYSVOL tree and the two `.SAMBAEXT` files under Samba's own
names. Unpacked, `samba-tool gpo restore` accepts the archive — cross-checked, not assumed. An
empty `.SAMBAEXT` file is not written: LDB refuses an attribute without a value, and an archive
containing one could not be restored with `samba-tool` at all.

Of the editor tree GPMC shows, four branches are deliberately left out: *Software installation*,
*Name Resolution Policy*, *Deployed Printers* and *Policy-based QoS*. They will be added when they
are actually needed. One small deviation inside what is built: the GPMC node *All Settings*, which
lists everything flat, does not exist — search leads there instead.

The settings report shows every policy with what is on SYSVOL. That the **Default Domain Policy of
a Samba domain looks empty there is correct**: Samba creates it with empty `MACHINE` and `USER`
folders and writes no `GptTmpl.inf`. The password policy sits on the domain object in the
directory — that is where diagnostics reads it, and where `samba-tool domain passwordsettings`
edits it. In a domain grown out of Windows the same policy holds a security template instead.

**Diagnostics** is read-only throughout: domain controllers with site and GC flag, the seven FSMO
roles and their holders, functional levels, the connected DC's replication state from `repsFrom`,
the password and lockout policy including fine-grained policies (PSOs), and locked, disabled and
expired accounts. Seizing a role or forcing replication is deliberately not part of it — that is
what `samba-tool fsmo seize` and `samba-tool drs replicate` on the DC are for.

### Reports

Rules over values SAMADCON reads itself, in
`core/findings.py`. Each finding carries the values it was decided from, so it
can be argued with rather than believed: "the minimum password length is 6,
measured against 8" is checkable, "the password policy is weak" is not.

**Nothing here runs on its own and nothing is asked of a language model.** The
console reads when you open something and writes when you press a button, and
that is the whole of it. There was an optional model that could word the
findings; it was read-only and marked as unverified, and it is gone — a console
that manages a domain is not the place for it. Automation, and anything asked
of a model, belong in a separate application with its own address and its own
account.

The policy rules look for the failure group policy is famous for and no console
reports: **a policy that reaches nobody looks exactly like one that works.** Its
settings are there, its versions are there, its links are there, and nothing
happens — because no client-side extension is registered, or every link is
disabled, or the half holding the settings is switched off. `gpo_linked_but_empty`
fires on real domains, not only constructed ones. A thorough pass walks each
policy's files on SYSVOL as well; it is a switch and not the default, because it
costs one round trip per policy.

Two rules are **deliberately absent**, and tests keep them absent: forcing
passwords to expire, which NIST withdrew because scheduled changes push people
towards predictable variations of one password; and listing locked or disabled
accounts, which diagnostics already shows and which would bury the findings that
need a decision.

**Both reports print.** There is no PDF library in the image — the browser
already writes PDFs with selectable text, and the dependency list is short on
purpose. The document carries the values and not only the findings, since
whoever is holding a printout cannot go and look. The print stylesheet forces
black on white: a reader in dark mode would otherwise print pale grey onto white
paper.

## Layout

```
backend/samadcon/     the FastAPI application
  core/               executor (one worker thread per session), audit, error translation, rate limit
  auth/               Kerberos TGT, krb5.conf for several realms, sessions, CSRF
  ad/                 LDAP access: connection targets, server probe, directory, ACLs
  gpo/                GPC/SYSVOL, ADMX, Registry.pol, security INF, preferences, VGP
  api/v1/             HTTP routers
frontend/src/         React + TypeScript, an MMC-like layout
frontend/public/      favicon
frontend/src/assets/  lockup and mark, light and dark, plus a monochrome one
docker/               Dockerfile, entrypoint, nginx, supervisord
docs/brand/           lockup, mark and favicon for use elsewhere; the interface has its own
```

The Samba Python libraries are blocking and not thread-safe. Every Samba call therefore goes
through `samadcon/core/executor.py` — a thread pool with a lock per session — and never directly
from a router.

## Technical foundation

The GPO part builds on existing Samba pieces rather than reimplementations:

- `samba.policies.RegistryGroupPolicies` — writes Registry.pol, keeps GPT.INI and the LDAP
  `versionNumber` in step, and registers CSE GUIDs.
- `samba.dcerpc.preg` + `ndr_pack`/`ndr_unpack` — the PReg format for the special cases.
- `samba.gp_parse.*` — parsers for GptTmpl.inf, scripts.ini, \*.pol.
- `samba.netcmd.gpo` — the reference for GPO creation including `dsacl2fsacl()` (SYSVOL ACLs).

## Development

The backend locally — needs `python3-samba` from the distribution:

```bash
python3 -m venv --system-site-packages .venv && .venv/bin/pip install -e "backend[dev]"
```

Tests without a DC — these run without `python3-samba` and without a container:

```bash
.venv/bin/pytest backend/tests/unit -q
```

### Raising the version

It is written in **one** place, `backend/samadcon/__init__.py`. `pyproject.toml`
declares `dynamic = ["version"]` and reads the attribute from there, so the two
cannot disagree. Everything that names a version to anyone — `/api/v1/health`,
the sign-in screen, `samadconctl --version`, the OpenAPI description — reads it
through that module.

`frontend/package.json` has to carry one too, because npm requires the field.
Nothing reads it at runtime, which is exactly why it drifts, so it is checked
rather than remembered:

```bash
python scripts/check_versions.py
```

The lint job runs it on every push, and on a tag build it compares against the
tag as well. That last part catches what no single-source arrangement can: a
tag pushed without the version being raised at all.

This exists because v0.5.2 shipped reporting itself as 0.5.1 — three files
carried the number, a release raised two of them, and a reader found it rather
than the project.

The release notes are written into the annotated tag, and `CHANGELOG.md` is
generated from them rather than kept alongside them:

```bash
python scripts/build_changelog.py
```

Run it once the tag exists and commit the result. It rewrites the file from the
tags every time, so anything typed straight into the changelog is lost — which
is the point. One source, and it is the tag.

## Licence

AGPL-3.0-or-later.

The console names it and links back here from its own interface — top right while signed in,
and at the foot of the sign-in card. That is not decoration: section 13 obliges anyone who
modifies SAMADCON and offers it over a network to offer its source to the people using it, and
a console that never says where it came from makes that impossible to keep. If you fork it,
point the link at your fork rather than removing it.

The Samba python bindings this is built on (`samba.samdb`, `samba.dcerpc`, `samba.ndr` and the
rest) are GPL-3.0-or-later, and `ldb` is LGPL-3.0-or-later. AGPLv3 and GPLv3 permit that
combination explicitly, each in its own section 13.

The icons are Phosphor Icons, MIT, embedded as path data rather than loaded
as files — see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
