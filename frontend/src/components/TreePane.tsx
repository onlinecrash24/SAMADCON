import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../api/endpoints'
import type { DnsZone, TreeNode } from '../api/types'
import { SNAPINS, type SnapinId } from '../features/console/snapins'
import { useI18n } from '../i18n'
import { Chevron, Icon, Spinner } from './primitives'

interface TreePaneProps {
  rootDn: string
  rootLabel: string
  selectedDn: string | null
  onSelect: (dn: string) => void
  showAdvanced: boolean
  activeSnapin: SnapinId
  onSelectSnapin: (id: SnapinId) => void
  selectedZoneDn: string | null
  onSelectZone: (zone: DnsZone) => void
}

/**
 * The navigation tree, laid out the way MMC does it: every console is a root
 * node, and the directory hierarchy hangs under the one that owns it.
 */
export function TreePane({
  rootDn,
  rootLabel,
  selectedDn,
  onSelect,
  showAdvanced,
  activeSnapin,
  onSelectSnapin,
  selectedZoneDn,
  onSelectZone,
}: TreePaneProps) {
  const { t } = useI18n()

  return (
    <nav className="tree" aria-label={t('nav.directory')}>
      {SNAPINS.map((snapin) => (
        <div className="tree__snapin" key={snapin.id}>
          <div
            className={
              activeSnapin === snapin.id && !selectedDn
                ? 'tree__row tree__row--selected'
                : 'tree__row'
            }
          >
            {/* No expander on a console root. It is a section heading rather
                than a container, and the arrow claimed a state that was never
                real: it always pointed open, while the DNS console only shows
                its zones once that console is the active one. */}
            <span className="tree__toggle" />
            <button
              type="button"
              className={
                snapin.available ? 'tree__label tree__label--root' : 'tree__label tree__label--muted'
              }
              onClick={() => onSelectSnapin(snapin.id)}
            >
              <Icon type={snapin.icon} />
              <span>{t(snapin.label)}</span>
            </button>
          </div>

          {snapin.available && snapin.id === 'directory' && (
            <TreeNodeRow
              node={{ dn: rootDn, name: rootLabel, type: 'domain', has_children: true } as TreeNode}
              depth={1}
              selectedDn={selectedDn}
              onSelect={onSelect}
              showAdvanced={showAdvanced}
              initiallyOpen
            />
          )}

          {snapin.available && snapin.id === 'dns' && activeSnapin === 'dns' && (
            <ZoneList selectedZoneDn={selectedZoneDn} onSelectZone={onSelectZone} />
          )}
        </div>
      ))}
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
}: {
  selectedZoneDn: string | null
  onSelectZone: (zone: DnsZone) => void
}) {
  const { t } = useI18n()

  const zones = useQuery({
    queryKey: ['dns-zones'],
    queryFn: () => api.dnsZones(),
    staleTime: 60_000,
  })

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
  initiallyOpen?: boolean
}

function TreeNodeRow({
  node,
  depth,
  selectedDn,
  onSelect,
  showAdvanced,
  initiallyOpen,
}: TreeNodeRowProps) {
  const { t } = useI18n()
  const [open, setOpen] = useState(initiallyOpen ?? false)

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
            aria-label={open ? '-' : '+'}
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
            />
          ))}
        </div>
      )}
    </div>
  )
}
