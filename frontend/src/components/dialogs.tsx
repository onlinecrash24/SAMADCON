/** Dialogs for the create/rename/delete/password actions. */

import { useState, type FormEvent } from 'react'

import { api } from '../api/endpoints'
import { useI18n } from '../i18n'
import { ErrorMessage, Field, Modal } from './primitives'

interface DialogProps {
  onClose: () => void
  onDone: (message: string) => void
}

function useSubmit(onDone: (message: string) => void, onClose: () => void) {
  const [error, setError] = useState<unknown>(null)
  const [pending, setPending] = useState(false)

  const run = async (action: () => Promise<string>) => {
    setError(null)
    setPending(true)
    try {
      const message = await action()
      onDone(message)
      onClose()
    } catch (cause) {
      setError(cause)
    } finally {
      setPending(false)
    }
  }

  return { error, setError, pending, run }
}

// ---------------------------------------------------------------------------
// New user
// ---------------------------------------------------------------------------

export function NewUserDialog({ parentDn, onClose, onDone }: DialogProps & { parentDn: string }) {
  const { t } = useI18n()
  const { error, setError, pending, run } = useSubmit(onDone, onClose)
  const [form, setForm] = useState({
    first_name: '',
    last_name: '',
    sam: '',
    password: '',
    mustChange: true,
    enabled: true,
  })

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((current) => ({ ...current, [key]: value }))

  const commonName = [form.first_name, form.last_name].filter(Boolean).join(' ') || form.sam

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void run(async () => {
      const created = await api.createUser({
        parent_dn: parentDn,
        sam_account_name: form.sam.trim(),
        common_name: commonName,
        password: form.password || undefined,
        must_change_password: form.mustChange,
        enabled: form.enabled,
        attributes: {
          ...(form.first_name ? { first_name: form.first_name } : {}),
          ...(form.last_name ? { last_name: form.last_name } : {}),
          ...(commonName ? { display_name: commonName } : {}),
        },
      })
      return t('status.created', { name: created.name })
    })
  }

  return (
    <Modal
      title={t('dialog.newUserTitle')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button type="submit" form="new-user" className="button button--primary" disabled={pending}>
            {t('action.create')}
          </button>
        </>
      }
    >
      <form id="new-user" onSubmit={submit} className="form">
        <ErrorMessage error={error} onDismiss={() => setError(null)} />
        <div className="form__grid">
          <Field label={t('user.firstName')}>
            <input value={form.first_name} onChange={(e) => set('first_name', e.target.value)} />
          </Field>
          <Field label={t('user.lastName')}>
            <input value={form.last_name} onChange={(e) => set('last_name', e.target.value)} />
          </Field>
        </div>
        <Field label={t('user.logonName')} hint="sAMAccountName — max. 20">
          <input
            required
            maxLength={20}
            value={form.sam}
            onChange={(e) => set('sam', e.target.value)}
          />
        </Field>
        <Field label={t('login.password')}>
          <input
            type="password"
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => set('password', e.target.value)}
          />
        </Field>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.mustChange}
            onChange={(e) => set('mustChange', e.target.checked)}
          />
          <span>{t('dialog.passwordMustChange')}</span>
        </label>
        {form.mustChange && (
          <p className="muted small">{t('dialog.passwordMustChangeHint')}</p>
        )}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => set('enabled', e.target.checked)}
          />
          <span>{t('user.status.active')}</span>
        </label>
      </form>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// New group / computer / OU
// ---------------------------------------------------------------------------

export function NewGroupDialog({ parentDn, onClose, onDone }: DialogProps & { parentDn: string }) {
  const { t } = useI18n()
  const { error, setError, pending, run } = useSubmit(onDone, onClose)
  const [name, setName] = useState('')
  const [scope, setScope] = useState('global')
  const [security, setSecurity] = useState(true)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void run(async () => {
      const created = await api.createGroup({
        parent_dn: parentDn,
        name: name.trim(),
        scope,
        security,
      })
      return t('status.created', { name: created.name })
    })
  }

  return (
    <Modal
      title={t('dialog.newGroupTitle')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button type="submit" form="new-group" className="button button--primary" disabled={pending}>
            {t('action.create')}
          </button>
        </>
      }
    >
      <form id="new-group" onSubmit={submit} className="form">
        <ErrorMessage error={error} onDismiss={() => setError(null)} />
        <Field label={t('list.name')}>
          <input required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t('group.scope')}>
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="global">{t('group.scope.global')}</option>
            <option value="domain_local">{t('group.scope.domain_local')}</option>
            <option value="universal">{t('group.scope.universal')}</option>
          </select>
        </Field>
        <Field label={t('group.type')}>
          <select value={security ? 'security' : 'distribution'} onChange={(e) => setSecurity(e.target.value === 'security')}>
            <option value="security">{t('group.security')}</option>
            <option value="distribution">{t('group.distribution')}</option>
          </select>
        </Field>
      </form>
    </Modal>
  )
}

export function NewComputerDialog({ parentDn, onClose, onDone }: DialogProps & { parentDn: string }) {
  const { t } = useI18n()
  const { error, setError, pending, run } = useSubmit(onDone, onClose)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void run(async () => {
      const created = await api.createComputer({
        parent_dn: parentDn,
        name: name.trim(),
        description: description || undefined,
      })
      return t('status.created', { name: created.name })
    })
  }

  return (
    <Modal
      title={t('dialog.newComputerTitle')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button type="submit" form="new-computer" className="button button--primary" disabled={pending}>
            {t('action.create')}
          </button>
        </>
      }
    >
      <form id="new-computer" onSubmit={submit} className="form">
        <ErrorMessage error={error} onDismiss={() => setError(null)} />
        <Field label={t('list.name')} hint="NetBIOS — max. 15">
          <input required maxLength={15} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t('list.description')}>
          <input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
      </form>
    </Modal>
  )
}

export function NewOuDialog({ parentDn, onClose, onDone }: DialogProps & { parentDn: string }) {
  const { t } = useI18n()
  const { error, setError, pending, run } = useSubmit(onDone, onClose)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [protect, setProtect] = useState(true)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void run(async () => {
      const created = await api.createOu({
        parent_dn: parentDn,
        name: name.trim(),
        description: description || undefined,
        protect_from_deletion: protect,
      })
      return t('status.created', { name: created.name })
    })
  }

  return (
    <Modal
      title={t('dialog.newOuTitle')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button type="submit" form="new-ou" className="button button--primary" disabled={pending}>
            {t('action.create')}
          </button>
        </>
      }
    >
      <form id="new-ou" onSubmit={submit} className="form">
        <ErrorMessage error={error} onDismiss={() => setError(null)} />
        <Field label={t('list.name')}>
          <input required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t('list.description')}>
          <input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <label className="checkbox">
          <input type="checkbox" checked={protect} onChange={(e) => setProtect(e.target.checked)} />
          <span>{t('dialog.protectFromDeletion')}</span>
        </label>
      </form>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Password, rename, delete
// ---------------------------------------------------------------------------

export function PasswordDialog({ dn, onClose, onDone }: DialogProps & { dn: string }) {
  const { t } = useI18n()
  const { error, setError, pending, run } = useSubmit(onDone, onClose)
  const [password, setPassword] = useState('')
  const [mustChange, setMustChange] = useState(true)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void run(async () => {
      await api.setPassword(dn, password, mustChange)
      return t('status.passwordSet')
    })
  }

  return (
    <Modal
      title={t('dialog.passwordTitle')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button type="submit" form="set-password" className="button button--primary" disabled={pending}>
            {t('action.save')}
          </button>
        </>
      }
    >
      <form id="set-password" onSubmit={submit} className="form">
        <ErrorMessage error={error} onDismiss={() => setError(null)} />
        <Field label={t('login.password')}>
          <input
            type="password"
            required
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={mustChange}
            onChange={(e) => setMustChange(e.target.checked)}
          />
          <span>{t('dialog.passwordMustChange')}</span>
        </label>
      </form>
    </Modal>
  )
}

export function RenameDialog({
  dn,
  currentName,
  onClose,
  onDone,
}: DialogProps & { dn: string; currentName: string }) {
  const { t } = useI18n()
  const { error, setError, pending, run } = useSubmit(onDone, onClose)
  const [name, setName] = useState(currentName)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void run(async () => {
      await api.rename(dn, name.trim())
      return t('status.saved')
    })
  }

  return (
    <Modal
      title={t('dialog.renameTitle')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button type="submit" form="rename" className="button button--primary" disabled={pending}>
            {t('action.save')}
          </button>
        </>
      }
    >
      <form id="rename" onSubmit={submit} className="form">
        <ErrorMessage error={error} onDismiss={() => setError(null)} />
        <Field label={t('list.name')}>
          <input required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
      </form>
    </Modal>
  )
}

export function DeleteDialog({
  dn,
  name,
  isContainer,
  isOu,
  onClose,
  onDone,
}: DialogProps & { dn: string; name: string; isContainer: boolean; isOu: boolean }) {
  const { t } = useI18n()
  const { error, setError, pending, run } = useSubmit(onDone, onClose)
  const [recursive, setRecursive] = useState(false)

  const submit = () => {
    void run(async () => {
      // OUs go through their own endpoint, which refuses while the object is
      // still protected instead of returning a bare access-denied.
      if (isOu) await api.deleteOu(dn, recursive)
      else await api.remove(dn, recursive)
      return t('status.deleted', { name })
    })
  }

  return (
    <Modal
      title={t('dialog.deleteTitle', { name })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button type="button" className="button button--danger" onClick={submit} disabled={pending}>
            {t('action.delete')}
          </button>
        </>
      }
    >
      <div className="form">
        <ErrorMessage error={error} onDismiss={() => setError(null)} />
        <p>{t('dialog.deleteBody')}</p>
        <p className="mono muted">{dn}</p>
        {isContainer && (
          <label className="checkbox">
            <input
              type="checkbox"
              checked={recursive}
              onChange={(e) => setRecursive(e.target.checked)}
            />
            <span>{t('dialog.deleteRecursive')}</span>
          </label>
        )}
      </div>
    </Modal>
  )
}
