/**
 * ADUC's account options "This account supports Kerberos AES 128 bit
 * encryption" and "… AES 256 bit encryption": two bits of
 * msDS-SupportedEncryptionTypes (MS-KILE 2.2.7). The other bits — DES, RC4
 * and the rest — stay as they are.
 *
 * Absent means the domain's default, and is shown as neither box ticked. An
 * attribute that ends up with no bit at all is removed rather than written
 * as 0, which would mean "no encryption type", not "the default".
 */

export const AES128 = 0x08
export const AES256 = 0x10

export const ENCRYPTION_ATTRIBUTE = 'msDS-SupportedEncryptionTypes'

export function hasEncryption(value: number | null, bit: number): boolean {
  return value !== null && (value & bit) !== 0
}

export function withEncryption(value: number | null, bit: number, on: boolean): number | null {
  const next = on ? (value ?? 0) | bit : (value ?? 0) & ~bit
  return next === 0 ? null : next
}
