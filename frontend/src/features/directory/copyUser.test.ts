import { describe, expect, it } from 'vitest'

import { requestedGroups } from './copyUser'

const SALES = 'CN=Vertrieb,OU=Gruppen,DC=example,DC=test'
const VPN = 'CN=VPN,OU=Gruppen,DC=example,DC=test'

describe('the groups a copy asks for', () => {
  it('are left to the server when none is unticked', () => {
    expect(requestedGroups([SALES, VPN], new Set())).toBeUndefined()
  })

  it('are the ticked ones otherwise', () => {
    expect(requestedGroups([SALES, VPN], new Set([VPN.toLowerCase()]))).toEqual([SALES])
  })

  it('may be none at all', () => {
    expect(requestedGroups([SALES], new Set([SALES.toLowerCase()]))).toEqual([])
  })
})
