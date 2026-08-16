/**
 * The administrative templates of one GPO.
 *
 * Laid out like the Windows editor, because the arrangement is not decoration:
 * the tree on the left *is* the vocabulary — people find a setting by
 * remembering roughly where Microsoft put it — and the state column on the
 * right is the one thing you cannot see from the tree. Both panes scroll on
 * their own so the window never scrolls as a whole.
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../../api/endpoints'
import type { AdmxCategory, AdmxPolicySummary, Gpo, PolicyState } from '../../../api/types'
import { ErrorMessage, Spinner } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import type { MessageKey } from '../../../i18n/messages'
import { PolicyDialog } from './PolicyDialog'
import { TemplateUpload } from './TemplateUpload'
import { admlLanguage } from './language'

type Half = 'Machine' | 'User'

export function AdmxTab({ gpo, onChanged }: { gpo: Gpo; onChanged: (message: string) => void }) {
  const { t, language } = useI18n()
  const wanted = admlLanguage(language)

  const [half, setHalf] = useState<Half>('Machine')
  const [category, setCategory] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [active, setActive] = useState('')
  const [onlyConfigured, setOnlyConfigured] = useState(false)
  const [editing, setEditing] = useState<AdmxPolicySummary | null>(null)

  const store = useQuery({ queryKey: ['admx-store'], queryFn: () => api.admxStore() })

  const tree = useQuery({
    // `onlyConfigured` belongs in the key: it changes what the server sends
    // back, not just how it is drawn.
    queryKey: ['admx-tree', category, half, gpo.dn, wanted, onlyConfigured],
    queryFn: () => api.admxTree(category, half, gpo.dn, wanted, onlyConfigured),
    enabled: Boolean(store.data?.present) && active === '',
  })

  const found = useQuery({
    queryKey: ['admx-search', active, half, gpo.dn, wanted],
    queryFn: () => api.admxSearch(active, half, gpo.dn, wanted),
    enabled: active !== '',
  })

  if (store.isLoading) return <Spinner label={t('status.loading')} />
  if (store.error) return <ErrorMessage error={store.error} />

  if (!store.data?.present) {
    return <TemplateUpload store={store.data} onDone={() => void store.refetch()} />
  }

  const listing = active ? found : tree
  const all = active ? (found.data?.policies ?? []) : (tree.data?.policies ?? [])
  // The search path has no server-side filter, so it still needs this one.
  // The tree comes back filtered already, and re-filtering it costs nothing.
  const policies = onlyConfigured
    ? all.filter((policy) => policy.state && policy.state !== 'not_configured')
    : all
  const categories = active ? [] : (tree.data?.categories ?? [])

  return (
    <div className="gpedit">
      <div className="gpedit__bar">
        <div className="tabs">
          {(['Machine', 'User'] as Half[]).map((id) => (
            <button
              key={id}
              type="button"
              className={half === id ? 'tabs__tab tabs__tab--active' : 'tabs__tab'}
              onClick={() => {
                setHalf(id)
                setCategory(null)
              }}
            >
              {id === 'Machine' ? t('admx.machineHalf') : t('admx.userHalf')}
            </button>
          ))}
        </div>

        <div className="gpedit__bar-right">
          <label className="checkbox checkbox--inline">
            <input
              type="checkbox"
              checked={onlyConfigured}
              onChange={(event) => setOnlyConfigured(event.target.checked)}
            />
            <span>{t('admx.onlyConfigured')}</span>
          </label>

          <form
            onSubmit={(event) => {
              event.preventDefault()
              setActive(search.trim())
            }}
          >
            <input
              type="search"
              value={search}
              placeholder={t('admx.search')}
              onChange={(event) => {
                setSearch(event.target.value)
                if (event.target.value === '') setActive('')
              }}
            />
          </form>
        </div>
      </div>

      {/* Asked for one language, got another. The server falls back rather
          than showing a tree with no labels, but silently ending up in English
          after switching the console to German looks like a bug in the console
          instead of a gap in the domain's store.

          Only the language is compared, and without case: a store that grew
          over time holds `de-de` next to `de-DE`, and `de-AT` is German too. */}
      {tree.data?.language &&
        tree.data.language.toLowerCase().split('-')[0] !== wanted.toLowerCase().split('-')[0] && (
          <p className="muted small">
            {t('admx.languageFallback', { wanted, used: tree.data.language })}
          </p>
        )}

      <div className="gpedit__panes">
        <nav className="gpedit__tree" aria-label={t('admx.categories')}>
          <CategoryTree
            root={half === 'Machine' ? t('admx.machineHalf') : t('admx.userHalf')}
            categories={categories}
            path={tree.data?.path ?? []}
            selected={category}
            disabled={active !== ''}
            onSelect={(id) => {
              setActive('')
              setSearch('')
              setCategory(id)
            }}
          />
        </nav>

        <section className="gpedit__list">
          <ErrorMessage error={listing.error} />
          {listing.isLoading && <Spinner label={t('status.loading')} />}

          {active && <p className="muted small">{t('admx.searchHint', { query: active })}</p>}

          <div className="table-wrap">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th>{t('admx.setting')}</th>
                  <th className="table__cell--narrow">{t('admx.state')}</th>
                  <th className="table__cell--narrow">{t('admx.appliesTo')}</th>
                </tr>
              </thead>
              <tbody>
                {policies.map((policy) => (
                  <tr key={policy.id} onDoubleClick={() => setEditing(policy)}>
                    <td>
                      <button type="button" className="link" onClick={() => setEditing(policy)}>
                        {policy.display_name}
                      </button>
                    </td>
                    <td>
                      <StateLabel state={policy.state} />
                    </td>
                    <td className="muted small">
                      {t(`admx.class.${policy.class}` as MessageKey)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {!listing.isLoading && policies.length === 0 && (
            <p className="muted">
              {/* With the filter on, an empty pane always means the same
                  thing — the server has already removed everything that is
                  not configured, so "pick a category" would point at a tree
                  that may have nothing left to pick. */}
              {active
                ? t('admx.nothingFound')
                : onlyConfigured
                  ? t('admx.noneConfigured')
                  : category === null
                    ? t('admx.pickCategory')
                    : t('admx.noSettings')}
            </p>
          )}
        </section>
      </div>

      {editing && (
        <PolicyDialog
          gpo={gpo}
          policy={editing}
          half={half === 'Machine' || editing.halves.includes(half) ? half : editing.halves[0]!}
          onClose={() => setEditing(null)}
          onSaved={(message) => {
            setEditing(null)
            void listing.refetch()
            onChanged(message)
          }}
        />
      )}
    </div>
  )
}

/**
 * The state as a word, not a colour.
 *
 * "Not configured" is the overwhelming majority and must not shout: it is the
 * two other states one scans a long list for.
 */
function StateLabel({ state }: { state?: PolicyState }) {
  const { t } = useI18n()
  if (!state || state === 'not_configured') {
    return <span className="muted small">{t('admx.state.not_configured')}</span>
  }
  return (
    <span className={state === 'enabled' ? 'state state--on' : 'state state--off'}>
      {t(`admx.state.${state}` as MessageKey)}
    </span>
  )
}

/**
 * One level at a time, with the way back above it.
 *
 * The full tree would mean loading the whole store — several thousand
 * categories on a domain with the Microsoft templates installed — to draw
 * something of which one branch is open.
 */
function CategoryTree({
  root,
  categories,
  path,
  selected,
  disabled,
  onSelect,
}: {
  root: string
  categories: AdmxCategory[]
  path: { id: string; display_name: string }[]
  selected: string | null
  disabled: boolean
  onSelect: (id: string | null) => void
}) {
  return (
    <ul className="cats">
      <li>
        <button
          type="button"
          className={selected === null && !disabled ? 'cats__node cats__node--active' : 'cats__node'}
          onClick={() => onSelect(null)}
        >
          {root}
        </button>
      </li>

      {path.map((item, depth) => (
        <li key={item.id} style={{ paddingLeft: `${(depth + 1) * 0.9}rem` }}>
          <button
            type="button"
            className={
              item.id === selected && !disabled ? 'cats__node cats__node--active' : 'cats__node'
            }
            onClick={() => onSelect(item.id)}
          >
            {item.display_name}
          </button>
        </li>
      ))}

      {categories.map((item) => (
        <li key={item.id} style={{ paddingLeft: `${(path.length + 1) * 0.9}rem` }}>
          <button type="button" className="cats__node" onClick={() => onSelect(item.id)}>
            <span className="cats__twisty">{item.has_children ? '▸' : '·'}</span>
            <span className="cats__name">{item.display_name}</span>
            {item.policy_count > 0 && (
              <span className="muted small">{item.policy_count}</span>
            )}
          </button>
        </li>
      ))}
    </ul>
  )
}
