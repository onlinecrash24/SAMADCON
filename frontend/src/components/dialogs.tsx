/** Dialogs for the create/rename/delete/password actions. */

import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { ApiError } from '../api/client'
import { api } from '../api/endpoints'
import type { TreeNode } from '../api/types'
import { isAtOrBelow } from '../dn'
import { useI18n } from '../i18n'
import { ErrorMessage, Field, Modal, Spinner } from './primitives'

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
// Move
// ---------------------------------------------------------------------------

export function MoveDialog({
  dn,
  name,
  onClose,
  onDone,
}: DialogProps & { dn: string; name: string }) {
  const { t } = useI18n()
  const { error, setError, pending, run } = useSubmit(onDone, onClose)

  // The partition the object lives in, taken from its own name. Derived
  // rather than passed in, and not because it saves a prop: an object cannot
  // move across partitions, so the only correct root is the one it is
  // already under. A root handed down from the console shell could be the
  // configuration partition, and every target under it would be refused.
  const baseDn = dn.slice(dn.search(/DC=/i))

  // Where the picker is looking, which is also the target. There is no
  // separate "selected" state on purpose: one of them would end up stale, and
  // the one that decides where an object lands should be the one on screen.
  const [target, setTarget] = useState(baseDn)

  const listing = useQuery({
    queryKey: ['move-target', target],
    queryFn: () => api.tree(target),
  })

  // A container cannot be moved into itself or into anything below it. The
  // server would let rename fail with a bare LDAP error; saying it here means
  // the button is simply not available for a move that cannot work.
  const inside = (candidate: string) => isAtOrBelow(candidate, dn)

  const parentOf = (child: string) => child.slice(child.indexOf(',') + 1)
  const canAscend = target.toLowerCase() !== baseDn.toLowerCase()

  const unchanged = parentOf(dn).toLowerCase() === target.toLowerCase()
  const refused = inside(target)

  const submit = () => {
    void run(async () => {
      const result = await api.move(dn, target)
      // The DN changed, so the caller has to follow it — otherwise the detail
      // pane keeps pointing at something that no longer exists.
      return t('status.moved', { name, target: result.dn })
    })
  }

  return (
    <Modal
      title={t('dialog.moveTitle', { name })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={pending || refused || unchanged}
            onClick={submit}
          >
            {t('action.move')}
          </button>
        </>
      }
    >
      <div className="form">
        <ErrorMessage error={error} onDismiss={() => setError(null)} />

        <p className="muted small">{t('dialog.moveHint')}</p>

        <Field label={t('dialog.moveTarget')}>
          <code className="mono small">{target}</code>
        </Field>

        {refused && <div className="alert alert--warning">{t('dialog.moveIntoItself')}</div>}
        {unchanged && !refused && <p className="muted small">{t('dialog.moveUnchanged')}</p>}

        <div className="pane__actions">
          <button
            type="button"
            className="button"
            disabled={!canAscend}
            onClick={() => setTarget(parentOf(target))}
          >
            {t('dialog.moveUp')}
          </button>
        </div>

        {listing.isLoading && <Spinner label={t('status.loading')} />}
        {listing.error && <ErrorMessage error={listing.error} />}

        <ul className="plain-list">
          {(listing.data?.nodes ?? []).map((node: TreeNode) => (
            <li key={node.dn}>
              <button
                type="button"
                className="button"
                // Descending into the object being moved is pointless: every
                // container under it is refused anyway.
                disabled={inside(node.dn)}
                onClick={() => setTarget(node.dn)}
              >
                {node.name}
              </button>
            </li>
          ))}
        </ul>

        {(listing.data?.nodes ?? []).length === 0 && !listing.isLoading && (
          <p className="muted small">{t('dialog.moveNoChildren')}</p>
        )}
      </div>
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

  // The refusal delete_ou gives while the OU is protected. Recognised rather
  // than shown as one more failure, because it is the one failure here with a
  // sensible next step — and without offering that step, a correct refusal
  // reads as a dead end.
  const isProtected = error instanceof ApiError && error.code === 'delete_protected'

  const remove = async () => {
    if (isOu) await api.deleteOu(dn, recursive)
    else await api.remove(dn, recursive)
    return t('status.deleted', { name })
  }

  const submit = () => {
    void run(remove)
  }

  const unprotectAndDelete = () => {
    void run(async () => {
      // Two writes, in this order, and the text above says so. If the delete
      // fails on something else afterwards, the protection is gone regardless.
      await api.setDeleteProtection(dn, false)
      return await remove()
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
          {isProtected ? (
            // Replaces the plain delete rather than sitting beside it: with
            // both on screen, the one that cannot work is the one people press.
            <button
              type="button"
              className="button button--danger"
              onClick={unprotectAndDelete}
              disabled={pending}
            >
              {t('action.unprotectAndDelete')}
            </button>
          ) : (
            <button
              type="button"
              className="button button--danger"
              onClick={submit}
              disabled={pending}
            >
              {t('action.delete')}
            </button>
          )}
        </>
      }
    >
      <div className="form">
        <ErrorMessage error={error} onDismiss={() => setError(null)} />
        {isProtected ? (
          <p>{t('dialog.deleteProtectedBody')}</p>
        ) : (
          <p>{t('dialog.deleteBody')}</p>
        )}
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
