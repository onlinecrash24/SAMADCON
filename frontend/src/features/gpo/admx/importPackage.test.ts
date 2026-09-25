import { describe, expect, it } from 'vitest'

import {
  DEFAULT_LANGUAGES,
  MICROSOFT_LANGUAGES,
  folderFilesToSend,
  formatBytes,
} from './importPackage'

/** A folder picked in a browser, shaped like Microsoft's package. */
function folder(root = 'PolicyDefinitions') {
  return [
    { path: `${root}/Search.admx`, size: 100 },
    { path: `${root}/WinLogon.admx`, size: 100 },
    { path: `${root}/en-US/Search.adml`, size: 10 },
    { path: `${root}/de-de/Search.adml`, size: 10 },
    { path: `${root}/fr-fr/Search.adml`, size: 10 },
    { path: `${root}/desktop.ini`, size: 1 },
  ]
}

describe('folderFilesToSend', () => {
  it('sends every template and the texts of the chosen languages', () => {
    const { send, left } = folderFilesToSend(folder(), DEFAULT_LANGUAGES)
    expect(send.map((file) => file.path)).toEqual([
      'PolicyDefinitions/Search.admx',
      'PolicyDefinitions/WinLogon.admx',
      'PolicyDefinitions/en-US/Search.adml',
      'PolicyDefinitions/de-de/Search.adml',
    ])
    expect(left).toBe(2)
  })

  it('matches a language however the package spells it', () => {
    // Microsoft's MSI writes every directory but en-US in lower case.
    const { send } = folderFilesToSend(folder(), ['DE-de'])
    expect(send.some((file) => file.path.endsWith('de-de/Search.adml'))).toBe(true)
  })

  it('reads backslashes as separators', () => {
    const { send } = folderFilesToSend([{ path: 'PolicyDefinitions\\de-de\\Search.adml', size: 1 }], [
      'de-DE',
    ])
    expect(send).toHaveLength(1)
  })

  it('sends the templates even with no language chosen', () => {
    const { send } = folderFilesToSend(folder(), [])
    expect(send.map((file) => file.path)).toEqual([
      'PolicyDefinitions/Search.admx',
      'PolicyDefinitions/WinLogon.admx',
    ])
  })

  it('adds up what it will send', () => {
    expect(folderFilesToSend(folder(), DEFAULT_LANGUAGES).bytes).toBe(220)
  })
})

describe('the language list', () => {
  it('offers the defaults among its choices', () => {
    for (const language of DEFAULT_LANGUAGES) {
      expect(MICROSOFT_LANGUAGES).toContain(language)
    }
  })

  it('holds the 22 directories of the Windows 11 package', () => {
    expect(new Set(MICROSOFT_LANGUAGES).size).toBe(22)
  })
})

describe('formatBytes', () => {
  it('rounds to what a reader can weigh', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2 KB')
    expect(formatBytes(12.2 * 1024 * 1024)).toBe('12.2 MB')
  })
})
