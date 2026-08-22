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
 *
 * Every container here is also a place a policy can be dropped. That gesture
 * is an accelerator and never the only way in: linking from the policy's own
 * Links tab still works, and has to, because a drag cannot be performed from a
 * keyboard.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type DragEvent, type MouseEvent } from 'react'
import { createPortal } from 'react-dom'

import { api } from '../../api/endpoints'
import type { ContainerLink, LinkableNode, LinkedContainer } from '../../api/types'
import { Badge, ErrorMessage, Modal, Spinner } from '../../components/primitives'
import { isAtOrBelow } from '../../dn'
import { useI18n } from '../../i18n'
import { anchorOf, useContextMenu } from '../../components/ContextMenu'
import { LinkPolicyDialog } from './LinkPolicyDialog'
import { isPolicyDrag, readPolicyDrag, type DraggedPolicy } from './policyDrag'

interface GpoLinkTreeProps {
  rootDn: string
  rootLabel: string
  selectedDn: string | null
  onSelect: (dn: string | null) => void
  onChanged: (message: string) => void
  /** A container to make visible after a reload; branches on the way open. */
  revealDn: string | null
}

interface DropTarget {
  dn: string
  name: string
  /** Always true here: a row that cannot be linked to refuses the drop. */
  linkable: boolean
}

export function GpoLinkTree({
  rootDn,
  rootLabel,
  selectedDn,
  onSelect,
  onChanged,
  revealDn,
}: GpoLinkTreeProps) {
  const { t } = useI18n()

  // What was dropped where, held until the dialog answers for it. A drop
  // writes nothing on its own.
  const [dropped, setDropped] = useState<{
    policy: DraggedPolicy | null
    target: DropTarget
  } | null>(null)

  // One instance for the whole tree, never one per row.
  const menu = useContextMenu()

  const [unlinking, setUnlinking] = useState<{
    container: DropTarget
    link: ContainerLink
  } | null>(null)

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
        onDropPolicy={(target, policy) => setDropped({ target, policy })}
        onAskAboutLink={(container, link, at) =>
          menu.open(
            at,
            [{ id: 'unlink', labelKey: 'gpo.unlinkHere', danger: true }],
            () => setUnlinking({ container, link }),
          )
        }
        onAskToLink={(target, at) =>
          menu.open(at, [{ id: 'link', labelKey: 'gpo.linkHere' }], () =>
            // Without a policy: the dialog asks which. Linking was a drag and
            // nothing else, and a drag cannot be done from a keyboard.
            setDropped({ target, policy: null }),
          )
        }
        // The domain itself, and a policy may always be linked to it — that is
        // where Default Domain Policy sits.
        linkable
        revealDn={revealDn}
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

      {/* Rendered onto the body rather than here. A fixed-position dialog
          escapes the pane's own scrolling, but not the media query that hides
          the whole tree pane on a narrow window — and an open dialog that
          vanishes with the pane it was opened from takes its unanswered
          question with it. */}
      {menu.menu}

      {unlinking && (
        <UnlinkDialog
          container={unlinking.container}
          link={unlinking.link}
          onClose={() => setUnlinking(null)}
          onDone={(message) => {
            setUnlinking(null)
            onChanged(message)
          }}
        />
      )}

      {dropped &&
        createPortal(
          <LinkPolicyDialog
            policy={dropped.policy}
            target={dropped.target}
            onClose={() => setDropped(null)}
            onDone={onChanged}
          />,
          document.body,
        )}
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
  onDropPolicy,
  onAskToLink,
  onAskAboutLink,
  linkable,
  revealDn,
  initiallyOpen = false,
}: {
  dn: string
  name: string
  depth: number
  byContainer: Map<string, LinkedContainer>
  selectedDn: string | null
  onSelect: (dn: string | null) => void
  onDropPolicy: (target: DropTarget, policy: DraggedPolicy) => void
  /** A row was right-clicked and wants the menu, at this point. */
  onAskToLink: (target: DropTarget, at: { x: number; y: number }) => void
  /** A link row was right-clicked. It names itself, so it gets its own menu. */
  onAskAboutLink: (
    target: DropTarget,
    link: ContainerLink,
    at: { x: number; y: number },
  ) => void
  /** Whether a policy may be linked here, as the server decides it. */
  linkable: boolean
  revealDn: string | null
  initiallyOpen?: boolean
}) {
  const { t } = useI18n()
  // Read once, when this row first appears: the branches between the domain
  // and a remembered container open themselves, and nothing reopens later.
  const [open, setOpen] = useState(initiallyOpen || isAtOrBelow(revealDn, dn))
  const [over, setOver] = useState(false)

  const children = useQuery({
    queryKey: ['gpo-tree', dn],
    queryFn: () => api.gpoTree(dn),
    // Only once the branch is open. A closed branch is a question nobody asked.
    enabled: open,
    staleTime: 30_000,
  })

  const linked = byContainer.get(dn.toLowerCase())?.links ?? []
  const indent = { paddingLeft: `${depth * 14}px` }

  const rowClass = ['tree__row', selectedDn === dn ? 'tree__row--selected' : '', over ? 'tree__row--drop' : '']
    .filter(Boolean)
    .join(' ')

  // Worn by the container's own row and by each policy row beneath it. Those
  // rows read as part of the container — they are indented under it and
  // describe it — and aiming at one of them is the likeliest miss there is.
  // Landing on the container is what was meant, so that is what happens, and
  // the container's row is what lights up to say so.
  const dropZone = {
    onDragOver: (event: DragEvent<HTMLElement>) => {
      // Only our own drags. Everything else — a file from the desktop, a
      // selection from another page — has to keep falling through, and the
      // media type is the one thing readable while a drag is in the air.
      if (!isPolicyDrag(event)) return
      // A container that is on screen only because a link already sits on it.
      // Showing the link is the point; offering to add another is not.
      if (!linkable) return
      // Without this the browser refuses the drop and the row never becomes a
      // target at all.
      event.preventDefault()
      event.dataTransfer.dropEffect = 'link'
      if (!over) setOver(true)
    },
    onDragLeave: (event: DragEvent<HTMLElement>) => {
      // Moving onto a child of the row fires this too. Ignoring the case
      // where the pointer is still inside keeps the row from flickering
      // between marked and unmarked as it crosses the label.
      if (event.currentTarget.contains(event.relatedTarget as Node | null)) return
      setOver(false)
    },
    onDrop: (event: DragEvent<HTMLElement>) => {
      event.preventDefault()
      setOver(false)
      const policy = readPolicyDrag(event)
      if (policy && linkable) onDropPolicy({ dn, name, linkable }, policy)
    },
    // Worn by the same rows as the drop, for the same reason: a policy row is
    // indented under its container and reads as part of it, so aiming at one
    // is the likeliest miss there is. It opens the container's menu.
    onContextMenu: (event: MouseEvent<HTMLElement>) => {
      if (!linkable) return
      event.preventDefault()
      onSelect(dn)
      onAskToLink({ dn, name, linkable }, { x: event.clientX, y: event.clientY })
    },
  }

  return (
    <div className="tree__node">
      <div className={rowClass} style={indent} {...dropZone}>
        <button
          type="button"
          className="tree__toggle"
          aria-label={open ? t('tree.collapse') : t('tree.expand')}
          onClick={() => setOpen(!open)}
        >
          {open ? '▾' : '▸'}
        </button>
        <button
          type="button"
          className="tree__label"
          onClick={() => onSelect(dn)}
          onKeyDown={(event) => {
            if (!linkable) return
            if (!((event.shiftKey && event.key === 'F10') || event.key === 'ContextMenu')) return
            event.preventDefault()
            onSelect(dn)
            onAskToLink({ dn, name, linkable }, anchorOf(event.currentTarget))
          }}
          title={linkable ? dn : t('gpo.notLinkable')}
        >
          <span className={linkable ? undefined : 'muted'}>{name}</span>
          {linked.length > 0 && <span className="muted small"> {linked.length}</span>}
        </button>
      </div>

      {open && (
        <div className="tree__children">
          {/* The policies first, then the containers below — the same order
              GPMC uses, and the one that reads as "here, then onwards". */}
          {linked.map((link) => (
            <div
              className="tree__row"
              key={link.guid}
              style={{ paddingLeft: `${(depth + 1) * 14}px` }}
              {...dropZone}
              // Overrides the container's, which dropZone also carries. A drop
              // aimed here is charitably read as aimed at the container; a
              // right-click is not a miss, it names the row it landed on.
              onContextMenu={(event) => {
                event.preventDefault()
                onSelect(dn)
                onAskAboutLink(
                  { dn, name, linkable },
                  link,
                  { x: event.clientX, y: event.clientY },
                )
              }}
            >
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

          {/* No filtering here. Which containers belong in this tree is
              decided by the endpoint, from the one list of classes that can
              carry a gPLink — a second opinion in the browser is how the two
              start disagreeing. */}
          {(children.data?.nodes ?? []).map((node: LinkableNode) => (
            <ContainerNode
              key={node.dn}
              dn={node.dn}
              name={node.name}
              depth={depth + 1}
              byContainer={byContainer}
              selectedDn={selectedDn}
              onSelect={onSelect}
              onDropPolicy={onDropPolicy}
              onAskToLink={onAskToLink}
              onAskAboutLink={onAskAboutLink}
              linkable={node.linkable}
              revealDn={revealDn}
            />
          ))}
        </div>
      )}
    </div>
  )
}
/**
 * Removing one link, with the two facts that decide the answer.
 *
 * Which policy and where — because the same policy is usually linked in
 * several places, and "remove the link" without saying which one is the
 * question people answer wrongly.
 */
function UnlinkDialog({
  container,
  link,
  onClose,
  onDone,
}: {
  container: DropTarget
  link: ContainerLink
  onClose: () => void
  onDone: (message: string) => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [error, setError] = useState<unknown>(null)

  const name = link.display_name ?? t('gpo.linkMissingPolicy')

  const remove = useMutation({
    // By the DN the attribute holds, not by one looked up from the policy —
    // this has to work for a link whose policy is gone, which is one of the
    // reasons to remove it.
    mutationFn: () => api.unlinkGpo(container.dn, link.dn),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['gpo-link-map'] })
      void queryClient.invalidateQueries({ queryKey: ['gpo-locations', link.guid] })
      onDone(t('gpo.unlinkedFrom', { policy: name, container: container.name }))
    },
    onError: setError,
  })

  return createPortal(
    <Modal
      title={t('gpo.unlinkHere')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--danger"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            {t('gpo.unlink')}
          </button>
        </>
      }
    >
      <ErrorMessage error={error} />
      <p>{t('gpo.confirmUnlink', { policy: name, container: container.name })}</p>
      <p className="muted small">{t('gpo.confirmUnlinkHint')}</p>
    </Modal>,
    document.getElementById('overlays') ?? document.body,
  )
}
