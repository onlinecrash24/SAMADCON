import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { DirectoryObject } from '../../api/types'
import { DeleteDialog, MoveDialog, PasswordDialog, RenameDialog } from '../../components/dialogs'
import { ErrorMessage } from '../../components/primitives'
import { useI18n } from '../../i18n'
import { detailRowActions, type AccountFacts, type ActionId } from './objectActions'

/**
 * The row of commands above an object — enable, reset password, rename,
 * move, delete — and the dialogs they open.
 *
 * Shared by the pane beside the list and the property window, so the two
 * cannot offer different commands for the same object. These are actions,
 * not fields: each one is its own operation in the directory and happens
 * when pressed, as it does in ADUC's context menu. What a property sheet
 * holds until OK is the sheet's business, not this row's.
 */
export function ObjectCommands({
  object,
  facts,
  onChanged,
  onRetarget,
}: {
  object: DirectoryObject
  facts: AccountFacts
  onChanged: (message: string) => void
  /** A rename or a move changed the DN out from under whoever hosts this. */
  onRetarget?: (dn: string, name: string) => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [dialog, setDialog] = useState<'password' | 'rename' | 'move' | 'delete' | null>(null)
  const [error, setError] = useState<unknown>(null)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['object-detail'] })
    void queryClient.invalidateQueries({ queryKey: ['object'] })
    void queryClient.invalidateQueries({ queryKey: ['children'] })
    void queryClient.invalidateQueries({ queryKey: ['tree'] })
  }

  const action = useMutation({
    mutationFn: async (task: () => Promise<string>) => task(),
    onSuccess: (message) => {
      setError(null)
      invalidate()
      onChanged(message)
    },
    onError: setError,
  })

  const done = (message: string) => {
    invalidate()
    onChanged(message)
  }

  const run = (id: ActionId) => {
    switch (id) {
      case 'enable':
        action.mutate(async () => {
          await api.setEnabled(object.dn, true)
          return t('status.saved')
        })
        return
      case 'disable':
        action.mutate(async () => {
          await api.setEnabled(object.dn, false)
          return t('status.saved')
        })
        return
      case 'unlock':
        action.mutate(async () => {
          await api.unlock(object.dn)
          return t('status.unlocked')
        })
        return
      case 'resetAccount':
        action.mutate(async () => {
          await api.resetComputer(object.dn)
          return t('status.saved')
        })
        return
      case 'resetPassword':
        setDialog('password')
        return
      case 'rename':
      case 'move':
      case 'delete':
        setDialog(id)
        return
      default:
        return
    }
  }

  return (
    <>
      <ErrorMessage error={error} onDismiss={() => setError(null)} />
      {/* The same list the right-click menu is built from. Two hand-written
          descriptions of "what applies to a computer" drift apart the week
          after they are written: someone adds an action to one of them. */}
      <div className="detail__actions">
        {detailRowActions(object, facts).map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={entry.danger ? 'button button--danger' : 'button'}
            disabled={action.isPending}
            onClick={() => run(entry.id)}
          >
            {t(entry.labelKey)}
          </button>
        ))}
      </div>

      {dialog === 'password' && (
        <PasswordDialog dn={object.dn} onClose={() => setDialog(null)} onDone={done} />
      )}
      {dialog === 'rename' && (
        <RenameDialog
          dn={object.dn}
          currentName={object.name}
          onClose={() => setDialog(null)}
          onDone={done}
          onRelocated={onRetarget}
        />
      )}
      {dialog === 'move' && (
        <MoveDialog
          dn={object.dn}
          name={object.name}
          onClose={() => setDialog(null)}
          onDone={done}
          onRelocated={onRetarget}
        />
      )}
      {dialog === 'delete' && (
        <DeleteDialog
          dn={object.dn}
          name={object.name}
          isContainer={object.is_container}
          isOu={object.type === 'organizational_unit'}
          onClose={() => setDialog(null)}
          onDone={done}
        />
      )}
    </>
  )
}
