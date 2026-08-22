import { useMemo, useState } from 'react'

import type { DirectoryObject } from '../api/types'
import { useI18n } from '../i18n'
import { anchorOf } from './ContextMenu'
import { Badge, Icon, useTypeLabel } from './primitives'

interface ObjectListProps {
  entries: DirectoryObject[]
  truncated?: boolean
  selectedDn: string | null
  onSelect: (object: DirectoryObject) => void
  onOpen?: (object: DirectoryObject) => void
  /**
   * A row was asked for its menu, and where to put it.
   *
   * The list says where and on what; what may be done there is decided by the
   * shell, which owns the dialogs and the writes.
   */
  onContext?: (object: DirectoryObject, at: { x: number; y: number }) => void
}

export function ObjectList({
  entries,
  truncated,
  selectedDn,
  onSelect,
  onOpen,
  onContext,
}: ObjectListProps) {
  const { t, tn } = useI18n()
  const typeLabel = useTypeLabel()
  const [filter, setFilter] = useState('')

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return entries
    // Client-side narrowing of what the server already returned; a wider search
    // is a separate, server-side query.
    return entries.filter((entry) =>
      [entry.name, entry.display_name, entry.description, entry.sam_account_name]
        .filter(Boolean)
        .some((value) => value!.toLowerCase().includes(needle)),
    )
  }, [entries, filter])

  return (
    <div className="list">
      <div className="list__toolbar">
        <input
          type="search"
          className="list__filter"
          placeholder={t('list.filter')}
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
        <span className="list__count">{tn('list.count', visible.length)}</span>
      </div>

      {truncated && <div className="alert alert--warning">{t('list.truncated')}</div>}

      {visible.length === 0 ? (
        <p className="list__empty">{t('list.empty')}</p>
      ) : (
        <table className="list__table">
          <thead>
            <tr>
              <th>{t('list.name')}</th>
              <th>{t('list.type')}</th>
              <th>{t('list.description')}</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((entry) => (
              <tr
                key={entry.dn}
                className={selectedDn === entry.dn ? 'list__row list__row--selected' : 'list__row'}
                onClick={() => onSelect(entry)}
                onDoubleClick={() => onOpen?.(entry)}
                onContextMenu={(event) => {
                  if (!onContext) return
                  event.preventDefault()
                  // Selected first, the way Windows does it — the menu acts on
                  // the row under the pointer, and the panes beside it should
                  // agree about which row that is.
                  onSelect(entry)
                  onContext(entry, { x: event.clientX, y: event.clientY })
                }}
                tabIndex={0}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') onOpen?.(entry)
                  if (event.key === ' ') {
                    event.preventDefault()
                    onSelect(entry)
                  }
                  // The keyboard way in. Without it the menu is not an
                  // equivalent of the right-click, only a shortcut for mice.
                  if ((event.shiftKey && event.key === 'F10') || event.key === 'ContextMenu') {
                    event.preventDefault()
                    onSelect(entry)
                    onContext?.(entry, anchorOf(event.currentTarget))
                  }
                }}
              >
                <td>
                  <span className="list__name">
                    <Icon type={entry.type} />
                    <span>{entry.display_name || entry.name}</span>
                    {entry.disabled && <Badge tone="muted">{t('user.status.disabled')}</Badge>}
                    {entry.primary_group_member && (
                      <Badge tone="muted">{t('group.primaryMember')}</Badge>
                    )}
                  </span>
                </td>
                <td>{typeLabel(entry.type)}</td>
                <td className="list__description">{entry.description ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
