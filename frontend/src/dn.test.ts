import { describe, expect, it } from 'vitest'

import { isAtOrBelow, nameFromDn, parentDn } from './dn'

describe('parentDn', () => {
  it('is everything after the first component', () => {
    expect(parentDn('CN=Anna,OU=Vertrieb,DC=example,DC=test')).toBe('OU=Vertrieb,DC=example,DC=test')
  })

  it('does not cut inside an escaped comma', () => {
    expect(parentDn('CN=Meyer\\, Sarah,OU=Users,DC=example,DC=test')).toBe('OU=Users,DC=example,DC=test')
  })

  it('is empty for a DN of one component', () => {
    expect(parentDn('DC=test')).toBe('')
  })
})

describe('nameFromDn', () => {
  it('is the first component without its attribute', () => {
    expect(nameFromDn('CN=Anna Meyer,OU=Users,DC=example,DC=test')).toBe('Anna Meyer')
    expect(nameFromDn('OU=Users,DC=example,DC=test')).toBe('Users')
    expect(nameFromDn('DC=example,DC=test')).toBe('example')
  })

  it('stops at the first unescaped comma, not the first comma', () => {
    // One object, called "Meyer, Sarah". A plain split gave "Meyer\".
    expect(nameFromDn('CN=Meyer\\, Sarah,OU=Users,DC=example,DC=test')).toBe('Meyer, Sarah')
  })

  it('undoes the other RFC 4514 escapes too', () => {
    expect(nameFromDn('CN=A \\+ B,OU=x')).toBe('A + B')
    expect(nameFromDn('CN=\\#1 Support,OU=x')).toBe('#1 Support')
    expect(nameFromDn('CN=Quote \\" here,OU=x')).toBe('Quote " here')
  })

  it('returns a bare value as it is', () => {
    expect(nameFromDn('Anna')).toBe('Anna')
    expect(nameFromDn('')).toBe('')
  })
})

describe('isAtOrBelow', () => {
  it('needs the comma', () => {
    expect(isAtOrBelow('OU=x,DC=example,DC=test', 'DC=example,DC=test')).toBe(true)
    expect(isAtOrBelow('DC=example,DC=test', 'DC=example,DC=test')).toBe(true)
    expect(isAtOrBelow('OU=xDC=example,DC=test', 'DC=example,DC=test')).toBe(false)
  })
})
