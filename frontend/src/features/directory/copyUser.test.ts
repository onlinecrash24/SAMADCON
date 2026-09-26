import { describe, expect, it } from 'vitest'

import { requestedGroups, templateGroups } from './copyUser'

const SALES = 'CN=Vertrieb,OU=Gruppen,DC=example,DC=test'
const VPN = 'CN=VPN,OU=Gruppen,DC=example,DC=test'
const PRIMARY = 'CN=Vertrieb-Primaer,OU=Gruppen,DC=example,DC=test'
const DOMAIN_USERS = 'CN=Domain Users,CN=Users,DC=example,DC=test'

describe('the groups a copy offers', () => {
  it('are the template memberships', () => {
    const groups = templateGroups({ member_of: [SALES, VPN], primary_group_id: 513, primary_group_dn: DOMAIN_USERS })
    expect(groups).toEqual([SALES, VPN])
  })

  it('include a primary group other than Domain Users, which memberOf leaves out', () => {
    const groups = templateGroups({ member_of: [SALES], primary_group_id: 1300, primary_group_dn: PRIMARY })
    expect(groups).toEqual([SALES, PRIMARY])
  })

  it('do not list a group twice', () => {
    const groups = templateGroups({ member_of: [PRIMARY], primary_group_id: 1300, primary_group_dn: PRIMARY.toLowerCase() })
    expect(groups).toEqual([PRIMARY])
  })
})

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
