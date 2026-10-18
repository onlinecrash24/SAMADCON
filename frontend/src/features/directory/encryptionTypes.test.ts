import { describe, expect, it } from 'vitest'

import { AES128, AES256, hasEncryption, withEncryption } from './encryptionTypes'

// ADUC's account options "This account supports Kerberos AES 128/256 bit
// encryption" are two bits of msDS-SupportedEncryptionTypes. SAMADCON read
// the attribute in diagnostics and offered neither box.

describe('the AES account options', () => {
  it('are the bits Microsoft gives them', () => {
    expect(AES128).toBe(0x08)
    expect(AES256).toBe(0x10)
  })

  it('read an absent attribute as neither', () => {
    expect(hasEncryption(null, AES128)).toBe(false)
    expect(hasEncryption(0x18, AES256)).toBe(true)
  })

  it('set their own bit and keep the others', () => {
    // RC4 (0x4) stays as it was.
    expect(withEncryption(0x04, AES256, true)).toBe(0x14)
    expect(withEncryption(null, AES128, true)).toBe(0x08)
  })

  it('clear their own bit and keep the others', () => {
    expect(withEncryption(0x1c, AES128, false)).toBe(0x14)
  })

  it('leave the attribute absent when nothing was set and nothing is', () => {
    expect(withEncryption(null, AES128, false)).toBeNull()
  })

  it('remove the attribute when the last bit goes', () => {
    expect(withEncryption(0x08, AES128, false)).toBeNull()
  })
})
