import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { ApiError } from './api/client'
import { api } from './api/endpoints'
import type { DirectoryObject } from './api/types'
import { DetailPane } from './components/DetailPane'
import { LoginView } from './components/LoginView'
import { LogoMark } from './components/Logo'
import { ObjectList } from './components/ObjectList'
import { TreePane } from './components/TreePane'
import { ConsoleTabs } from './features/console/ConsoleTabs'
import {
  NewComputerDialog,
  NewGroupDialog,
  NewOuDialog,
  NewUserDialog,
} from './components/dialogs'
import { ErrorMessage, Icon, Spinner } from './components/primitives'
import type { DnsZone } from './api/types'
import { SNAPINS, panesFor, type SnapinId } from './features/console/snapins'
import { DiagnosticsView } from './features/diagnostics/DiagnosticsView'
import { SecurityFindings } from './features/diagnostics/SecurityFindings'
import { DnsView } from './features/dns/DnsView'
import { GpoView } from './features/gpo/GpoView'
import { SitesView } from './features/sites/SitesView'
import { useI18n } from './i18n'
import { readConsoleLocation, writeConsoleLocation } from './state/consoleLocation'
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

  // Read once, at mount. This component only exists while there is a session
  // (see App above), so the domain to validate the stored DNs against is
  // available right here — no effect, and nothing to undo if it turns out to
  // be nonsense.
  const [restored] = useState(() => readConsoleLocation(baseDn))

  // The stored selection, until the object behind it has been fetched. Held
  // because the two effects below both run on mount and the writer runs
  // first: without it, the very first write would store "nothing selected"
  // and a second refresh arriving inside that window would lose the pane.
  const pendingSelection = useRef(restored.selectedDn)

  // Where the person was when the page loaded, so the navigation tree can open
  // the branches on the way to it. Held here rather than inside the pane: it is
  // a fact about this session, and a pane that captured it itself would quietly
  // start meaning "when the pane last mounted" if it were ever rendered
  // conditionally — which is exactly what a console with no tree invites.
  const revealDn = useRef(restored.search ? null : restored.dn)

  const [currentDn, setCurrentDn] = useState(restored.dn)
  const [selected, setSelected] = useState<DirectoryObject | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(restored.showAdvanced)
  // Both from the same stored value: the box should show the words that
  // produced the results on screen, not sit empty above them.
  const [searchTerm, setSearchTerm] = useState(restored.search)
  const [activeSearch, setActiveSearch] = useState(restored.search)
  const [newObject, setNewObject] = useState<NewObjectKind>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [navigationError, setNavigationError] = useState<unknown>(null)
  const [snapin, setSnapin] = useState<SnapinId>(restored.snapin)
  const [dnsZone, setDnsZone] = useState<DnsZone | null>(null)
  // Which container the policy tree points at. null is GPMC's "all
  // policies" node, and the state the console opens in.
  const [gpoContainerDn, setGpoContainerDn] = useState<string | null>(restored.gpoContainerDn)

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

  // Remember where this tab is, so that a refresh returns to it. Only the
  // identity of things is stored — a DN, a console — never the objects
  // themselves, which are fetched again and may well have changed.
  useEffect(() => {
    writeConsoleLocation({
      snapin,
      dn: currentDn,
      selectedDn: selected?.dn ?? pendingSelection.current,
      showAdvanced,
      search: activeSearch,
      gpoContainerDn,
      zoneDn: dnsZone?.dn ?? null,
    })
  }, [snapin, currentDn, selected?.dn, showAdvanced, activeSearch, gpoContainerDn, dnsZone?.dn])

  // The detail pane held an object, and only its name was stored. Fetch it
  // back once.
  useEffect(() => {
    const dn = restored.selectedDn
    if (!dn) return

    void api
      .object(dn)
      // Only if nothing has been picked in the meantime: this arrives after a
      // round trip, and whoever is already clicking outranks it.
      .then((object) => setSelected((current) => current ?? object))
      .catch(() => {
        // Moved, deleted, or no longer permitted. Silently — nobody performed
        // this navigation, so an error banner on load would be noise about a
        // request the user did not make.
      })
      .finally(() => {
        pendingSelection.current = null
      })
  }, [restored.selectedDn])

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

  // Three shapes rather than one boolean modifier. The old one only ever
  // asked "is this the directory console?", which could not express that three
  // consoles have no tree at all — they were being handed a 210-280px column
  // to leave empty.
  const panes = panesFor(snapin)
  const shape = panes.detail ? 'full' : panes.tree ? 'tree' : 'list'

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

      {/* Above the notices, not below: the strip is chrome, and it must not
          jump down when a success message appears and away again four seconds
          later. */}
      <ConsoleTabs active={snapin} onSelect={setSnapin} />

      {notice && <div className="alert alert--success">{notice}</div>}
      <ErrorMessage error={navigationError} onDismiss={() => setNavigationError(null)} />

      <div className={`console__panes console__panes--${shape}`}>
        {/* Always rendered, even for the three consoles that have no tree —
            the stylesheet hides it for those. Unmounting it would throw away
            every expanded branch on the way past Sites, and the pane is built
            on never being unmounted. */}
        <div className="pane pane--tree">
          <TreePane
            rootDn={baseDn}
            rootLabel={session!.domain.dns_domain}
            selectedDn={activeSearch ? null : currentDn}
            onSelect={(dn) => {
              setActiveSearch('')
              setSearchTerm('')
              setCurrentDn(dn)
              setSelected(null)
            }}
            showAdvanced={showAdvanced}
            activeSnapin={snapin}
            revealDn={revealDn.current}
            gpoContainerDn={gpoContainerDn}
            onSelectGpoContainer={setGpoContainerDn}
            onChanged={onChanged}
            restoredZoneDn={restored.zoneDn}
            selectedZoneDn={dnsZone?.dn ?? null}
            onSelectZone={(zone) => {
              setDnsZone(zone)
              setSelected(null)
            }}
          />
        </div>

        <div className="splitter splitter--tree" />

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
            <GpoView containerDn={gpoContainerDn} onChanged={onChanged} />
          </div>
        ) : snapin === 'assistant' ? (
          <div className="pane pane--list">
            <SecurityFindings />
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

        {/* Only the directory console fills this. Every other console left
            it standing on "nothing selected" and took 420px of width with
            it — which is the width the group policy list wanted. GPMC has
            two panes there for the same reason. Which consoles those are is
            now stated in snapins.ts rather than spelled out here. */}
        {panes.detail && (
          <>
            <div className="splitter splitter--detail" />
            <div className="pane pane--detail">
              <DetailPane
                object={selected}
                onChanged={onChanged}
                onNavigate={(dn) => void navigateTo(dn)}
              />
            </div>
          </>
        )}
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
