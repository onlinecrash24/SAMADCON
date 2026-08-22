/**
 * The group policy tree: where each policy is linked, in the shape GPMC draws.
 *
 * The list beside it answers "what policies exist". This answers the question
 * people actually arrive with — "what applies to this OU" — and it answers it
 * by structure rather than by a lookup, which is why it is worth a tree at all.
 *
 * Two sources, joined here. The container hierarchy comes from the same
 * endpoint the directory console walks, one level at a time as branches open:
 * a domain with two hundred OUs should not cost two hundred searches to show
 * its first level. Every link in the domain comes from one call — two searches
 * for the whole thing — so opening a branch never asks about links again.
 *
 * Links are drawn in precedence order, 1 first, because that is the order they
 * take effect in. Any other order would look like precedence and mislead.
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { LinkedContainer, TreeNode } from '../../api/types'
import { Badge, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'

interface GpoLinkTreeProps {
  rootDn: string
  rootLabel: string
  selectedDn: string | null
  onSelect: (dn: string | null) => void
}

export function GpoLinkTree({ rootDn, rootLabel, selectedDn, onSelect }: GpoLinkTreeProps) {
  const { t } = useI18n()

  // Every link in the domain, once. Fetched only while this console is open —
  // the caller mounts this component then — and shared by every branch.
  const links = useQuery({
    queryKey: ['gpo-link-map'],
    queryFn: () => api.gpoLinkMap(),
    staleTime: 30_000,
  })

  const byContainer = new Map<string, LinkedContainer>()
  for (const node of links.data?.containers ?? []) {
    byContainer.set(node.dn.toLowerCase(), node)
  }

  if (links.isLoading) {
    return (
      <div className="tree__children" style={{ paddingLeft: '34px' }}>
        <Spinner label={t('status.loading')} />
      </div>
    )
  }

  return (
    <div className="tree__children">
      <ContainerNode
        dn={rootDn}
        name={rootLabel}
        depth={1}
        byContainer={byContainer}
        selectedDn={selectedDn}
        onSelect={onSelect}
        initiallyOpen
      />

      {/* GPMC's own node, and worth keeping: it is where you go when the
          question is about a policy rather than about a place. */}
      <div className="tree__node">
        <div
          className={selectedDn === null ? 'tree__row tree__row--selected' : 'tree__row'}
          style={{ paddingLeft: '20px' }}
        >
          <span className="tree__toggle" />
          <button type="button" className="tree__label" onClick={() => onSelect(null)}>
            <span>{t('gpo.allPolicies')}</span>
          </button>
        </div>
      </div>
    </div>
  )
}

/** One container, its policies, and the containers below it. */
function ContainerNode({
  dn,
  name,
  depth,
  byContainer,
  selectedDn,
  onSelect,
  initiallyOpen = false,
}: {
  dn: string
  name: string
  depth: number
  byContainer: Map<string, LinkedContainer>
  selectedDn: string | null
  onSelect: (dn: string | null) => void
  initiallyOpen?: boolean
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(initiallyOpen)

  const children = useQuery({
    queryKey: ['gpo-tree', dn],
    queryFn: () => api.tree(dn),
    // Only once the branch is open. A closed branch is a question nobody asked.
    enabled: open,
    staleTime: 30_000,
  })

  const linked = byContainer.get(dn.toLowerCase())?.links ?? []
  const indent = { paddingLeft: `${depth * 14}px` }

  return (
    <div className="tree__node">
      <div className={selectedDn === dn ? 'tree__row tree__row--selected' : 'tree__row'} style={indent}>
        <button
          type="button"
          className="tree__toggle"
          aria-label={open ? t('tree.collapse') : t('tree.expand')}
          onClick={() => setOpen(!open)}
        >
          {open ? '▾' : '▸'}
        </button>
        <button type="button" className="tree__label" onClick={() => onSelect(dn)}>
          <span>{name}</span>
          {linked.length > 0 && <span className="muted small"> {linked.length}</span>}
        </button>
      </div>

      {open && (
        <div className="tree__children">
          {/* The policies first, then the containers below — the same order
              GPMC uses, and the one that reads as "here, then onwards". */}
          {linked.map((link) => (
            <div className="tree__row" key={link.guid} style={{ paddingLeft: `${(depth + 1) * 14}px` }}>
              <span className="tree__toggle" />
              <span className="tree__label">
                <span className={link.enabled ? undefined : 'muted'}>
                  {/* A link can outlive the policy it names. Saying so beats
                      dropping the row: it still costs every client in scope a
                      lookup on each refresh, and nothing else reports it. */}
                  {link.display_name ?? t('gpo.linkMissingPolicy')}
                </span>
                {!link.enabled && <> <Badge tone="muted">{t('report.linkDisabled')}</Badge></>}
                {link.enforced && <> <Badge tone="warn">{t('report.linkEnforced')}</Badge></>}
              </span>
            </div>
          ))}

          {children.isLoading && (
            <div style={{ paddingLeft: `${(depth + 1) * 14}px` }}>
              <Spinner label={t('status.loading')} />
            </div>
          )}

          {(children.data?.nodes ?? [])
            // Only what can hold a link. A tree of every user would bury the
            // handful of containers this view is about.
            .filter((node: TreeNode) => node.is_container)
            .map((node: TreeNode) => (
              <ContainerNode
                key={node.dn}
                dn={node.dn}
                name={node.name}
                depth={depth + 1}
                byContainer={byContainer}
                selectedDn={selectedDn}
                onSelect={onSelect}
              />
            ))}
        </div>
      )}
    </div>
  )
}
