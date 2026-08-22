/**
 * Startup, shutdown, logon and logoff scripts of one GPO.
 *
 * Laid out like the Windows editor: the events on the left, the scripts of the
 * selected one on the right, in the order they run.
 *
 * The two engines are separate tabs rather than one merged list, and that is
 * not a simplification — `scripts.ini` and `psscripts.ini` each carry their
 * own numbering, and what decides which of the two goes first is a single flag
 * for the whole event, not their position in a list. A merged, reorderable
 * list would promise something the format cannot keep.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { api } from '../../../api/endpoints'
import type { Gpo, ScriptEngine, ScriptEntry, ScriptEvent, ScriptFile } from '../../../api/types'
import { ErrorMessage, Spinner } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import type { MessageKey } from '../../../i18n/messages'

type Half = 'Machine' | 'User'

const EVENTS: Record<Half, ScriptEvent[]> = {
  Machine: ['Startup', 'Shutdown'],
  User: ['Logon', 'Logoff'],
}

interface Draft {
  command: string
  parameters: string
}

export function ScriptsTab({ gpo, onChanged }: { gpo: Gpo; onChanged: (message: string) => void }) {
  const { t } = useI18n()

  const [half, setHalf] = useState<Half>('Machine')
  const [event, setEvent] = useState<ScriptEvent>('Startup')
  const [engine, setEngine] = useState<ScriptEngine>('cmd')
  const [draft, setDraft] = useState<Draft[]>([])
  const [error, setError] = useState<unknown>(null)

  const listing = useQuery({
    queryKey: ['gpo-scripts', gpo.dn, half],
    queryFn: () => api.gpoScripts(gpo.dn, half),
  })

  // The draft is what the form edits; it is refilled whenever the answer, the
  // event or the engine changes, and the list is only ever sent whole.
  useEffect(() => {
    const entries = listing.data?.events?.[event] ?? []
    setDraft(
      entries
        .filter((item) => item.engine === engine)
        .map((item) => ({ command: item.command, parameters: item.parameters })),
    )
  }, [listing.data, event, engine])

  const save = useMutation({
    mutationFn: () =>
      api.setGpoScripts(gpo.dn, {
        half,
        event,
        engine,
        scripts: draft.filter((item) => item.command.trim() !== ''),
        expected_version: listing.data?.version,
      }),
    onSuccess: (result) => {
      void listing.refetch()
      onChanged(result.changed ? t('scripts.saved') : t('scripts.unchanged'))
    },
    onError: setError,
  })

  if (listing.isLoading) return <Spinner label={t('status.loading')} />
  if (listing.error) return <ErrorMessage error={listing.error} />

  const move = (index: number, by: number) => {
    const next = [...draft]
    const target = index + by
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target]!, next[index]!]
    setDraft(next)
  }

  const edit = (index: number, field: keyof Draft, value: string) => {
    setDraft(draft.map((item, at) => (at === index ? { ...item, [field]: value } : item)))
  }

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
                setEvent(EVENTS[id][0]!)
              }}
            >
              {t(id === 'Machine' ? 'admx.machineHalf' : 'admx.userHalf')}
            </button>
          ))}
        </div>

        <div className="gpedit__bar-right">
          <div className="tabs">
            {(['cmd', 'powershell'] as ScriptEngine[]).map((id) => (
              <button
                key={id}
                type="button"
                className={engine === id ? 'tabs__tab tabs__tab--active' : 'tabs__tab'}
                onClick={() => setEngine(id)}
              >
                {t(`scripts.engine.${id}` as MessageKey)}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* The trap no other console shows: scripts written into a policy whose
          extension is not registered are run by nobody. */}
      {!listing.data?.registered && hasAny(listing.data?.events) && (
        <div className="alert alert--warning">{t('scripts.notRegistered')}</div>
      )}

      <div className="gpedit__panes">
        <nav className="gpedit__tree" aria-label={t('scripts.events')}>
          <ul className="cats">
            {EVENTS[half].map((id) => (
              <li key={id}>
                <button
                  type="button"
                  className={event === id ? 'cats__node cats__node--active' : 'cats__node'}
                  onClick={() => setEvent(id)}
                >
                  <span className="cats__name">{t(`scripts.event.${id}` as MessageKey)}</span>
                  <Count entries={listing.data?.events?.[id]} />
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <section className="gpedit__list">
          <ErrorMessage error={error} onDismiss={() => setError(null)} />

          <p className="muted small">{t('scripts.orderHint')}</p>

          <div className="table-wrap">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th className="table__cell--narrow">#</th>
                  <th>{t('scripts.command')}</th>
                  <th>{t('scripts.parameters')}</th>
                  <th className="table__cell--narrow" />
                </tr>
              </thead>
              <tbody>
                {draft.map((item, index) => (
                  <tr key={index}>
                    <td className="muted small">{index + 1}</td>
                    <td>
                      <input
                        value={item.command}
                        onChange={(change) => edit(index, 'command', change.target.value)}
                      />
                    </td>
                    <td>
                      <input
                        value={item.parameters}
                        onChange={(change) => edit(index, 'parameters', change.target.value)}
                      />
                    </td>
                    <td>
                      <div className="pane__actions">
                        <button
                          type="button"
                          className="button"
                          disabled={index === 0}
                          onClick={() => move(index, -1)}
                          aria-label={t('scripts.moveUp')}
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          className="button"
                          disabled={index === draft.length - 1}
                          onClick={() => move(index, 1)}
                          aria-label={t('scripts.moveDown')}
                        >
                          ↓
                        </button>
                        <button
                          type="button"
                          className="button button--danger"
                          onClick={() => setDraft(draft.filter((_, at) => at !== index))}
                        >
                          {t('action.remove')}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {draft.length === 0 && <p className="muted">{t('scripts.none')}</p>}

          <div className="pane__actions">
            <button
              type="button"
              className="button"
              onClick={() => setDraft([...draft, { command: '', parameters: '' }])}
            >
              + {t('scripts.add')}
            </button>
            <button
              type="button"
              className="button button--primary"
              disabled={save.isPending}
              onClick={() => save.mutate()}
            >
              {t('action.save')}
            </button>
          </div>

          <Files dn={gpo.dn} half={half} event={event} onChanged={onChanged} />
        </section>
      </div>
    </div>
  )
}


/**
 * The files in one event's directory on the share.
 *
 * Storing one does not schedule it. That separation is the point rather than
 * an omission: a helper script another one calls belongs on the share and not
 * in the list of things to run, and the console should not decide otherwise on
 * someone's behalf.
 */
function Files({
  dn,
  half,
  event,
  onChanged,
}: {
  dn: string
  half: Half
  event: ScriptEvent
  onChanged: (message: string) => void
}) {
  const { t } = useI18n()
  const [error, setError] = useState<unknown>(null)
  const picker = useRef<HTMLInputElement>(null)

  const listing = useQuery({
    // The directory is per half and per event, exactly as the endpoints are.
    queryKey: ['gpo-script-files', dn, half, event],
    queryFn: () => api.gpoScriptFiles(dn, half, event),
  })

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadGpoScriptFile(dn, half, event, file),
    onSuccess: (result) => {
      void listing.refetch()
      onChanged(t('scripts.fileStored', { name: result.name }))
    },
    onError: setError,
  })

  const remove = useMutation({
    mutationFn: (name: string) => api.deleteGpoScriptFile(dn, half, event, name),
    onSuccess: (result) => {
      void listing.refetch()
      onChanged(t('scripts.fileRemoved', { name: result.removed }))
    },
    onError: setError,
  })

  const files: ScriptFile[] = listing.data?.files ?? []

  return (
    <section className="stack">
      <h4>{t('scripts.files')}</h4>
      <p className="muted small">{t('scripts.filesHint')}</p>

      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      {listing.isLoading && <Spinner label={t('status.loading')} />}
      {listing.error && <ErrorMessage error={listing.error} />}

      {files.length === 0 && !listing.isLoading && (
        <p className="muted">{t('scripts.noFiles')}</p>
      )}

      {files.length > 0 && (
        <div className="table-wrap">
          <table className="table table--compact">
            <thead>
              <tr>
                <th>{t('scripts.fileName')}</th>
                <th className="table__cell--narrow">{t('scripts.fileSize')}</th>
                <th className="table__cell--narrow" />
              </tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <tr key={file.name}>
                  <td className="mono small">{file.name}</td>
                  <td className="muted small">{bytes(file.size)}</td>
                  <td>
                    <div className="pane__actions">
                      <button
                        type="button"
                        className="button"
                        onClick={() => void api.downloadGpoScriptFile(dn, half, event, file.name)}
                      >
                        {t('scripts.download')}
                      </button>
                      <button
                        type="button"
                        className="button button--danger"
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(file.name)}
                      >
                        {t('action.remove')}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="pane__actions">
        <button
          type="button"
          className="button"
          disabled={upload.isPending}
          onClick={() => picker.current?.click()}
        >
          {upload.isPending ? t('scripts.storing') : t('scripts.addFile')}
        </button>
        <input
          ref={picker}
          type="file"
          hidden
          onChange={(change) => {
            const file = change.target.files?.[0]
            // Cleared so the same file can be picked twice in a row — after a
            // failed upload that is exactly what someone tries.
            change.target.value = ''
            if (file) upload.mutate(file)
          }}
        />
      </div>
    </section>
  )
}

/** Sizes a reader can weigh, without pretending to more precision than matters. */
function bytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function Count({ entries }: { entries?: ScriptEntry[] }) {
  if (!entries || entries.length === 0) return null
  return <span className="muted small">{entries.length}</span>
}

function hasAny(events?: Record<string, ScriptEntry[]>): boolean {
  return Object.values(events ?? {}).some((entries) => entries.length > 0)
}
