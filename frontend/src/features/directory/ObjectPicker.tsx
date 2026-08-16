/**
 * Picking a directory object by searching for it.
 *
 * Used wherever the API wants a DN or a SID that nobody would type by hand:
 * group members, permission trustees, the manager field.
 */

import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api } from '../../api/endpoints'
import type { DirectoryObject, ObjectType } from '../../api/types'
import { Field, Icon, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'

/**
 * Searching on every keystroke would hammer the DC, but a minimum length is
 * the wrong brake: plenty of groups are called "IT", "HR" or "QA", and
 * requiring three characters makes them unfindable. Waiting for a pause in
 * typing achieves the same without excluding anything.
 */
const SEARCH_DELAY_MS = 300
const MAX_RESULTS = 20

function useDebounced<T>(value: T, delay = SEARCH_DELAY_MS): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return settled
}

interface ObjectPickerProps {
  types: ObjectType[]
  label?: MessageKey
  /** Already-chosen DNs, greyed out so they cannot be added twice. */
  exclude?: Set<string>
  onSelect: (object: DirectoryObject) => void
}

export function ObjectPicker({ types, label, exclude, onSelect }: ObjectPickerProps) {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const settled = useDebounced(query.trim())

  const results = useQuery({
    queryKey: ['object-search', settled, types.join(',')],
    queryFn: () => api.search(settled, { types }),
    enabled: settled.length > 0,
  })

  return (
    <Field label={t(label ?? 'security.account')} hint={t('security.accountHint')}>
      <input
        type="search"
        autoFocus
        value={query}
        placeholder={t('nav.search')}
        onChange={(event) => setQuery(event.target.value)}
      />

      {(results.isFetching || settled !== query.trim()) && <Spinner />}

      {results.data && (
        <ul className="picker__results">
          {results.data.entries.slice(0, MAX_RESULTS).map((entry) => {
            const already = exclude?.has(entry.dn.toLowerCase()) ?? false
            return (
              <li key={entry.dn}>
                <button
                  type="button"
                  className="link"
                  disabled={already}
                  onClick={() => onSelect(entry)}
                >
                  <Icon type={entry.type} />
                  <span>{entry.display_name || entry.name}</span>
                  {entry.sam_account_name && (
                    <span className="muted small">{entry.sam_account_name}</span>
                  )}
                  {already && <span className="muted small">✓</span>}
                </button>
              </li>
            )
          })}
          {results.data.entries.length === 0 && <li className="muted small">{t('list.empty')}</li>}
        </ul>
      )}
    </Field>
  )
}

/** The chosen object, with a way back to the search. */
export function ChosenObject({
  object,
  onClear,
  label,
}: {
  object: DirectoryObject
  onClear: () => void
  label?: MessageKey
}) {
  const { t } = useI18n()
  return (
    <Field label={t(label ?? 'security.account')}>
      <div className="picker__chosen">
        <Icon type={object.type} />
        <span>{object.display_name || object.name}</span>
        <button type="button" className="link" onClick={onClear}>
          {t('action.change')}
        </button>
      </div>
    </Field>
  )
}
