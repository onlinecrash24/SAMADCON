import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type CSSProperties } from 'react'

import { ApiError } from './api/client'
import { api } from './api/endpoints'
import type { DirectoryObject } from './api/types'
import { DetailPane } from './components/DetailPane'
import { LoginView } from './components/LoginView'
import { LogoMark } from './components/Logo'
import { ObjectList } from './components/ObjectList'
import { TreePane } from './components/TreePane'
import { useContextMenu, type MenuNode } from './components/ContextMenu'
import { Splitter } from './components/Splitter'
import { Taskbar, useWindowCounts, WindowLayer } from './components/WindowLayer'
import { ConsoleTabs } from './features/console/ConsoleTabs'
import {
  NewComputerDialog,
  NewGroupDialog,
  NewOuDialog,
  NewUserDialog,
  RenameDialog,
  MoveDialog,
  DeleteDialog,
  PasswordDialog,
} from './components/dialogs'
import { ErrorMessage, Icon, Spinner } from './components/primitives'
import { SourceNote } from './components/SourceNote'
import type { DnsZone } from './api/types'
import { SNAPINS, panesFor, type SnapinId } from './features/console/snapins'
import { DiagnosticsView } from './features/diagnostics/DiagnosticsView'
import { SecurityFindings } from './features/diagnostics/SecurityFindings'
import { DnsView } from './features/dns/DnsView'
import { contextMenuActions } from './features/directory/objectActions'
import { GpoView } from './features/gpo/GpoView'
import { ObjectPropertiesWindow } from './features/directory/ObjectPropertiesWindow'
import { GpoWindow } from './features/gpo/GpoWindow'
import { SitesView } from './features/sites/SitesView'
import { useI18n } from './i18n'
import { readConsoleLocation, writeConsoleLocation } from './state/consoleLocation'
import { readPaneWidths, writePaneWidths, type Boundary } from './state/paneWidths'
import { useWindows, WindowProvider } from './state/windows'
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

  // Above Console, so Console itself can open windows — and because Console
  // exists only while there is a session, signing out unmounts the windows
  // with it. No cleanup, no forgetWindows().
  return session ? (
    <WindowProvider>
      <Console />
    </WindowProvider>
  ) : (
    <LoginView />
  )
}

/** The leading component of a DN, without its attribute name. */
function nameFromDn(dn: string): string {
  return (dn.split(',')[0] ?? dn).replace(/^[A-Za-z]+=/, '')
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

  // Read once. Written back only when a drag is released, never per move —
  // the drag itself writes straight to the DOM.
  const [paneWidths, setPaneWidths] = useState(() => readPaneWidths())

  const rememberWidth = (boundary: Boundary, px: number | null) => {
    setPaneWidths((current) => {
      const forConsole = { ...current[snapin] }
      if (px === null) delete forConsole[boundary]
      else forConsole[boundary] = px

      const updated = { ...current, [snapin]: forConsole }
      writePaneWidths(updated)
      return updated
    })
  }

  const [currentDn, setCurrentDn] = useState(restored.dn)
  const [selected, setSelected] = useState<DirectoryObject | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(restored.showAdvanced)
  // Both from the same stored value: the box should show the words that
  // produced the results on screen, not sit empty above them.
  const [searchTerm, setSearchTerm] = useState(restored.search)
  const [activeSearch, setActiveSearch] = useState(restored.search)
  const [newObject, setNewObject] = useState<NewObjectKind>(null)
  const [notice, setNotice] = useState<string | null>(null)
  // Anything a menu, a navigation or a one-shot action failed at. Shown once,
  // at the top, and dismissible.
  const [shellError, setShellError] = useState<unknown>(null)
  const [objectDialog, setObjectDialog] = useState<
    { kind: 'rename' | 'move' | 'delete' | 'password'; object: DirectoryObject } | null
  >(null)
  // Which container a "Neu" command creates into. A menu on a row means that
  // row, which is not necessarily where the tree is pointing.
  const [newObjectParent, setNewObjectParent] = useState<string | null>(null)
  const [snapin, setSnapin] = useState<SnapinId>(restored.snapin)
  const [dnsZone, setDnsZone] = useState<DnsZone | null>(null)
  // Which container the policy tree points at. null is GPMC's "all
  // policies" node, and the state the console opens in.
  const [gpoContainerDn, setGpoContainerDn] = useState<string | null>(restored.gpoContainerDn)

  // Shares its key with the diagnosis page, which asks for the same thing:
  // one request between them, and /info touches no domain controller.
  const serverInfo = useQuery({ queryKey: ['server-info'], queryFn: () => api.info() })

  const children = useQuery({
    queryKey: ['children', currentDn, showAdvanced],
    queryFn: () => api.children(currentDn, { advanced: showAdvanced }),
    enabled: activeSearch === '',
  })

  const search = useQuery({
    // The switch is part of the key, or toggling it would serve the previous
    // answer out of the cache and look like the switch does nothing.
    queryKey: ['search', activeSearch, showAdvanced],
    queryFn: () => api.search(activeSearch, { advanced: showAdvanced }),
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
      setShellError(error)
    }
  }

  const menu = useContextMenu()
  const windows = useWindows()
  const windowCounts = useWindowCounts()

  /**
   * What a menu choice does.
   *
   * Split from what a menu offers (objectActions) on purpose: the offer has to
   * be identical wherever it is made, and the doing differs — the detail pane
   * has the object loaded and can mutate it straight away, a row has a name
   * and a DN.
   */
  const runAction = (object: DirectoryObject, id: string) => {
    const write = (call: Promise<unknown>, message: string) => {
      setShellError(null)
      call.then(() => onChanged(message)).catch(setShellError)
    }

    switch (id) {
      case 'open':
        void navigateTo(object.dn)
        return
      case 'refresh':
        void queryClient.invalidateQueries({ queryKey: ['tree'] })
        void queryClient.invalidateQueries({ queryKey: ['children'] })
        return
      case 'newUser':
      case 'newGroup':
      case 'newComputer':
      case 'newOu':
        setNewObjectParent(object.dn)
        setNewObject(
          id === 'newUser' ? 'user' : id === 'newGroup' ? 'group' : id === 'newComputer' ? 'computer' : 'ou',
        )
        return
      case 'enable':
        write(api.setEnabled(object.dn, true), t('status.saved'))
        return
      case 'disable':
        write(api.setEnabled(object.dn, false), t('status.saved'))
        return
      case 'unlock':
        write(api.unlock(object.dn), t('status.unlocked'))
        return
      case 'resetAccount':
        write(api.resetComputer(object.dn), t('status.saved'))
        return
      case 'resetPassword':
        setObjectDialog({ kind: 'password', object })
        return
      case 'rename':
        setObjectDialog({ kind: 'rename', object })
        return
      case 'move':
        setObjectDialog({ kind: 'move', object })
        return
      case 'delete':
        setObjectDialog({ kind: 'delete', object })
        return
      case 'properties':
        windows.open({
          snapin: 'directory',
          kind: 'object',
          title: object.display_name || object.name,
          dn: object.dn,
        })
        return
      default:
        return
    }
  }

  const openMenu = (object: DirectoryObject, at: { x: number; y: number }) => {
    const entries: MenuNode[] = contextMenuActions(object).map((entry) =>
      entry.kind === 'separator'
        ? 'separator'
        : entry.kind === 'submenu'
          ? {
              id: `submenu:${entry.labelKey}`,
              labelKey: entry.labelKey,
              children: entry.items.map((child) => ({ id: child.id, labelKey: child.labelKey })),
            }
          : { id: entry.id, labelKey: entry.labelKey, danger: entry.danger },
    )
    menu.open(at, entries, (id) => runAction(object, id))
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
  // A menu on a container creates into that container; the toolbar above the
  // list creates into wherever the tree is pointing.
  const parentForNew = newObjectParent ?? currentDn
  const closeNew = () => {
    setNewObject(null)
    setNewObjectParent(null)
  }

  const panes = panesFor(snapin)
  const shape = panes.detail ? 'full' : panes.tree ? 'tree' : 'list'

  // Absent means "no preference", and the stylesheet's own minmax() applies.
  // Written as values rather than as a grid-template-columns declaration,
  // which would outrank both media queries.
  const widths = paneWidths[snapin] ?? {}
  const paneStyle = {
    ...(widths.tree !== undefined && { '--tree-w': `${widths.tree}px` }),
    ...(widths.detail !== undefined && { '--detail-w': `${widths.detail}px` }),
  } as CSSProperties

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
          <SourceNote version={serverInfo.data?.version} />
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
      <ConsoleTabs active={snapin} onSelect={setSnapin} windowCounts={windowCounts} />

      {notice && <div className="alert alert--success">{notice}</div>}
      <ErrorMessage error={shellError} onDismiss={() => setShellError(null)} />

      <div className={`console__panes console__panes--${shape}`} style={paneStyle}>
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
            onContextNode={openMenu}
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

        <Splitter boundary="tree" onCommit={(px) => rememberWidth('tree', px)} />

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
              <GpoView
              containerDn={gpoContainerDn}
              onChanged={onChanged}
              onOpenPolicy={(dn, title) =>
                windows.open({ snapin: 'gpo', kind: 'gpo', title, dn })
              }
            />
          </div>
        ) : snapin === 'reports' ? (
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
            <div className="pane__actions">
              {/* It acts on this console alone — the tree and the list beside
                  it — and it used to sit in the top bar, where it stayed
                  visible while someone was in DNS or Group Policy and it did
                  nothing at all. Outside the search condition below, because
                  it applies to the results of a search too. */}
              <label className="checkbox checkbox--inline">
                <input
                  type="checkbox"
                  checked={showAdvanced}
                  onChange={(event) => setShowAdvanced(event.target.checked)}
                />
                <span>{t('nav.advanced')}</span>
              </label>

              {!activeSearch && (
                <>
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
                </>
              )}
            </div>
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
                return
              }
              // A double click on something that cannot be opened into opens
              // its properties, which is what it does in the original.
              setSelected(object)
              windows.open({
                snapin: 'directory',
                kind: 'object',
                title: object.display_name || object.name,
                dn: object.dn,
              })
            }}
            onContext={openMenu}
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
            <Splitter boundary="detail" onCommit={(px) => rememberWidth('detail', px)} />
            <div className="pane pane--detail">
              <DetailPane
                object={selected}
                onChanged={onChanged}
                onNavigate={(dn) => void navigateTo(dn)}
                onRetarget={(dn) => void navigateTo(dn)}
              />
            </div>
          </>
        )}
      </div>

      {newObject === 'user' && (
        <NewUserDialog parentDn={parentForNew} onClose={closeNew} onDone={onChanged} />
      )}
      {newObject === 'group' && (
        <NewGroupDialog parentDn={parentForNew} onClose={closeNew} onDone={onChanged} />
      )}
      {newObject === 'computer' && (
        <NewComputerDialog parentDn={parentForNew} onClose={closeNew} onDone={onChanged} />
      )}
      {newObject === 'ou' && (
        <NewOuDialog parentDn={parentForNew} onClose={closeNew} onDone={onChanged} />
      )}

      {/* Opened from a menu on a row, so they act on that row rather than on
          whatever the detail pane is showing. The pane keeps its own copies
          for its own buttons. */}
      {objectDialog?.kind === 'rename' && (
        <RenameDialog
          dn={objectDialog.object.dn}
          currentName={objectDialog.object.name}
          onClose={() => setObjectDialog(null)}
          onDone={onChanged}
        />
      )}
      {objectDialog?.kind === 'move' && (
        <MoveDialog
          dn={objectDialog.object.dn}
          name={objectDialog.object.name}
          onClose={() => setObjectDialog(null)}
          onDone={onChanged}
        />
      )}
      {objectDialog?.kind === 'delete' && (
        <DeleteDialog
          dn={objectDialog.object.dn}
          name={objectDialog.object.name}
          isContainer={objectDialog.object.is_container}
          isOu={objectDialog.object.type === 'organizational_unit'}
          onClose={() => setObjectDialog(null)}
          onDone={(message) => {
            if (selected?.dn === objectDialog.object.dn) setSelected(null)
            onChanged(message)
          }}
        />
      )}
      {objectDialog?.kind === 'password' && (
        <PasswordDialog
          dn={objectDialog.object.dn}
          onClose={() => setObjectDialog(null)}
          onDone={onChanged}
        />
      )}

      {menu.menu}

      {/* A flex child of the console, not a fixed strip: the panes shrink to
          make room and nothing is ever covered by it. */}
      <Taskbar activeSnapin={snapin} />

      <WindowLayer
        activeSnapin={snapin}
        render={(open) =>
          open.kind === 'gpo' ? (
            <GpoWindow
              dn={open.dn}
              onClose={() => windows.close(open.id)}
              onChanged={onChanged}
            />
          ) : (
            <ObjectPropertiesWindow
              dn={open.dn}
              onClose={() => windows.close(open.id)}
              onChanged={onChanged}
              // Following a member or a parent group opens another window
              // rather than moving the console behind this one: windows are
              // cheap now, and shifting the pane under something someone is
              // reading is the disorienting alternative.
              onNavigate={(dn) =>
                windows.open({
                  snapin: 'directory',
                  kind: 'object',
                  // The leading component, not the whole DN: a title bar
                  // reading CN=Anna,OU=Benutzer,DC=… tells nobody anything it
                  // could not fit.
                  title: nameFromDn(dn),
                  dn,
                })
              }
              onRetarget={(dn, name) => windows.retarget(open.id, dn, name)}
            />
          )
        }
      />
    </div>
  )
}
