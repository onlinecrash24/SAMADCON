/**
 * The three things you can do to a policy without opening it.
 *
 * They lived inside the policy editor, which was the only place they could be
 * reached from — so acting on a policy meant opening it first, and closing it
 * afterwards. A right-click on the row in the list is the shorter way, and it
 * is the one GPMC has.
 *
 * Out here rather than duplicated: the editor and the list ask for the same
 * three, and two copies of "are you sure you want to delete this policy" drift
 * the moment one of them learns something the other does not.
 */

import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { Gpo } from '../../api/types'
import { ErrorMessage, Modal } from '../../components/primitives'
import { useI18n } from '../../i18n'

interface GpoDialogProps {
  gpo: Gpo
  onClose: () => void
  onDone: () => void
}

/** The name that identifies a policy to a person; the GUID when it has none. */
export function gpoName(gpo: Gpo): string {
  return gpo.display_name ?? gpo.guid
}

export function CopyGpoDialog({ gpo, onClose, onDone }: GpoDialogProps) {
  const { t } = useI18n()
  const [name, setName] = useState(`${gpoName(gpo)} (copy)`)
  const [error, setError] = useState<unknown>(null)

  const copy = useMutation({
    mutationFn: () => api.copyGpo(gpo.dn, name.trim()),
    onSuccess: onDone,
    onError: setError,
  })

  return (
    <Modal
      title={t('gpo.copy')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!name.trim() || copy.isPending}
            onClick={() => copy.mutate()}
          >
            {t('gpo.copy')}
          </button>
        </>
      }
    >
      <ErrorMessage error={error} />
      <label className="field">
        <span className="field__label">{t('gpo.name')}</span>
        <input value={name} onChange={(event) => setName(event.target.value)} autoFocus />
        <span className="field__hint">{t('gpo.copyHint')}</span>
      </label>
    </Modal>
  )
}

/**
 * Renaming a policy changes its display name, not its directory name.
 *
 * Which is why this cannot reuse the directory rename dialog: that one moves
 * an object's RDN. A policy keeps its GUID for life — every link and every
 * client refers to it by that — and what changes here is only what people call
 * it.
 */
export function RenameGpoDialog({ gpo, onClose, onDone }: GpoDialogProps) {
  const { t } = useI18n()
  const [name, setName] = useState(gpoName(gpo))
  const [error, setError] = useState<unknown>(null)

  const rename = useMutation({
    mutationFn: () => api.updateGpo(gpo.dn, { display_name: name.trim() }),
    onSuccess: onDone,
    onError: setError,
  })

  return (
    <Modal
      title={t('dialog.renameTitle')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!name.trim() || name === gpoName(gpo) || rename.isPending}
            onClick={() => rename.mutate()}
          >
            {t('action.save')}
          </button>
        </>
      }
    >
      <ErrorMessage error={error} />
      <label className="field">
        <span className="field__label">{t('gpo.name')}</span>
        <input value={name} onChange={(event) => setName(event.target.value)} autoFocus />
        <span className="field__hint">{t('gpo.renameHint')}</span>
      </label>
    </Modal>
  )
}

export function DeleteGpoDialog({ gpo, onClose, onDone }: GpoDialogProps) {
  const { t } = useI18n()
  const [error, setError] = useState<unknown>(null)

  const remove = useMutation({
    mutationFn: () => api.deleteGpo(gpo.dn, false),
    onSuccess: onDone,
    onError: setError,
  })

  return (
    <Modal
      title={t('gpo.confirmDeleteTitle')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--danger"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            {t('action.delete')}
          </button>
        </>
      }
    >
      <ErrorMessage error={error} />
      <p>{t('gpo.confirmDelete', { name: gpoName(gpo) })}</p>
      <p className="muted small">{t('gpo.confirmDeleteHint')}</p>
    </Modal>
  )
}
