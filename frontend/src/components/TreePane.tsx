import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { isAtOrBelow } from '../dn'

import { api } from '../api/endpoints'
import type { DnsZone, TreeNode } from '../api/types'
import { snapinLabel, type SnapinId } from '../features/console/snapins'
import { GpoLinkTree } from '../features/gpo/GpoLinkTree'
import { useI18n } from '../i18n'
import { Chevron, Icon, Spinner } from './primitives'

interface TreePaneProps {
  rootDn: string
  rootLabel: string
  selectedDn: string | null
  onSelect: (dn: string) => void
  showAdvanced: boolean
  activeSnapin: SnapinId
  selectedZoneDn: string | null
  onSelectZone: (zone: DnsZone) => void
  /** Which container the policy tree has selected; null means all policies. */
  gpoContainerDn: string | null
  onSelectGpoContainer: (dn: string | null) => void
  /** A policy dropped onto a container in the tree reports back through this. */
  onChanged: (message: string) => void
  /** A zone remembered from before a reload, still to be matched to a zone. */
  restoredZoneDn: string | null
  /**
   * A DN to make visible: every branch on the way to it starts open.
   *
   * Held by the shell rather than captured here. It means "where the person
   * was when the page loaded", which is a fact about the session and not about
   * this component — captured here it would quietly become "where they were
   * when this pane last mounted" the moment anyone renders the pane
   * conditionally.
   */
  revealDn: string | null
}

/**
 * The navigation pane: the hierarchy of whichever console is open.
 *
 * It used to hold the consoles as well, as roots with their trees hanging
 * beneath them. Those live in the tab strip now, so this pane shows one
 * hierarchy at a time and nothing else — which is what the left pane of an
 * RSAT console is.
 */
export function TreePane({
  rootDn,
  rootLabel,
  selectedDn,
  onSelect,
  showAdvanced,
  activeSnapin,
  selectedZoneDn,
  onSelectZone,
  gpoContainerDn,
  onSelectGpoContainer,
  onChanged,
  restoredZoneDn,
  revealDn,
}: TreePaneProps) {
  const { t } = useI18n()

  // A selection inside a console only marks a row while that console is the
  // active one. The selected DN and zone deliberately survive a switch to
  // another console, so that coming back lands where you left off — but the
  // highlight must not, or the tree shows a selected directory node while an
  // entirely different console fills the pane beside it.
  const directoryDn = activeSnapin === 'directory' ? selectedDn : null
  const zoneDn = activeSnapin === 'dns' ? selectedZoneDn : null

  return (
    // Named after what it is currently showing. Labelled "Verzeichnis" while
    // listing DNS zones, it tells a screen reader something untrue.
    <nav className="tree" aria-label={t(snapinLabel(activeSnapin))}>
      {/* Hidden while another console is open, not unmounted. Which branches
          someone had expanded is part of where they left off — the same reason
          the selected DN survives the switch — and unmounting would throw it
          away every time they glanced at another console. The tab strip makes
          switching one click and always visible, so that now happens more
          often, which makes discarding the state cost more, not less. */}
      <div hidden={activeSnapin !== 'directory'}>
        <TreeNodeRow
          node={{ dn: rootDn, name: rootLabel, type: 'domain', has_children: true } as TreeNode}
          depth={1}
          selectedDn={directoryDn}
          onSelect={onSelect}
          showAdvanced={showAdvanced}
          revealDn={revealDn}
          initiallyOpen
        />
      </div>

      {activeSnapin === 'dns' && (
        <ZoneList
          selectedZoneDn={zoneDn}
          onSelectZone={onSelectZone}
          restoredZoneDn={restoredZoneDn}
        />
      )}

      {activeSnapin === 'gpo' && (
        <GpoLinkTree
          rootDn={rootDn}
          rootLabel={rootLabel}
          selectedDn={gpoContainerDn}
          onSelect={onSelectGpoContainer}
          onChanged={onChanged}
          // Followed live, unlike the directory tree above: the policy tree is
          // unmounted whenever another console is open, so it mounts again on
          // every visit and has to open toward wherever the selection is now —
          // not toward where a reload found it.
          revealDn={gpoContainerDn}
        />
      )}
    </nav>
  )
}

/**
 * The zones below the DNS console.
 *
 * Loaded only while that console is open — three partition searches are not
 * something to run on every sign-in for a tree branch nobody looked at.
 */
function ZoneList({
  selectedZoneDn,
  onSelectZone,
  restoredZoneDn,
}: {
  selectedZoneDn: string | null
  onSelectZone: (zone: DnsZone) => void
  restoredZoneDn: string | null
}) {
  const { t } = useI18n()

  const zones = useQuery({
    queryKey: ['dns-zones'],
    queryFn: () => api.dnsZones(),
    staleTime: 60_000,
  })

  // A remembered zone is a name, and the console holds a zone. Matched here
  // rather than in the shell because this is where the list already is —
  // there is no endpoint for a single zone, and fetching the list a second
  // time would undo the reason it is only fetched once this console opens.
  //
  // A zone that is gone simply does not match, and the view says "pick a
  // zone", which is a correct state rather than a broken one.
  const restored = useRef(false)
  useEffect(() => {
    if (restored.current || !restoredZoneDn || selectedZoneDn) return
    const found = zones.data?.zones.find((zone) => zone.dn === restoredZoneDn)
    if (!found) return
    restored.current = true
    onSelectZone(found)
  }, [zones.data, restoredZoneDn, selectedZoneDn, onSelectZone])

  if (zones.isLoading) {
    return (
      <div style={{ paddingLeft: '34px' }}>
        <Spinner label={t('status.loading')} />
      </div>
    )
  }

  return (
    <div className="tree__children">
      {zones.data?.zones.map((zone) => (
        <div className="tree__node" key={zone.dn}>
          <div
            className={
              selectedZoneDn === zone.dn ? 'tree__row tree__row--selected' : 'tree__row'
            }
            style={{ paddingLeft: '20px' }}
          >
            <span className="tree__toggle" />
            <button
              type="button"
              className="tree__label"
              onClick={() => onSelectZone(zone)}
              title={zone.dn}
            >
              <Icon type={zone.reverse ? 'container' : 'domain'} />
              <span>{zone.name}</span>
            </button>
          </div>
        </div>
      ))}
      {zones.data?.zones.length === 0 && (
        <p className="muted small" style={{ paddingLeft: '34px' }}>
          {t('dns.noZones')}
        </p>
      )}
    </div>
  )
}

interface TreeNodeRowProps {
  node: TreeNode
  depth: number
  selectedDn: string | null
  onSelect: (dn: string) => void
  showAdvanced: boolean
  /** A DN to make visible: every branch on the way to it starts open. */
  revealDn: string | null
  initiallyOpen?: boolean
}

function TreeNodeRow({
  node,
  depth,
  selectedDn,
  onSelect,
  showAdvanced,
  revealDn,
  initiallyOpen,
}: TreeNodeRowProps) {
  const { t } = useI18n()
  // Read once, when this row first appears. Children only mount once their
  // parent is open, so the path unfolds one level at a time — each new row
  // asking the same question of itself — and stops at the branch that holds
  // the DN. Nothing below it is fetched.
  const [open, setOpen] = useState(initiallyOpen ?? isAtOrBelow(revealDn, node.dn))

  const children = useQuery({
    queryKey: ['tree', node.dn, showAdvanced],
    queryFn: () => api.tree(node.dn, showAdvanced),
    // Children are only fetched once the node is expanded, so a large domain
    // is never walked on load.
    enabled: open,
    staleTime: 30_000,
  })

  // The server tells us whether there is anything below. Once expanded, what
  // actually arrived is the better answer — a container emptied by someone
  // else should lose its expander without a reload.
  const expandable = open
    ? (children.data?.nodes.length ?? 0) > 0 || children.isLoading
    : node.has_children !== false

  const selected = selectedDn === node.dn

  return (
    <div className="tree__node">
      <div
        className={selected ? 'tree__row tree__row--selected' : 'tree__row'}
        style={{ paddingLeft: `${depth * 14 + 6}px` }}
      >
        {expandable ? (
          <button
            type="button"
            className="tree__toggle"
            onClick={() => setOpen((value) => !value)}
            // A bare '-' or '+' told a screen reader nothing; the labels
            // existed for the policy tree anyway.
            aria-label={open ? t('tree.collapse') : t('tree.expand')}
            aria-expanded={open}
          >
            <Chevron open={open} />
          </button>
        ) : (
          // Keeps the labels aligned with their expandable siblings.
          <span className="tree__toggle" />
        )}

        <button
          type="button"
          className="tree__label"
          onClick={() => {
            onSelect(node.dn)
            if (!open && expandable) setOpen(true)
          }}
          title={node.dn}
        >
          <Icon type={node.type} />
          <span>{node.name}</span>
        </button>
      </div>

      {open && (
        <div className="tree__children">
          {children.isLoading && (
            <div style={{ paddingLeft: `${(depth + 1) * 14 + 22}px` }}>
              <Spinner label={t('status.loading')} />
            </div>
          )}
          {children.data?.nodes.map((child) => (
            <TreeNodeRow
              key={child.dn}
              node={child}
              depth={depth + 1}
              selectedDn={selectedDn}
              onSelect={onSelect}
              showAdvanced={showAdvanced}
              revealDn={revealDn}
            />
          ))}
        </div>
      )}
    </div>
  )
}
