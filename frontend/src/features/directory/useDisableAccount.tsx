/**
 * Disabling an account from a menu or a command, with the question the server
 * may ask first.
 *
 * The context menu and the detail pane's commands both disable in one step.
 * For most accounts that is what ADUC does too. For an administrator the
 * server refuses without a confirmation; this turns that refusal into the
 * dialog and, once the box is ticked, sends the same request confirmed.
 */

import { useState, type ReactNode } from 'react'

import { api } from '../../api/endpoints'
import { adminRefusal, type AdminRefusal } from './adminDisable'
import { ConfirmAdminDisable } from './ConfirmAdminDisable'

interface Asking {
  dn: string
  name: string
  refusal: AdminRefusal
}

export function useDisableAccount({
  onDone,
  onError,
}: {
  onDone: () => void
  onError: (cause: unknown) => void
}): { disable: (object: { dn: string; name: string }) => Promise<void>; dialog: ReactNode } {
  const [asking, setAsking] = useState<Asking | null>(null)
  const [pending, setPending] = useState(false)

  const disable = async (object: { dn: string; name: string }) => {
    try {
      await api.setEnabled(object.dn, false)
      onDone()
    } catch (cause) {
      const refusal = adminRefusal(cause)
      if (refusal) setAsking({ ...object, refusal })
      else onError(cause)
    }
  }

  const confirm = async () => {
    if (!asking) return
    setPending(true)
    try {
      await api.setEnabled(asking.dn, false, true)
      setAsking(null)
      onDone()
    } catch (cause) {
      setAsking(null)
      onError(cause)
    } finally {
      setPending(false)
    }
  }

  const dialog = asking ? (
    <ConfirmAdminDisable
      name={asking.name}
      refusal={asking.refusal}
      pending={pending}
      onCancel={() => setAsking(null)}
      onConfirm={() => void confirm()}
    />
  ) : null

  return { disable, dialog }
}
