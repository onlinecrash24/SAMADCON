"""SAMADCON — Samba AD Console.

A web front end for administering Samba Active Directory domain controllers,
built on the Samba python bindings (LDAP/LDAPS, Kerberos, SMB).
"""

# The version, and the only place it is written. pyproject.toml reads this
# attribute; /api/v1/health, /api/v1/info, the sign-in screen, samadconctl
# --version and the OpenAPI description all read it through this module.
#
# Keep it a plain string literal. setuptools parses this file rather than
# importing it, which is what keeps the samba bindings out of the build —
# anything it cannot evaluate statically sends it back to importing.
__version__ = "0.5.4"
