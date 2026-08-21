"""Group policy.

A GPO is two objects that have to be kept in step:

* the **GPC**, a ``groupPolicyContainer`` in LDAP under
  ``CN=Policies,CN=System,<base>``, carrying the display name, the version
  number, the links and the security filtering, and
* the **GPT**, a directory tree on the SYSVOL share holding the files the
  client-side extensions actually read.

Nothing enforces that the two agree. Windows decides whether to re-apply a
policy by comparing the version in ``GPT.INI`` with ``versionNumber`` in LDAP,
so a change written to only one half is either ignored or applied forever.
Keeping them in step is the job of this package.
"""
