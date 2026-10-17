import { describe, expect, it } from 'vitest'

import { choiceLabel, choicesWithCurrent } from './fieldChoices'

const t = (key: string) => `[${key}]`

describe('the choices of a preference field', () => {
  it('shows a drive letter with its colon, and asks for one when there is none', () => {
    expect(choiceLabel('letter', 'Q', t)).toBe('Q:')
    expect(choiceLabel('letter', '', t)).toBe('[pref.letter.choose]')
  })

  it('shows hives and registry types as the registry spells them', () => {
    expect(choiceLabel('hive', 'HKEY_LOCAL_MACHINE', t)).toBe('HKEY_LOCAL_MACHINE')
    expect(choiceLabel('type', 'REG_SZ', t)).toBe('REG_SZ')
  })

  it('gives every other choice a word', () => {
    expect(choiceLabel('thisDrive', 'NOCHANGE', t)).toBe('[pref.choice.NOCHANGE]')
  })

  it('offers a value from the file that is not in the list, rather than losing it', () => {
    expect(choicesWithCurrent(['', 'A', 'B'], 'b')).toEqual(['', 'A', 'B', 'b'])
    expect(choicesWithCurrent(['', 'A', 'B'], 'A')).toEqual(['', 'A', 'B'])
  })
})
