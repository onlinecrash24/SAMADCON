import { useMemo, useState } from 'react'

import type { DirectoryObject } from '../api/types'
import { useI18n } from '../i18n'
import { LIST_LIMITS, isListLimit, type ListLimit } from '../state/listLimit'
import type { ListSort, SortColumn } from '../state/listSort'
import { DEFAULT_COLUMNS, columnDef } from '../state/listColumns'
import { ColumnsDialog } from './ColumnsDialog'
import { anchorOf } from './ContextMenu'
import { Badge, Icon, useDateFormat, useTypeLabel } from './primitives'

interface ObjectListProps {
  entries: DirectoryObject[]
  truncated?: boolean
  /**
   * How many the server was asked for, and the dial to change it. ADUC has
   * the same under View → Filter Options, and a 100 000-object OU is where
   * one finds out why: a fixed ceiling is right for nobody in particular.
   */
  limit?: ListLimit
  onLimitChange?: (limit: ListLimit) => void
  /** Which column the server sorted by; a click on a header asks for another. */
  sort?: ListSort
  onSortChange?: (column: SortColumn) => void
  /** Which columns to draw, name first. Without a handler the default three, fixed. */
  columns?: string[]
  onColumnsChange?: (columns: string[]) => void
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
  limit,
  onLimitChange,
  sort,
  onSortChange,
  columns = DEFAULT_COLUMNS,
  onColumnsChange,
  selectedDn,
  onSelect,
  onOpen,
  onContext,
}: ObjectListProps) {
  const { t, tn } = useI18n()
  const typeLabel = useTypeLabel()
  const formatDate = useDateFormat()
  const [filter, setFilter] = useState('')
  const [choosing, setChoosing] = useState(false)

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
        {onColumnsChange && (
          <button type="button" className="link list__columns" onClick={() => setChoosing(true)}>
            {t('columns.button')}
          </button>
        )}
        {limit !== undefined && onLimitChange && (
          <label className="list__limit">
            <span>{t('list.limit')}</span>
            <select
              value={limit}
              onChange={(event) => {
                const next = Number(event.target.value)
                if (isListLimit(next)) onLimitChange(next)
              }}
            >
              {LIST_LIMITS.map((choice) => (
                <option key={choice} value={choice}>
                  {choice.toLocaleString()}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {choosing && onColumnsChange && (
        <ColumnsDialog
          columns={columns}
          onClose={() => setChoosing(false)}
          onSave={(next) => {
            onColumnsChange(next)
            setChoosing(false)
          }}
        />
      )}

      {truncated && (
        <div className="alert alert--warning">
          {limit !== undefined
            ? t('list.truncatedAt', { limit: limit.toLocaleString() })
            : t('list.truncated')}
        </div>
      )}

      {visible.length === 0 ? (
        <p className="list__empty">{t('list.empty')}</p>
      ) : (
        <table className="list__table">
          <thead>
            <tr>
              {columns.map((id) => (
                <SortHeader
                  key={id}
                  column={id}
                  label={t(columnDef(id)?.label ?? 'list.name')}
                  sort={sort}
                  onSort={onSortChange}
                />
              ))}
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
                {columns.map((id) =>
                  id === 'name' ? (
                <td key={id}>
                  <span className="list__name">
                    <Icon type={entry.type} />
                    <span
                      title={
                        entry.display_name && entry.display_name !== entry.name
                          ? entry.display_name
                          : undefined
                      }
                    >
                      {entry.name}
                    </span>
                    {entry.disabled && <Badge tone="muted">{t('user.status.disabled')}</Badge>}
                    {entry.primary_group_member && (
                      <Badge tone="muted">{t('group.primaryMember')}</Badge>
                    )}
                  </span>
                </td>
                  ) : id === 'type' ? (
                    <td key={id}>{typeLabel(entry.type)}</td>
                  ) : id === 'description' ? (
                    <td key={id} className="list__description">{entry.description ?? ''}</td>
                  ) : (
                    <td key={id} className="list__description">
                      {columnDef(id)?.kind === 'date'
                        ? formatDate(entry.columns?.[id] ?? null)
                        : (entry.columns?.[id] ?? '')}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/**
 * A column header that sorts. Without a handler it is a plain header, which
 * is what the pickers get: they show a handful of candidates and have no
 * server sort to ask for.
 *
 * aria-sort on the cell, so a screen reader hears which column the list is
 * ordered by; the arrow is for everyone else, and is drawn only on that one
 * column — three arrows would say nothing.
 */
function SortHeader({
  column,
  label,
  sort,
  onSort,
}: {
  column: SortColumn
  label: string
  sort?: ListSort
  onSort?: (column: SortColumn) => void
}) {
  const active = sort?.column === column
  const direction = active ? (sort.descending ? 'descending' : 'ascending') : undefined
  if (!onSort) return <th>{label}</th>
  return (
    <th aria-sort={direction ?? 'none'}>
      <button type="button" className="list__sort" onClick={() => onSort(column)}>
        {label}
        {active && (
          <span className="list__sort-arrow" aria-hidden="true">
            {sort.descending ? '\u25BE' : '\u25B4'}
          </span>
        )}
      </button>
    </th>
  )
}
