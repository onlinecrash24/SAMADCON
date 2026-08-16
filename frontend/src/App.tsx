import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { ApiError } from './api/client'
import { api } from './api/endpoints'
import type { DirectoryObject } from './api/types'
import { DetailPane } from './components/DetailPane'
import { LoginView } from './components/LoginView'
import { LogoMark } from './components/Logo'
import { ObjectList } from './components/ObjectList'
import { TreePane } from './components/TreePane'
import {
  NewComputerDialog,
  NewGroupDialog,
  NewOuDialog,
  NewUserDialog,
} from './components/dialogs'
import { ErrorMessage, Icon, Spinner } from './components/primitives'
import type { DnsZone } from './api/types'
import { SNAPINS, type SnapinId } from './features/console/snapins'
import { DiagnosticsView } from './features/diagnostics/DiagnosticsView'
import { DnsView } from './features/dns/DnsView'
import { GpoView } from './features/gpo/GpoView'
import { SitesView } from './features/sites/SitesView'
import { useI18n } from './i18n'
import { useSession } from './state/session'

type NewObjectKind = 'user' | 'group' | 'computer' | 'ou' | null

/** Stands in for a console that is planned but not built yet. */
function SnapinPlaceholder({ id }: { id: SnapinId }) {
  const { t } = useI18n()
  const snapin = SNAPINS.find((entry) => entry.id === id)
  if (!snapin) return null

  return (
    <div className="placeholder">
      <Icon type={snapin.icon} className="icon--large" />
      <h2>{t(snapin.label)}</h2>
      {snapin.note && <p className="muted">{t(snapin.note)}</p>}
    </div>
  )
}

export function App() {
  const { session, loading } = useSession()
  const { t } = useI18n()

  if (loading) {
    return (
      <div className="boot">
        <Spinner label={t('status.loading')} />
      </div>
    )
  }

  return session ? <Console /> : <LoginView />
}

function Console() {
  const { t, language, setLanguage } = useI18n()
  const { session, logout, expire } = useSession()
  const queryClient = useQueryClient()

  const baseDn = session!.domain.base_dn
  const [currentDn, setCurrentDn] = useState(baseDn)
  const [selected, setSelected] = useState<DirectoryObject | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [activeSearch, setActiveSearch] = useState('')
  const [newObject, setNewObject] = useState<NewObjectKind>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [navigationError, setNavigationError] = useState<unknown>(null)
  const [snapin, setSnapin] = useState<SnapinId>('directory')
  const [dnsZone, setDnsZone] = useState<DnsZone | null>(null)

  const children = useQuery({
    queryKey: ['children', currentDn, showAdvanced],
    queryFn: () => api.children(currentDn, { advanced: showAdvanced }),
    enabled: activeSearch === '',
  })

  const search = useQuery({
    queryKey: ['search', activeSearch],
    queryFn: () => api.search(activeSearch),
    enabled: activeSearch !== '',
  })

  const active = activeSearch ? search : children
  const entries = activeSearch ? (search.data?.entries ?? []) : (children.data?.entries ?? [])

  // Any 401 means the ticket is gone; drop straight back to the login view
  // rather than letting every panel fail on its own.
  useEffect(() => {
    const error = active.error
    if (error instanceof ApiError && error.isUnauthenticated) expire()
  }, [active.error, expire])

  // Transient success messages should not linger.
  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), 4000)
    return () => window.clearTimeout(timer)
  }, [notice])

  /**
   * Follow a DN from the detail pane (a group member, a parent group).
   * Containers become the new list root; anything else is shown in the detail
   * pane, with the list moved to its parent so the object is visible there too.
   */
  const navigateTo = async (dn: string) => {
    setActiveSearch('')
    setSearchTerm('')
    try {
      const object = await api.object(dn)
      if (object.is_container) {
        setCurrentDn(object.dn)
        setSelected(null)
        return
      }
      const { path } = await api.path(object.dn)
      const parent = path.at(-2)
      if (parent) setCurrentDn(parent.dn)
      setSelected(object)
    } catch (error) {
      setNavigationError(error)
    }
  }

  const onChanged = (message: string) => {
    setNotice(message)
    void queryClient.invalidateQueries({ queryKey: ['children'] })
    void queryClient.invalidateQueries({ queryKey: ['tree'] })
  }

  return (
    <div className="console">
      <header className="topbar">
        <div className="topbar__brand">
          <LogoMark size={26} />
          <strong>{t('app.title')}</strong>
          <span>{session!.domain.dns_domain}</span>
        </div>

        <form
          className="topbar__search"
          onSubmit={(event) => {
            event.preventDefault()
            setActiveSearch(searchTerm.trim())
            setSelected(null)
          }}
        >
          <input
            type="search"
            value={searchTerm}
            placeholder={t('nav.search')}
            onChange={(event) => {
              setSearchTerm(event.target.value)
              if (event.target.value === '') setActiveSearch('')
            }}
          />
        </form>

        <div className="topbar__actions">
          <label className="checkbox checkbox--inline">
            <input
              type="checkbox"
              checked={showAdvanced}
              onChange={(event) => setShowAdvanced(event.target.checked)}
            />
            <span>{t('nav.advanced')}</span>
          </label>
          <button type="button" className="link" onClick={() => setLanguage(language === 'de' ? 'en' : 'de')}>
            {language === 'de' ? 'EN' : 'DE'}
          </button>
          <span className="topbar__user" title={session!.principal}>
            {session!.username}
          </span>
          <button type="button" className="button" onClick={() => void logout()}>
            {t('nav.logout')}
          </button>
        </div>
      </header>

      {notice && <div className="alert alert--success">{notice}</div>}
      <ErrorMessage error={navigationError} onDismiss={() => setNavigationError(null)} />

      <div className="console__panes">
        <div className="pane pane--tree">
          <TreePane
            rootDn={baseDn}
            rootLabel={session!.domain.dns_domain}
            selectedDn={activeSearch ? null : currentDn}
            onSelect={(dn) => {
              setActiveSearch('')
              setSearchTerm('')
              setSnapin('directory')
              setCurrentDn(dn)
              setSelected(null)
            }}
            showAdvanced={showAdvanced}
            activeSnapin={snapin}
            onSelectSnapin={setSnapin}
            selectedZoneDn={dnsZone?.dn ?? null}
            onSelectZone={(zone) => {
              setSnapin('dns')
              setDnsZone(zone)
              setSelected(null)
            }}
          />
        </div>

        {snapin === 'dns' ? (
          <div className="pane pane--list">
            <DnsView zone={dnsZone} onChanged={onChanged} />
          </div>
        ) : snapin === 'sites' ? (
          <div className="pane pane--list">
            <SitesView onChanged={onChanged} />
          </div>
        ) : snapin === 'diagnostics' ? (
          <div className="pane pane--list">
            <DiagnosticsView />
          </div>
        ) : snapin === 'gpo' ? (
          <div className="pane pane--list">
            <GpoView onChanged={onChanged} />
          </div>
        ) : snapin !== 'directory' ? (
          <div className="pane pane--list">
            <SnapinPlaceholder id={snapin} />
          </div>
        ) : (
        <div className="pane pane--list">
          <div className="pane__header">
            <span className="mono muted small">{activeSearch ? t('nav.search') : currentDn}</span>
            {!activeSearch && (
              <div className="pane__actions">
                <button type="button" className="button" onClick={() => setNewObject('user')}>
                  + {t('action.newUser')}
                </button>
                <button type="button" className="button" onClick={() => setNewObject('group')}>
                  + {t('action.newGroup')}
                </button>
                <button type="button" className="button" onClick={() => setNewObject('computer')}>
                  + {t('action.newComputer')}
                </button>
                <button type="button" className="button" onClick={() => setNewObject('ou')}>
                  + {t('action.newOu')}
                </button>
              </div>
            )}
          </div>

          {active.isLoading && <Spinner label={t('status.loading')} />}
          <ErrorMessage error={active.error} />

          <ObjectList
            entries={entries}
            truncated={activeSearch ? search.data?.truncated : children.data?.truncated}
            selectedDn={selected?.dn ?? null}
            onSelect={setSelected}
            onOpen={(object) => {
              if (object.is_container) {
                setActiveSearch('')
                setCurrentDn(object.dn)
                setSelected(null)
              } else {
                setSelected(object)
              }
            }}
          />
        </div>
        )}

        <div className="pane pane--detail">
          <DetailPane object={selected} onChanged={onChanged} onNavigate={(dn) => void navigateTo(dn)} />
        </div>
      </div>

      {newObject === 'user' && (
        <NewUserDialog parentDn={currentDn} onClose={() => setNewObject(null)} onDone={onChanged} />
      )}
      {newObject === 'group' && (
        <NewGroupDialog parentDn={currentDn} onClose={() => setNewObject(null)} onDone={onChanged} />
      )}
      {newObject === 'computer' && (
        <NewComputerDialog parentDn={currentDn} onClose={() => setNewObject(null)} onDone={onChanged} />
      )}
      {newObject === 'ou' && (
        <NewOuDialog parentDn={currentDn} onClose={() => setNewObject(null)} onDone={onChanged} />
      )}
    </div>
  )
}
