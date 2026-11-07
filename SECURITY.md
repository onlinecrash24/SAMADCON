# Security Policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting:
**[Report a vulnerability](https://github.com/onlinecrash24/SAMADCON/security/advisories/new)**
(Security tab → Report a vulnerability). It is private to you and the
maintainer, and it keeps the report, the discussion and the eventual advisory
in one place.

If you would rather not use GitHub, email **webmaster@onlinecrash24.de** with
`SAMADCON` in the subject. Either way, please do not open a public issue for
anything exploitable.

Useful to include, as far as you have it: the version (top right in the
console, and at the foot of the sign-in card), what an attacker would need to
already have — an account, a delegated right in the directory, network access
to the container — and the smallest reproduction you can manage.

This is a single-maintainer project, so the honest expectation is a reply
within a few days rather than a same-day acknowledgement, and a fix in the next
release rather than an out-of-band one. You will be credited in the release
notes unless you would rather not be.

## Supported versions

Only the latest release. There are no backports and no security-only branches:
if a fix ships, it ships in the next tag. Images are published to
`ghcr.io/onlinecrash24/samadcon`; `:latest` follows the most recent release,
and `:0.6` the most recent 0.6.x.

## What SAMADCON holds, on purpose

Read this before deciding whether something is a vulnerability.

- **No account of its own.** There is no service account, no keytab and no
  stored password. Every administrator signs in with their own AD account;
  SAMADCON obtains a Kerberos ticket into a per-session credential cache on
  tmpfs and runs every LDAP and SMB operation with it. The password is used
  for that and nothing else, and is never stored or logged.
- **So a session is as strong as the account behind it.** A signed-in Domain
  Admin can do in SAMADCON what they can do with `samba-tool` or ADUC. A
  logged-in user deleting an OU is the product working.
- **But what SAMADCON reads from the directory is data, not instruction.**
  Because it acts with the administrator's rights, anything it takes from an
  attribute that a less privileged account may write — a path, a name, a
  link — must not steer those rights somewhere else. A value that does is a
  finding (see v0.6.29: `gPCFileSysPath`).
- **Transport.** LDAP only with GSSAPI sealing, SMB only signed. LDAPS
  certificates are verified unless a profile says otherwise, and the console
  says so on every sign-in.
- **The container runs as an unprivileged user**, with all capabilities
  dropped and `no-new-privileges`; nginx terminates TLS in front of uvicorn.
- **Every write is in the audit log**: who, what, DN, attribute diff, and the
  identity provider's user when one is in front.
- **No telemetry, no phone-home, no auto-update.** SAMADCON makes no outbound
  HTTP requests.

## In scope

- Reaching an authenticated route, or a session, without signing in
- CSRF, XSS, or anything else that makes a signed-in browser act without intent
- Anything read from the directory or SYSVOL that redirects an administrator's
  write, delete or execute to another object or path
- LDAP filter injection, path traversal (SYSVOL, backup restore), injection
  into a generated configuration file (krb5.conf, smb.conf, nginx)
- Leaking passwords, tickets or other credentials into logs, the audit log,
  responses or files
- A guard the server claims and does not enforce (confirmations for
  privileged accounts, reserved names, protected OUs)
- Information given away before sign-in beyond what the form needs

## Not in scope

- **That a signed-in administrator can change the directory.** That is the
  feature; the directory's own permissions decide how far.
- **Reserved names and protected OUs as a security boundary.** They are a help
  inside SAMADCON, documented as such: the same administrator reaches those
  objects with `samba-tool` or ADUC.
- Anything that requires you to already hold an administrator's password, a
  valid ticket, a session cookie, or the container's volumes.
- Running the console on an untrusted network without a reverse proxy or
  identity provider in front, or with `SAMADCON_TRUSTED_PROXIES` set to
  everything.
- Denial of service by asking the console to do expensive work you are already
  authorised to ask for.

## Known and accepted

- **The supply chain is pinned by version, not by digest.** GitHub Actions
  are referenced by major tag and the base images by tag; Python packages
  are locked with hashes and npm packages through `package-lock.json`.
- **The HTTP API is internal.** It follows the console and is neither
  documented nor stable. `/api/docs` is off unless `SAMADCON_API_DOCS=1`.
