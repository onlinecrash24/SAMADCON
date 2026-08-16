/**
 * Editable property sheet.
 *
 * Only changed fields are sent: a PATCH that repeats unchanged values would
 * bump whenChanged on every save and fill the audit log with entries that
 * record nothing. The backend also skips no-op writes, but the diff belongs on
 * this side too — it is what the "unsaved changes" state is built from.
 */

import { useMemo, useState, type FormEvent } from 'react'

import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'
import { Badge, ErrorMessage, Field } from '../../components/primitives'
import { ACCOUNT_FLAGS, DANGEROUS_FLAGS, type FieldGroup } from './fieldDefs'

type Attributes = Record<string, string | null>
type Flags = Record<string, boolean>

interface PropertySheetProps {
  groups: FieldGroup[]
  attributes: Attributes
  /** Present for object types that carry userAccountControl. */
  flags?: Flags
  saving: boolean
  error: unknown
  onDismissError: () => void
  onSave: (changes: { attributes?: Attributes; flags?: Flags }) => void
}

export function PropertySheet({
  groups,
  attributes,
  flags,
  saving,
  error,
  onDismissError,
  onSave,
}: PropertySheetProps) {
  const { t } = useI18n()

  // Drafts hold only what the user touched; everything else falls back to the
  // value loaded from the directory.
  const [draft, setDraft] = useState<Attributes>({})
  const [flagDraft, setFlagDraft] = useState<Flags>({})

  const value = (name: string): string =>
    (name in draft ? draft[name] : attributes[name]) ?? ''

  const flagValue = (name: string): boolean =>
    name in flagDraft ? flagDraft[name]! : Boolean(flags?.[name])

  const changedAttributes = useMemo(() => {
    const result: Attributes = {}
    for (const [name, next] of Object.entries(draft)) {
      const current = attributes[name] ?? ''
      const trimmed = (next ?? '').trim()
      if (trimmed === (current ?? '')) continue
      // An emptied field means "remove the attribute", which the API expresses
      // as null rather than an empty string.
      result[name] = trimmed === '' ? null : trimmed
    }
    return result
  }, [draft, attributes])

  const changedFlags = useMemo(() => {
    const result: Flags = {}
    for (const [name, next] of Object.entries(flagDraft)) {
      if (Boolean(flags?.[name]) !== next) result[name] = next
    }
    return result
  }, [flagDraft, flags])

  const attributeCount = Object.keys(changedAttributes).length
  const flagCount = Object.keys(changedFlags).length
  const dirty = attributeCount + flagCount > 0

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!dirty) return
    onSave({
      ...(attributeCount ? { attributes: changedAttributes } : {}),
      ...(flagCount ? { flags: changedFlags } : {}),
    })
    // The drafts are cleared by the parent remounting this component with
    // fresh data once the save succeeded; on failure they stay, so the user
    // does not lose what they typed.
  }

  const discard = () => {
    setDraft({})
    setFlagDraft({})
    onDismissError()
  }

  return (
    <form className="sheet" onSubmit={submit}>
      <ErrorMessage error={error} onDismiss={onDismissError} />

      {groups.map((group) => (
        <section className="detail__section" key={group.title}>
          <h3>{t(group.title)}</h3>
          {group.fields.map((field) => (
            <Field
              key={field.name}
              label={t(field.label)}
              hint={field.hint ? t(field.hint) : undefined}
            >
              {field.kind === 'multiline' ? (
                <textarea
                  rows={2}
                  value={value(field.name)}
                  maxLength={field.maxLength}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, [field.name]: event.target.value }))
                  }
                />
              ) : (
                <input
                  // 'multiline' is handled by the branch above, so what
                  // remains maps directly onto an input type.
                  type={field.kind ?? 'text'}
                  value={value(field.name)}
                  maxLength={field.maxLength}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, [field.name]: event.target.value }))
                  }
                />
              )}
            </Field>
          ))}
        </section>
      ))}

      {flags && (
        <section className="detail__section">
          <h3>{t('detail.accountOptions')}</h3>
          {ACCOUNT_FLAGS.filter((name) => name in flags).map((name) => (
            <label className="checkbox" key={name}>
              <input
                type="checkbox"
                checked={flagValue(name)}
                onChange={(event) =>
                  setFlagDraft((current) => ({ ...current, [name]: event.target.checked }))
                }
              />
              <span>
                {t(`flag.${name}` as MessageKey)}
                {DANGEROUS_FLAGS.has(name) && flagValue(name) && (
                  <Badge tone="danger">{t('flag.dangerous')}</Badge>
                )}
              </span>
            </label>
          ))}
        </section>
      )}

      <div className="sheet__actions">
        <span className="muted small">
          {dirty ? t('detail.unsaved') : t('detail.noChanges')}
        </span>
        <div className="sheet__buttons">
          <button type="button" className="button" onClick={discard} disabled={!dirty || saving}>
            {t('action.discard')}
          </button>
          <button type="submit" className="button button--primary" disabled={!dirty || saving}>
            {t('action.save')}
          </button>
        </div>
      </div>
    </form>
  )
}
