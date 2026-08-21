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

> Status: under development. What is built is listed under [Milestones](#milestones).

## Why

RSAT requires a domain-joined Windows client. In a pure Linux environment it is simply not
available, and `samba-tool`, being a command-line tool, covers only part of the daily work.

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
- **recently used** servers, kept in the browser only, never credentials,
- the container's **default domain**, if one is configured.

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

### Running the published image

Every push to the default branch builds an image and pushes it to the GitHub container registry.
Nothing has to be cloned or built:

```bash
docker pull ghcr.io/onlinecrash24/samadcon:latest
```

A `docker-compose.yml` for that image, complete as it stands — put it in an empty directory:

```yaml
services:
  samadcon:
    # `latest` follows the default branch. Pin `sha-<short>` for anything that
    # matters — see "Which tag" below.
    image: ghcr.io/onlinecrash24/samadcon:latest
    # A fixed name, so `docker logs samadcon` and `docker exec samadcon …`
    # work without looking up what compose generated.
    container_name: samadcon
    # Comes back after a host reboot, stays down when you stopped it yourself.
    restart: unless-stopped

    environment:
      # The name the console is reached under. It becomes the CN and the SAN of
      # the self-signed certificate and the target of the HTTP-to-HTTPS
      # redirect — the one value practically every installation must change.
      SAMADCON_PUBLIC_HOST: "samadcon.example.lan"
      # Must name the port the host publishes, not the one nginx listens on.
      # They differ as soon as a proxy or a port mapping sits in between, and
      # the redirect then points somewhere nobody can reach.
      SAMADCON_PUBLIC_HTTPS_PORT: "8443"
      # The reverse proxy in front of this container, if there is one. Only an
      # address named here is believed about who the caller is — see
      # "Behind a reverse proxy" below. Empty means no proxy.
      SAMADCON_TRUSTED_PROXIES: ""

      # Both may stay empty: the sign-in form then asks for a server address.
      # When set, use names that resolve — Kerberos needs the DC's own FQDN,
      # and a bare IP fails with NT_STATUS_INVALID_PARAMETER.
      SAMADCON_REALM: ""
      SAMADCON_DC_HOSTS: ""

      # INFO names what happens; DEBUG is for tracking a problem down and not
      # for running. Writes are recorded separately in the audit log either
      # way — that does not depend on this.
      SAMADCON_LOG_LEVEL: "INFO"

      # The KI-Manager's model service. Empty means off — nothing is sent
      # anywhere and the reports show only what the rules found. The address
      # belongs here and not in the interface: the container makes the call,
      # so an address a user could type would reach hosts their browser
      # cannot. From in here, localhost is this container — name the Ollama
      # host's own address:
      #
      #   SAMADCON_OLLAMA_URL: "http://192.168.1.20:11434"
      #
      SAMADCON_OLLAMA_URL: ""

    ports:
      # Loopback. Docker publishes on every interface of the host when no
      # address is given, and this is a sign-in form that issues Kerberos
      # tickets for the domain. Reaching it from another machine is a
      # decision — make it here, by naming the address it should answer on:
      #
      #   - "0.0.0.0:8443:8443"
      #
      - "127.0.0.1:8443:8443"
      # HTTP, and it serves exactly two things: a redirect to HTTPS and the
      # health check. Nothing is answered here that could be worth reading.
      - "127.0.0.1:8080:8080"

    # How the container reaches the domain. With SAMADCON_DC_HOSTS naming the
    # controllers, nothing here is needed. Left empty, SAMADCON finds a DC
    # through SRV records — and that needs a resolver which serves the domain,
    # which in practice is the DC itself. Without one, signing in fails with
    # NT_STATUS_NO_LOGON_SERVERS and nothing on the way there says why:
    #
    #   dns: ["192.168.1.10"]
    #   dns_search: ["example.lan"]
    #
    # Kerberos also has to resolve the DC's own FQDN. Where DNS does not give
    # it, name it directly — this provides an address and no SRV records, so
    # it complements `dns:` rather than replacing it:
    #
    #   extra_hosts: ["dc1.example.lan:192.168.1.10"]

    volumes:
      # A real certificate goes here as server.crt and server.key. Without one
      # the container generates a self-signed certificate on first start. The
      # container runs as uid 1000 and a bind mount belongs to root, so this
      # directory has to be writable for it — see below.
      - ./tls:/etc/samadcon/tls
      # CA bundles for validating the DCs' LDAPS certificates. Read-only: the
      # container has no business changing what it validates against.
      - ./ca:/etc/samadcon/ca:ro
      # Samba's cache and lock directory. Losing it costs nothing but a little
      # speed; it is a volume so the container does not write into its own
      # image layer.
      - samadcon-cache:/var/cache/samadcon
      # The samadcon user's home, and Samba's private and state directory.
      # Also where a generated certificate lands if ./tls is not writable —
      # which is why losing this one means a new self-signed certificate.
      - samadcon-data:/var/lib/samadcon
      # The audit trail should outlive the container. Who did what, to which
      # DN, with which attribute changed — the record you need when someone
      # asks months later.
      - samadcon-logs:/var/log/samadcon

    # Kerberos credential caches live in /dev/shm and must never hit a disk.
    shm_size: 64m
    tmpfs:
      # uid/gid are required: a tmpfs mount belongs to root by default, and
      # nginx and supervisor run as uid 1000.
      - /run/samadcon:mode=0700,uid=1000,gid=1000,size=8m

    # Nothing in here needs to become more privileged than it starts, and
    # setuid binaries are the usual way that happens.
    security_opt:
      - no-new-privileges:true
    # No capability at all. nginx listens on 8443, above the privileged range,
    # so not even NET_BIND_SERVICE is wanted.
    cap_drop:
      - ALL

# Named volumes, so docker keeps them where it keeps such things and they
# survive `docker compose down`. Only `docker compose down -v` removes them.
volumes:
  samadcon-cache:
  samadcon-data:
  samadcon-logs:
```

The container runs as uid 1000 and a bind mount belongs to root, so the certificate directory has
to be writable for it. Without this the entrypoint falls back to a volume with a warning, and the
certificate is not where anyone looks for it:

```bash
mkdir -p tls ca && sudo chown -R 1000:1000 tls
docker compose up -d
```

**Which tag.** `latest` follows the default branch, `DEV` names it explicitly, and every build
also carries `sha-<short>`. For anything that matters, pin the `sha-` tag: `latest` moves under
you on the next push.

### Behind a reverse proxy

The ports above bind to loopback, which is what most installations want: a proxy on the same
host terminates TLS and forwards to `127.0.0.1:8443`. To reach the console directly from other
machines instead, name the address in the `ports` lines — `0.0.0.0:8443:8443`, or better the
one address it should answer on. (The `docker-compose.yml` in this repository reads it from
`SAMADCON_BIND`, so there one `SAMADCON_BIND=0.0.0.0` does the same job.)

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

### Building from source

```bash
git clone https://github.com/onlinecrash24/SAMADCON.git
cd SAMADCON
docker compose up -d --build
```

No `.env` is needed — the whole configuration lives in `docker-compose.yml`. With no domain
configured, the sign-in form asks for a server address and works the rest out itself.

The interface then runs on `https://<host>:8443`. Without a mounted certificate the container
generates a self-signed one on first start.

## Deployment

### What has to be on the target system

```
SAMADCON/
├── docker-compose.yml          the whole configuration
├── .dockerignore               keeps node_modules and local secrets out of the image
├── docker/
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

`backend/tests/` is only needed when building with `SAMADCON_TARGET=test`.

Do not copy along: `frontend/node_modules`, `frontend/dist`, `backend/samadcon.egg-info`, any
`__pycache__`, `.venv`. The `.dockerignore` catches those and at the same time keeps certificates
and any local `.env` out of the image — configuration arrives at runtime, never in a layer.

`docker/tls/`, `docker/ca/` and `docker/servers/` appear on first start.

None of this is needed when running the published image: it carries everything.

### What has to be configured

**No `.env`.** Everything is in `docker-compose.yml` with the value it should have — no second
place to keep in step, and nothing that quietly falls back to an empty string because a variable
was not exported.

| Setting | What for |
|---|---|
| `SAMADCON_PUBLIC_HOST` | The name the console is reached under. It becomes the CN and the SAN of the self-signed certificate and the target of the HTTPS redirect. **The one value practically every installation must change.** |
| `SAMADCON_REALM`, `SAMADCON_DC_HOSTS` | Pre-fills the sign-in form. **Names that resolve, not bare IP addresses** — Kerberos needs the DC's FQDN. |
| `SAMADCON_LDAP_CA_FILE` | The DC's CA, when the LDAPS certificate is to be validated. |
| `SAMADCON_TRUSTED_PROXIES` | The reverse proxy in front of the container, if there is one. Without it every audit entry records the proxy instead of the administrator — see [Behind a reverse proxy](#behind-a-reverse-proxy). Empty when there is none. |

What belongs to the machine rather than to the project stays as `${VAR:-default}` and comes from
the shell: the ports, if 8443 or 8080 are taken; `SAMADCON_BIND`, which is `127.0.0.1` unless the
console should answer on another address; `SAMADCON_TARGET=test` for the test image; and the
`TEST_*` values of the integration tests. **A password never belongs in the compose file** —
that file is in version control.

### Steps

Adjust `docker-compose.yml`, at least `SAMADCON_PUBLIC_HOST`. Then:

```bash
docker compose up -d --build
```

For a real certificate put `server.crt` and `server.key` into `docker/tls/`. One catch: the
container runs as uid 1000 and a bind mount from the host belongs to root. If `docker/tls/` is not
writable, the entrypoint falls back to the `samadcon-data` volume with a warning — the certificate
is then not where you look for it. So, once:

```bash
mkdir -p docker/tls docker/ca && chown -R 1000:1000 docker/tls
```

Check:

```bash
docker compose ps
```

The container has a health check on `/api/v1/health` and reports `healthy` after about twenty
seconds. If it does not, `docker compose logs samadcon` says why. The connection to the DC can be
checked without credentials:

```bash
docker compose exec samadcon samadconctl probe dc1.example.lan
```

Updating is the same command as installing. The volumes `samadcon-cache`, `samadcon-data` and
`samadcon-logs` — the audit trail lives in the last one — survive it:

```bash
docker compose up -d --build
```

## Testing against an existing Samba AD

The credentials come from the shell, not from a file — a domain administrator's password has no
business in a file that can be backed up by accident.

Unit tests need no domain and run anywhere. Three of them compare against files GPMC itself
produced, kept in `backend/tests/data/` with a note on
[where they came from](backend/tests/data/PROVENANCE.md) and what was changed to publish them.

The tests live in the image rather than in a mount, which is what the `test` build target is for:

```bash
SAMADCON_TARGET=test docker compose up -d --build
```

Integration tests against that domain:

```bash
TEST_DC_HOST=dc1.example.lan TEST_ADMIN_PASSWORD=... docker compose exec samadcon python -m pytest tests/integration -q
```

> A changed test is copied into the image at build time. After every change to the tests, run
> `up -d --build` first, then `exec`.

> The tests create objects and delete them again, each run inside its own OU
> `samadcon-test-<random>`. Run them against a test domain only.

If the connection does not come up, the CLI inside the container answers why — without
credentials:

```bash
docker compose exec samadcon samadconctl probe 192.168.1.10
```

And with a sign-in, all the way to the rootDSE:

```bash
docker compose exec samadcon samadconctl check --server 192.168.1.10 --insecure
```

## Milestones

| # | Scope | Status |
|---|---|---|
| 1 | Foundation, auth, users/groups/computers/OUs (the ADUC replacement) | done, verified against a real domain |
| 2 | DNS, Sites & Services, diagnostics (FSMO, replication, password policies) | done, verified against a real domain |
| 3 | GPMC basics: GPOs, links, filtering, backup/restore, report | done, verified against a real domain |
| 4 | Group policy editor: ADMX → security settings → Linux/VGP → preferences → scripts/folder redirection | complete; each of the five parts proven **applied** on a real client (4c through `samba-gpupdate --rsop`), preferences in all three waves. [What of that proof is in this repository](#the-policy-editor) — and what is not |
| 5 | KI-Manager: findings about the domain and its policies, a printable report, optionally written up by a model | done; the rules run against a real domain, the model half is [optional and marked as unverified](#the-ki-manager) |

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

Uploaded templates are validated **before** anything is written, and a package lands whole or not
at all: Windows reads the central store as one, and a single unreadable file makes it abandon
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
`smbcontrol smbd close-share sysvol` or a restart of `samba-ad-dc` ends it at once.

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

### The KI-Manager

Two reports, and the line between them is the point of the thing.

**The binding half** is rules over values SAMADCON reads itself, in
`core/findings.py`. Each finding carries the values it was decided from, so it
can be argued with rather than believed: "the minimum password length is 6,
measured against 8" is checkable, "the password policy is weak" is not. No
model is involved and none is needed.

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

**The unverified half** is optional and off unless `SAMADCON_OLLAMA_URL` names a
model service. It orders the findings and puts them in plain language; it may
not contradict one, invent one, or restate its severity. What would be sent can
be looked at before it goes — the exact prompt, from the same function that
builds the request, because domain configuration leaving for another service is
a decision and a decision needs the thing itself rather than a description of
it. The answer appears in a frame that names the model and says nothing in it
was checked.

The address comes from the deployment and never from a request: the container
makes the call, so an address a user could type would let any signed-in account
reach hosts its own browser cannot. The model *name* comes from the interface,
because a name is not an address.

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
docs/brand/           banner variants, not used by the interface
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

## Licence

AGPL-3.0-or-later.
