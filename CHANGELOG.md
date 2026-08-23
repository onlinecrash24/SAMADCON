# Changelog

Generated from the annotated git tags by `scripts/build_changelog.py` — the
tag is the source, this file is a copy of it. Do not edit it by hand; the next
release overwrites it.

Each entry is the release note as it was written at the time, unedited. Where
one says something was not verified, that sentence is part of the record and
stays.

Images for every version are on GHCR: `ghcr.io/onlinecrash24/samadcon:0.5.9`
pins one exactly, `:0.5` follows the minor series, `:latest` the newest
release.

---

## 0.5.9 — 2026-08-22

Two commits, and both of them are about saying out loud what the console
already knew.

**A link's two switches can be set where the tree reports them.** The policy
tree draws both states as badges; setting them meant opening the policy and
finding its Links tab. They are on the link's own menu now, beside removing it.

Both write at once and without asking, unlike removal. Each is one click to
undo, and each entry is named for what pressing it does rather than for the
state it is in — a menu has nowhere to put a tick, and "Enforced" with no mark
beside it says nothing about which way it would go.

The tree grew an error line with them. It had nowhere at all to report a write
that failed, and a switch that silently did not flip is worse than one that
says so.

Which answers a question that came with it: the badges are invisible in a
domain where every link is plain, because there is no badge for the ordinary
case. A row saying "enabled, not enforced" under every policy under every OU is
a column of noise. With these two entries the state can be produced, which is
also the way to see them.

**And the icons.** A set arrived that was made for this console — its
categories match, and one file is named after a tab that was renamed the same
day. Phosphor, regular weight, MIT, one path each on a 256 grid with
fill:currentColor, which is exactly the shape this already used.

The six console tabs had been sharing three icons: Users and Computers looked
like Diagnosis, DNS like Sites and Services, Group Policy like Reports. Half
the strip said nothing about which console you were in. Each has its own now.

That was working by accident. The tabs have always passed an icon *name* into a
prop that resolves an object *type*, and it drew anything at all only because
the three names they used happened to be spelled the same as three object
types. With six distinct names the coincidence runs out, so the lookup accepts
either — deliberately this time.

Managed service accounts stop looking like users, which is the one thing in the
set this console could not previously say.

Status and action icons are deliberately left out. Both are text today, and
text is more exact and better for a screen reader; an icon beside it would be
decoration.

MIT requires its notice to travel with every copy, which for icons compiled
into a bundle means a file in the repository. There was none, so
THIRD-PARTY-NOTICES.md is new, with the licence reproduced in full from the
source rather than from memory, and both READMEs point at it.

Also here: the policy list is a third tighter per row — 48px to 39px, measured
against the built stylesheet. It was using the roomy table while carrying a
GUID under every name, which is two lines of prose spacing for a line and a
label.

Not verified against a live domain: the machine this was built on can reach
neither a DC nor Docker, and the browser pane would not composite a frame, so
the icons were measured rather than looked at — sixteen paths, none malformed,
each filling between 63% and 98% of its grid.

---

## 0.5.8 — 2026-08-22

Group policy management stops being read-only-with-a-drag. Three commits, all
from one observation: the right-click menu worked in Users and Computers and
nowhere else.

**Half of that was an unfinished plan.** The policy tree was meant to offer
"link a policy here" from the start, and the reason is written in the file
itself: a drag cannot be performed from a keyboard, and the fallback it names
is two panes and a window away from the container you are looking at. It was
planned, not built, and not mentioned when the work was called done.

The dialog behind it already knew how to take several targets and report per
target. All it lacked was a way to be opened without a policy in hand, so it
now takes one or asks for one — and opened from a drop it never asks, because
the drop has already said which.

**The policy list had no action on a row at all.** Copying, renaming or
deleting meant opening the policy, doing the thing, and closing it again. Copy
and the delete confirmation lived inside the editor as local components, which
is precisely why the list could not reach them; they are shared now, so there
is one description of "are you sure you want to delete this policy" rather than
two that drift. Rename is new and deliberately not the directory rename dialog:
that one moves an object's RDN, while a policy keeps its GUID for life and
every link and every client refers to it by that. What changes is only what
people call it, and the dialog says so.

**And a link can be removed from the tree that draws it.** Right-clicking a
policy under a container used to open the container's menu, which offered to
link another one — the opposite of what someone aiming at a link wants. That
behaviour is right for a *drop*, where a row indented under its container is a
likely miss and the charitable reading is the container. A right-click is not a
miss. The link rows keep the drop handling and take a menu of their own.

Removing one needed something the tree did not carry: a link entry had a GUID
and no DN, and removal matches on the DN the gPLink attribute holds. That
string was already parsed on the way in and simply not passed on. Deriving it
from the policy object instead would have failed in exactly the case that
matters most — a link whose policy is gone has no object left to look one up
from, and removing it is the reason you are there. Two tests hold that,
including the orphan.

It asks first and names both facts that decide the answer, which policy and
where, because the same policy is usually linked in several places. The hint
adds the part that is easy to assume away: it takes effect at the next refresh
of the machines in scope, not at once.

Four surfaces have menus now — the object list, the directory tree, the policy
tree and the policy list — and every one of them answers Shift+F10 as well as
the mouse. DNS records and sites deliberately have none: they already carry
visible buttons on each row, so a menu there would duplicate what is on screen
rather than reach something that is not.

The enabled and enforced toggles on a link are deliberately absent. The tree
shows both as badges and the same menu is the obvious place for them, but they
are writes that change what applies to machines and nobody asked yet.

Not verified against a live domain: the machine this was built on can reach
neither a DC nor Docker.

---

## 0.5.7 — 2026-08-22

A short release, and an honest one: five of the six commits fix things the
previous release shipped broken, and the sixth removes a feature on the
strength of an argument rather than a defect.

**The model is gone.** A reviewer's position: a frontend should never be able
to perform automatic interactions, and a model belongs in a separate
application if anywhere. Two things turned up while acting on it.

The console labelled KI-Manager was not the model. It is the findings browser —
two dozen rules, each printed with the values it was decided from — the deep
pass over every policy's files on SYSVOL, and the whole printable domain
report. The model was one card at the bottom, inert unless an address was
configured. So the tab is renamed to what it is, **Berichte**, and keeps
everything computed.

And there was never a write path. The router used ad_read and never ad_write;
no tools field, no function calling, no loop. The answer was filtered
server-side against the findings it had been given, reached no audit and no
store, and was rendered as text. What left the container was the findings list,
not the values behind it — no SIDs, no user enumeration, no attributes. The
objection stands as a line worth drawing; it is worth recording that this
removed a capability nobody wanted rather than closed a hole.

httpx moved from the runtime dependencies into the dev extra rather than being
deleted with the client it existed for. Deleting it would have broken the
entire suite at collection, because TestClient is built on it and the extra
never listed it.

**And five defects, all from the window shell in 0.5.6, all of the same
family.** Each is a mechanism that suppresses or removes something running
earlier than the thing it was meant to leave alone — and not one of them is
visible to TypeScript or to a unit test. Every one was reproduced in a browser
against the built stylesheet before being fixed, and measured again after.

*The window buttons did nothing.* Minimise, maximise and close sit in the title
bar, and the title bar captures the pointer on press — so the release never
reached the button and no click was ever produced. They were inert from the
moment they were written.

*Every command in the right-click menu was dead to the mouse.* The menu
dismisses on a capture-phase pointerdown, and the guard against its own presses
was a React handler, which runs in the bubble phase — afterwards. The item was
gone before pointerup. Arrowing to it and pressing Enter always worked, which
is exactly why a keyboard check passed it.

*Hiding a window did nothing.* The hidden attribute carries its display:none
from the browser's own stylesheet, and a window is display:flex, so the author
rule won. Switching console left the policy editor standing in front of the
console just moved to, while the count on the tab correctly said it had been
put away. Minimising was broken the same way.

*A property sheet could not be scrolled*, and worse than reported: the content
grew to its full height, the window clipped it, and the close button went with
it. The same defect hid the close button in a window reporting a deleted
object — the one state where closing is all that is left.

*The Neu submenu opened at the edge of the screen* — thirteen visible pixels of
a hundred and ninety — because it inherits position:fixed, and on a fixed box
left:100% measures against the viewport. And a second dialog darkened the page
anyway: the rule that removes the tint was written immediately before the rule
it overrides, so with equal specificity it lost every time and never once
applied.

**The scrollbar and the form controls follow the theme now.** The page had
never declared a colour scheme, so the browser assumed light and painted
everything it draws itself that way — a white bar down a dark pane, and a white
date field in a dark property sheet. One declaration, both fixed.

Seventeen further claims from the same audit are still unverified and
deliberately untouched. Two of the three checked so far were only obvious once
measured, which is the argument for leaving the rest alone until each can be.

Not verified against a live domain: the machine this was built on can reach
neither a DC nor Docker. The dragging, the window buttons and the console
switch were confirmed against a real domain by the maintainer; the rest was
measured in a browser against the built stylesheet.

---

## 0.5.6 — 2026-08-22

The release that stopped being a web application about a directory and started
being the console people already know. A tester made the argument and it is
better than it first sounds: the RSAT dialogs are no clearer than ours, but
they are *known*, and in a tool this complicated familiarity does the work that
clarity would otherwise have to.

**The consoles are a tab strip.** They were roots of the left-hand tree, which
is MMC's arrangement — and it is not the one anybody arrives already knowing,
because in RSAT each console is a separate program with its own window and its
own tree. The navigation pane now shows one hierarchy and nothing else. Which
panes a console has is stated per console rather than asked as "is this the
directory?", a question that could not express what is true of three of them:
Sites, Diagnosis and the assistant have no tree at all and were being handed a
column to leave empty.

That uncovered a bug present since the two-pane modifier was written. It was a
second class on the same element, so it outranked the media queries on
`.console__panes` — for five of six consoles the 1100px layout never applied,
and at 720px the hidden tree still held its column. Measured in a browser
against the built stylesheet before and after.

**Pane boundaries can be dragged**, remembered per console. The width reaches
the grid as a custom property and never as an inline `grid-template-columns`,
which would beat every media query and quietly disable the narrow layouts the
first time anyone dragged anything. At 980px a pane told to be 460px wide still
lays out at 220px; at 1500px it is 460px. Resetting deletes the property, so
the default stays written down in one place.

**Rows have a right-click menu**, opened by Shift+F10 as well — without that it
is a shortcut for mice rather than an equivalent of the gesture, and the policy
tree already said in its own header that a drag needs a keyboard fallback.

The menu is not the interesting half. The detail pane's row of buttons was the
only place that knew what can be done to a computer, and a menu needs the same
answer; two hand-written lists drift apart the week after they are written,
with nothing failing anywhere. There is one function producing the list and
both surfaces read it, and the button row was moved onto it in the same commit
rather than later, because later is how the second list gets written.

**Property sheets are windows.** Several at once, dragged, resized, maximised,
listed in a taskbar scoped to the console that owns them. Every dialog used to
be a single nullable held by whichever pane was showing, so only one could
exist — and switching console destroyed it without a word.

The trap was found before anything was built on it. A window carries a
z-index, so it creates a stacking context, and a dialog rendered as its child
resolves `z-index: 50` *inside* that context: a confirmation opened from the
window behind paints underneath the window in front. Silently. Reproduced in a
browser, then disproved with the dialog portalled out — on top at every point
tested. Three defects that only appear with a second overlay went with it: one
Escape closed every open dialog, two backdrops compounded to 70% black, and
`aria-modal` was asserted while Tab walked out into the console behind.

**The policy tree GPMC draws.** Where each policy is linked, by place rather
than by policy, in precedence order. Drag a policy onto an OU to link it — it
asks first, adds rather than moves, and can take several targets at once, each
its own write and its own audit record so a failure partway through says which.

It shows only what a policy can actually be linked to. The classes that can
carry a gPLink had been written down in the group policy layer and used by
nothing; they now feed the search, the flag each node is handed, and the
expander probe, so a branch cannot promise children it will not show.
Containers that already carry a link keep their row, muted, because this is the
only view that reports links by location.

**A refresh returns to where you were** — console, container, selected object,
search, the policy container, the DNS zone, and the branches on the way to it.
Kept per browser tab rather than in the address bar: a hash would work equally
well and would put OU and account names into history and screenshots, and
nobody asked for shareable links. Signing in starts at Users and Computers,
which took a second commit: clearing the position on sign-out alone left it
outliving any session that merely lapsed.

**Three things a tester ran into**, all fixed here: a click beside the policy
editor no longer discards everything typed into it, an OU can be moved, and an
OU protected against deletion offers to lift the protection and delete in two
deliberate steps rather than refusing with no way forward.

**The advanced-objects switch** moved into the console it acts on — it had been
in the top bar, visible while someone was in DNS or Group Policy where it does
nothing — and the search now obeys it. It had hidden objects from browsing and
not from finding.

**The frontend has tests.** Fifty-six of them, in CI beside ruff and pytest,
covering the action list two screens share, both storage validators and the
overlay stack. Node environment only, and the config says why: in a stand-in
DOM every measurement reads zero, so the clamps and the edge-flip arithmetic
would be asserting against the stand-in. Those were checked in a real browser
instead.

One of those tests was decorative when written — it claimed to guard the comma
in the domain check and passed with the guard removed, because the example did
not end with the base string at all. Replaced, and confirmed red without the
fix.

Not verified against a live domain: the machine this was built on can reach
neither a DC nor Docker. Everything measurable was measured in a browser
against the built stylesheet; the rest is reported honestly as unverified.

---

## 0.5.5 — 2026-08-22

The release where several things the code had been carefully vague about
became measured, and two of them turned out the other way round.

**Folder redirection clears its registration.** KEEPS_REGISTRATION said
otherwise and said plainly why: nothing had established it, and treating an
unverified extension as kept costs only a finding while the reverse would flag
a healthy policy. Removing the last redirected folder in GPMC and reading the
attribute back gave a single space — the same empty marker scripts and
templates leave. A leftover redirection registration is now reported, and the
reconcile below offers to remove it.

**And clearing one leaves the file, not a marker.** A note had it that a
cleared redirection keeps its section with Flags=4. It does not: GPMC rewrites
fdeploy1.ini down to its preamble, 112 bytes, nothing after
[Folder_Redirection]. That file is checked in unmodified — the only reference
in the repository that needed no sanitising, since a cleared file holds no
domain name, no SID and no path. Our own renderer produces it byte for byte.

**Unix/Scripts/Startup is built.** It was held back because an entry carries a
hash of its script and guessing wrong means the script re-runs on every
refresh, or never. cmd_add_startup computes md5 of the script bytes, upper
case; gp_file_applier compares it against the value cached at the last
application and never against the script — so a stable but unrelated hash
means a changed script never runs again. The digest is computed from the bytes
on the share and is not offered to the caller.

**Registration can be reconciled.** The health tab reported that content and
registration disagree and left you to fix it elsewhere. It now says which
extension each piece of content belongs to — closing a gap
registration_problems had named in its own docstring — shows what would
change, and applies it as a separate step.

**Script files.** Four endpoints had existed since the scripts work and nothing
called them: a script could be scheduled by name with no way to put that name
on the share.

**SAMADCON_LDAP_TRANSPORTS** names which transports may be tried, in order.
Not a "secure option" switch: LDAP here is Kerberos sign-and-seal with the DC
proving itself by decrypting the ticket, LDAPS is TLS which proves something
only when the certificate is validated. The console shows what is permitted
and what the session got, and takes no view.

**Members.** A fifth diagnosis tab: what each computer in the domain may do —
which Kerberos ciphers it can negotiate, and whether it could impersonate
users authenticating to it. Two findings, unconstrained delegation on a member
and a DES cipher. An unset cipher list is deliberately not one: absent leaves
the choice to the KDC, which on anything current includes AES.

The attachable per-policy report is now written in the language the console is
being used in, while the domain's own words — section names, registry keys —
are passed through untouched.

---

## 0.5.4 — 2026-08-22

No application code changed since 0.5.3. This is documentation and packaging,
and worth pulling mainly because one of the corrections is to something the
README told people to do wrong.

**A bare IP in SAMADCON_DC_HOSTS works.** Three files said it fails with
NT_STATUS_INVALID_PARAMETER. It does not: ad/targets.py probes the configured
domain exactly as it probes a typed address, and the DC's own name is read out
of its rootDSE, because Kerberos has no principal for a bare address. The code
and the documentation were written the same day and disagreed from the start,
until someone setting up against a DC by address asked whether their compose
file was right. It was.

**A reverse proxy on another machine** now has a section of its own. The old
one described a proxy on the same host forwarding to 127.0.0.1:8443, which is
one topology and not the common one for anyone running Nginx Proxy Manager.
The four settings involved are set out as a table, including the detail that
costs an evening: a proxy running in Docker arrives as its *host's* address,
not its container's, so read SAMADCON_TRUSTED_PROXIES out of the audit log
after one sign-in rather than working it out.

**Never set SAMADCON_TRUSTED_PROXIES to 0.0.0.0/0.** That does not configure
the setting generously, it switches it off: every host becomes a trusted hop
and the audit log fills with addresses the callers chose for themselves. Worse
than leaving it empty, which merely records the proxy. Said in both READMEs
and beside the setting itself.

**Dependency floors are audited in CI now.** A reader reported
python-multipart>=0.0.9. The CVE named does not apply — it affects <= 0.0.6 —
but three others do, all denial of service and all reachable without signing
in, because FastAPI parses the request body before it solves the dependency
that checks the session. No image was ever exposed: >= resolves to a current
version. That is exactly why it needed a check rather than a fix, and why the
check runs twice: once at what a build gets, once with every floor pinned. The
second pass found two more stale floors than the report did, and then that the
declared floors could not be installed together at all.

The compose block in both READMEs is now the maintainer's own, annotated.

---

## 0.5.3 — 2026-08-21

**v0.5.2 reports itself as 0.5.1.** That is the reason for this release.

Three files carried the version number and the v0.5.2 release commit raised
two of them, missing samadcon/__init__.py — which is the one the code actually
reads. Every v0.5.2 installation therefore shows the wrong version on its
sign-in screen and returns it from /api/v1/health, from samadconctl --version
and in the OpenAPI description. Nothing else is affected: it is a label, not
behaviour. The v0.5.2 tag and its image keep the fault; tags are not moved.

The number is written in one place now. pyproject.toml declares a dynamic
version and reads the attribute out of samadcon/__init__.py, so those two
cannot disagree by construction. frontend/package.json still needs one because
npm requires the field, and it is checked rather than remembered:
scripts/check_versions.py runs in CI on every push, and on a tag build it
compares against the tag as well — which catches the one case no single-source
arrangement can, a tag pushed without the version being raised at all.

Upgrading from 0.5.2 needs nothing. Pull and restart; the console will finally
agree with the tag you pulled.

With thanks to the reviewer who found it. It was found by a reader, not by the
project, and the check now in CI is the answer to that.

---

## 0.5.2 — 2026-08-21

**Read this before pulling: the ports now bind to loopback.**

docker-compose.yml published on every interface of the host, which put a
sign-in form that issues Kerberos tickets for the domain wherever that host is
reachable — without anyone having decided it. The default is 127.0.0.1 now.
If you reach the console from another machine, set SAMADCON_BIND=0.0.0.0 (or
the one address it should answer on) before the next `docker compose up`, or
it will be gone.

The other new setting is SAMADCON_TRUSTED_PROXIES. Behind a reverse proxy
every audit entry recorded the proxy rather than the administrator, so several
administrators working through one became indistinguishable in the record
meant to tell them apart. Name the proxy and the real address is recorded.
It is a list and not a switch because X-Forwarded-For is a plain header anyone
can send; unnamed hops are not believed.

**The KI-Manager grew a second report.** Security and group policies now
answer separately, each with its own rules and its own instructions to the
model. The policy rules find what no other console reports: a policy that
reaches nobody looks exactly like one that works — its settings, versions and
links are all there, and nothing happens. `gpo_linked_but_empty` fires on real
domains, not only constructed ones.

Both reports print. There is no PDF library in the image: the browser already
writes PDFs with selectable text. The print stylesheet forces black on white,
because a reader in dark mode otherwise prints pale grey onto white paper.

**A ticket-expiry bug that would have been hard to place.** klist prints local
time and SAMADCON read it as UTC, correct only while the container had no
timezone. With TZ set and running forward, the session outlived the ticket and
operations failed partway through the work instead of asking for a new
sign-in. TZ is pinned on the call now.

**The GPMC reference files are files.** They were byte literals in the test
modules — a transcription, where a copying slip would have had every assertion
agree with it. They live in backend/tests/data now, with a note recording what
was substituted to publish them and what that costs: the domain's own names
and SIDs are gone, so a byte count no longer proves a file is GPMC's. What is
not in the repository is said plainly rather than implied.

CI built the image and never started it. It now runs the entrypoint and lets
nginx judge the result — which caught a broken include on its first run,
before it reached anyone's container.

---

## 0.5.1 — 2026-08-18

Everything here was settled against a live domain rather than reasoned about,
and three assumptions lost.

Group policy
  * Samba's own administrative templates ship in the image and install into
    the central store from the editor, so smb.conf, the Unix cron scripts and
    sudo rights are editable without adding code for them.
  * Unix/Files: read, written, uploaded and cleaned up, and proven applied on
    a member with the owner and mode it was given.
  * An emptied half is unregistered the way GPMC does it — down to the single
    space it leaves in the attribute — for the extensions GPMC clears, and
    left alone for the ones it keeps. Which is which was verified per
    extension, because Windows does not treat them alike.
  * The settings report reads Samba manifests instead of guessing at them,
    and no longer counts a security template's header sections as settings.
  * The consistency tab reports where content and registration disagree, and
    explains the one case that looks wrong and is not.

Connections
  * Samba no longer writes its own krb5.conf. It was doing so with a KDC it
    found over DNS SRV, ignoring the addresses this container had already
    proven reachable — which failed a sign-in that every other check passed.
  * The transport in use, and whether the DC's certificate was verified, are
    recorded and shown rather than left in the container log.

Licensed AGPL-3.0-or-later.

---

## 0.5.0 — 2026-08-17

First tagged release. Milestone 4 is complete: the Group Policy editor
covers administrative templates (ADMX), security settings, Samba/Linux
VGP policies, all three waves of Group Policy Preferences, and scripts
with folder redirection — each proven applied on a real client rather
than merely written to SYSVOL.

Alongside it: users, groups, computers, OUs and contacts; ACL and
delegation editing; DNS over LDAP; sites and services; diagnostics.

Licensed AGPL-3.0-or-later.
