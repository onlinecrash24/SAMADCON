/**
 * The question ADUC asks before resetting a computer account, asked from the
 * row of buttons and from the right-click menu alike: the machine's trust
 * with the domain breaks until it is joined again.
 */

import { useMutation } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { useI18n } from '../../i18n'

export function ConfirmResetComputer({
  dn,
  name,
  onClose,
  onDone,
}: {
  dn: string
  name: string
  onClose: () => void
  onDone: (message: string) => void
}) {
  const { t } = useI18n()
  const reset = useMutation({
    mutationFn: () => api.resetComputer(dn),
    onSuccess: () => {
      onClose()
      onDone(t('status.saved'))
    },
  })

  return (
    <ConfirmDialog
      title={t('computer.resetConfirmTitle', { name })}
      confirmLabel={t('action.resetAccount')}
      pending={reset.isPending}
      error={reset.error}
      onConfirm={() => reset.mutate()}
      onCancel={onClose}
    >
      <p>{t('computer.resetConfirmBody')}</p>
    </ConfirmDialog>
  )
}
