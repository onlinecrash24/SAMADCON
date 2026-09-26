import { describe, expect, it } from 'vitest'

import { ApiError } from '../../api/client'
import {
  CONFIRM_DELETE_ADMIN,
  CONFIRM_DISABLE_ADMIN,
  adminRefusal,
  isBuiltinAdministrator,
} from './adminDisable'

function refusal(context?: Record<string, unknown>, code = CONFIRM_DISABLE_ADMIN) {
  return new ApiError(409, {
    code,
    message: 'Disabling this account takes an administrator away from the domain.',
    context,
  })
}

describe('adminRefusal', () => {
  it('recognises the refusal and reads who it is about', () => {
    expect(adminRefusal(refusal({ role: 'Domain Admins', account: 'anna.admin' }))).toEqual({
      action: 'disable',
      role: 'Domain Admins',
      account: 'anna.admin',
    })
  })

  it('tells a refused delete from a refused disable', () => {
    expect(adminRefusal(refusal({ role: 'Enterprise Admins' }, CONFIRM_DELETE_ADMIN))).toEqual({
      action: 'delete',
      role: 'Enterprise Admins',
      account: null,
    })
  })

  it('is nothing for any other error', () => {
    expect(adminRefusal(new ApiError(409, { code: 'template_exists', message: 'x' }))).toBeNull()
    expect(adminRefusal(new Error('network'))).toBeNull()
    expect(adminRefusal(null)).toBeNull()
  })

  it('does not trust the shape of what the server sent', () => {
    expect(adminRefusal(refusal({ role: 42, account: '' }))).toEqual({
      action: 'disable',
      role: '',
      account: null,
    })
    expect(adminRefusal(refusal())).toEqual({ action: 'disable', role: '', account: null })
  })
})

describe('isBuiltinAdministrator', () => {
  it('tells the built-in account from a membership', () => {
    expect(
      isBuiltinAdministrator({ action: 'disable', role: 'Administrator', account: 'Administrator' }),
    ).toBe(true)
    expect(isBuiltinAdministrator({ action: 'disable', role: 'Domain Admins', account: 'x' })).toBe(
      false,
    )
  })
})
