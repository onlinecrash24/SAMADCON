import { describe, expect, it } from 'vitest'

import { NO_OPTIONS, conditionFromObject, setOption } from './preferenceOptions'

describe('the common options', () => {
  it('turns the action into Replace when removal is ticked, as GPMC does', () => {
    const next = setOption(NO_OPTIONS, 'U', 'remove_policy', true)
    expect(next).toEqual({ options: { ...NO_OPTIONS, remove_policy: true }, action: 'R' })
  })

  it('clears apply-once when removal is ticked, and the other way round', () => {
    const once = { ...NO_OPTIONS, run_once: true }
    expect(setOption(once, 'U', 'remove_policy', true).options.run_once).toBe(false)
    const removed = { ...NO_OPTIONS, remove_policy: true }
    expect(setOption(removed, 'R', 'run_once', true).options.remove_policy).toBe(false)
  })

  it('leaves the action alone for every other option', () => {
    expect(setOption(NO_OPTIONS, 'U', 'stop_on_error', true).action).toBe('U')
    expect(setOption(NO_OPTIONS, undefined, 'user_context', true).action).toBeUndefined()
  })
})

describe('a condition picked from the directory', () => {
  const group = {
    dn: 'CN=Domain Users,CN=Users,DC=myantispam,DC=local',
    name: 'Domain Users',
    sam_account_name: 'Domain Users',
    sid: 'S-1-5-21-2540059117-2646349506-3686739550-513',
  }

  it('names a group as GPMC does and keeps the DN for the server to check', () => {
    expect(conditionFromObject('group', group, 'MYANTISPAM')).toEqual({
      type: 'group',
      bool: 'AND',
      not: false,
      name: 'MYANTISPAM\\Domain Users',
      sid: group.sid,
      user_context: true,
      primary_group: false,
      local_group: false,
      dn: group.dn,
    })
  })

  it('names an OU by its DN', () => {
    const ou = { dn: 'OU=Test,DC=myantispam,DC=local', name: 'Test' }
    expect(conditionFromObject('ou', ou, 'MYANTISPAM')).toMatchObject({
      type: 'ou',
      name: 'OU=Test,DC=myantispam,DC=local',
      user_context: true,
      direct_member: false,
    })
  })

  it('names a computer by its account without the dollar', () => {
    const computer = {
      dn: 'CN=WIN11-PVE,CN=Computers,DC=myantispam,DC=local',
      name: 'WIN11-PVE',
      sam_account_name: 'WIN11-PVE$',
    }
    expect(conditionFromObject('computer', computer, 'MYANTISPAM')).toMatchObject({
      type: 'computer',
      name: 'WIN11-PVE',
      computer_type: 'NETBIOS',
    })
  })
})
