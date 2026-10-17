/**
 * Whether the domain controller is a Samba one.
 *
 * Some things behave differently on a Windows DC. The password policy is the
 * first: a Samba DC leaves the Default Domain Policy's values off the domain
 * object, a Windows DC copies them there. 0.6.15 said the Samba half to a
 * tester running three Windows domains. Samba names itself in the rootDSE's
 * vendorName; a Windows DC sends none, so anything else counts as Windows.
 */

export function isSambaDc(domain: { dc_vendor?: string | null } | null | undefined): boolean {
  return (domain?.dc_vendor ?? '').trim().toLowerCase().startsWith('samba')
}
