# Where these files come from

Three files that GPMC wrote, kept here so the tests compare against an
artefact rather than against a transcription of one. Each was read off SYSVOL
with `od -c` on the domain controller and is byte for byte what a Windows
Group Policy Management Console produced — with one exception, described
below, which is the whole reason this note exists.

They are read by the unit tests through `reference()` in
`backend/tests/conftest.py`. Nothing writes them; a test that needs a variant
builds it from the loaded bytes.

## The files

| File | What it is | Produced by |
|---|---|---|
| `fdeploy1.ini` | Folder redirection: Saved Games, redirected under a root path for Everyone | GPMC, GPO "Wegwerf-GPO" |
| `scripts.ini` | A machine startup script — PowerShell with an execution-policy argument | GPMC, GPO "Deploy Tactical RMM Agent" |
| `GptTmpl.inf` | Security settings: minimum password length, lockout threshold, logon auditing, one user right | GPMC, GPO "Wegwerf-GPO" |
| `fdeploy1-cleared.ini` | The same file after the last redirected folder was set back to *Not configured* | GPMC, GPO "Wegwerf-GPO" |
| `GptTmpl-audit.inf` | Security log size 81920 KB, application log retention "as needed", "force audit policy subcategory settings" enabled | GPMC (German), GPO "SAMADCON-Referenz-Audit" |
| `audit.csv` | Advanced audit policy: "Audit Logon" success and failure, "Audit User Account Management" success | GPMC (German), GPO "SAMADCON-Referenz-Audit" |

All four are UTF-16LE with a `FF FE` byte-order mark and CRLF line endings.
That is not incidental — a client ignores the file if the encoding is wrong,
and says nothing about it.

Between them they settle a number of details no specification states: the
blank line `scripts.ini` opens with and the absence of an empty `[Shutdown]`
section; the preamble of `fdeploy1.ini`, which is a blank line, a line of five
spaces and another blank line, and its lower-case `[version]` beside
mixed-case `[Folder_Redirection]`; the spacing around the equals sign in
`GptTmpl.inf`, which differs from section to section.

### The one that needed no sanitising

`fdeploy1-cleared.ini` is unmodified. It is what GPMC leaves behind when the
last redirected folder goes back to *Not configured*, and what it leaves is a
preamble and nothing else: the byte-order mark, a blank line, a line of five
spaces, `[version]`, `version=100`, `[Folder_Redirection]`. No folder, no
SID, no path — so there was nothing in it to replace, and the 112 bytes here
are the 112 bytes on the share.

That makes it the only reference in this directory a third party can check
against their own GPMC exactly. It also settles two questions that had been
guessed at: GPMC does **not** delete the file, and it does **not** leave the
redirection behind marked as off. A note in the working list had it that a
cleared redirection keeps its section with `Flags=4`. It does not.

## What was changed, and what that costs

**The domain's own identifiers were replaced with example ones before
publication.** Domain names, host names and SIDs are the values that appear in
these files, and this is a public repository. What was substituted:

- the DNS domain and the DC host name, now `example.lan` / `dc1.example.lan`
- the SIDs, now the well-known `S-1-1-0` and an example domain SID
- the script's UNC path, now under `example.lan`

Everything structural is untouched: encoding, byte-order mark, line endings,
section order and case, spacing, the numbering scheme, the sections left
empty.

The cost is worth stating plainly rather than leaving for someone to work out.
The original files were 460, 298 and 752 bytes; these are 446, 282 and 750,
the difference being the shorter substituted names. So a byte count no longer
proves these files are what GPMC wrote — a recomputed one would only assert
that a file equals itself. **A third party cannot verify these against a real
GPMC from this repository alone.** They can verify that SAMADCON reads and
writes them exactly, which is what the tests do, and they can produce their
own files from their own GPMC and compare the structure.

Publishing the unmodified originals would settle it, and would also publish a
real domain's names and SIDs. That trade was made deliberately, in favour of
not publishing them.

## The proof these files are not

These fixtures show that a file is shaped right. They do not show that a
client applies it — a formally correct file and an applied policy are
different claims, and only the second one matters. That second proof runs on a
domain-joined Windows 11 through `gpresult /h`, and on a Linux member through
`samba-gpupdate --rsop`. Those reports are not in this repository: sanitising a
`gpresult` report is a good deal harder than sanitising an INI file, since it
carries the whole applied policy set of a real machine. What they showed is
described in the README, section "The policy editor".

## The two audit references (September 2026)

`GptTmpl-audit.inf` and `audit.csv` come from the reference GPO
"SAMADCON-Referenz-Audit", made in a German GPMC on Windows 11 for the advanced
audit policy work. They carry no domain names, host names or SIDs, so nothing
was substituted.

Unlike the files above they were **not** copied off the share byte for byte.
They were rebuilt from what the domain controller printed: `iconv -f UTF-16
-t UTF-8` for `GptTmpl.inf`, `cat -A` for `audit.csv`, which shows every line
ending and would have shown a UTF-8 byte-order mark had there been one. What
the rebuild assumes is only what the older references already established for
`GptTmpl.inf` — UTF-16LE with `FF FE` and CRLF. It held: `sha256sum` on the
domain controller gave the same digests as the rebuilt files,

    391d6e1e19856db2f7054b9730f5d71821697741f191a81d70e0dbdf9e3690c9  GptTmpl.inf
    e901a3c4b73b901b2c7cb1d6dfd6cb648280d93593eacc691a5459d8fe491a88  audit.csv

so these are the bytes on the share, not a transcription of them.

`audit.csv` settles its format: UTF-8 without a byte-order mark, CRLF, seven
columns, and a header and texts in the language of the console that wrote it.
`GptTmpl-audit.inf` settles that `[Registry Values]` is written without spaces
around the equals sign — which the first reference could not show, having had
that section empty.

## The preference references with item-level targeting (October 2026)

`Drives-ilt.xml` and `Registry-ilt.xml` come from the reference GPO
"SAMADCON-Referenz-ILT", made in a German GPMC on Windows 11 to settle how the
common options and item-level targeting of group policy preferences are
written. The domain is the maintainer's test domain, and its names and SIDs
were kept: they are part of what is measured.

Rebuilt from what `cat` printed on the domain controller, with tabs for the
indentation the terminal showed as spaces, and only three assumptions tried:
byte-order mark or none, CRLF or LF, final newline or none. One combination
matched the digests `sha256sum` gave on the domain controller,

    62e30f1b66aaf340dddf8999a8599c60687fbdc38a737c7df68503721edc9c97  Drives.xml
    e55fd2a46201cb1fb63c3c9739689e80f94d400c3e8b89a3c4737e8a07ef572e  Registry.xml

— UTF-8 without a byte-order mark, CRLF, a final newline — so these are the
bytes on the share.

What they settle, item by item (all drive maps to `\zmb-ad\netlogon`):

- P: every common option ticked GPMC allows together. "Remove this item when
  it is no longer applied" is `removePolicy="1"` and turned the action into
  Replace (`action="R"`); "run in the logged-on user's security context" is
  `userContext="1"`; "stop processing items on error" ticked is
  `bypassErrors="0"`. Targeting: user in group Domain Users.
- T: "apply once and do not reapply" instead of removal — GPMC greys one out
  while the other is ticked. It is no attribute but a filter,
  `<FilterRunOnce hidden="1" not="0" bool="AND" id="{GUID}"/>`, after which
  GPMC writes a CRLF and two tabs before `</Filters>`.
- Q, R, S: no options ticked — `bypassErrors="1"`, no `userContext`, no
  `removePolicy`. Q targets an OU, negated (`FilterOrgUnit not="1"`); R a
  computer name OR computer in group (`bool="OR"`, `userContext="0"`); S a
  user AND a group AND a computer name.
- Registry: a machine-side item with removal and stop-on-error; it carries
  no `userContext` at all.
