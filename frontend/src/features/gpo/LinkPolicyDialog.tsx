/**
 * The question a dropped policy asks before it is linked.
 *
 * Dropping is a gesture that can happen by accident — a pointer that slipped
 * one row while the button was down looks exactly like a decision — and what
 * it writes reaches every machine under the container on its next refresh. So
 * it asks, and it names both halves: which policy, and where.
 *
 * It adds a link; it never moves one. A policy is meant to apply in several
 * places at once, and the places it already applies are listed here so that is
 * visible at the moment of deciding rather than discovered afterwards. Further
 * targets can be picked in the same breath, because linking a new baseline to
 * six OUs one drag at a time is six chances to drop on the wrong row.
 *
 * Several targets are written one after another rather than in one call. Each
 * link is its own write against its own container and its own audit record,
 * and one of them failing says nothing about the others — so the outcome is
 * reported per target instead of as a single verdict.
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { ApiError } from '../../api/client'
import { api } from '../../api/endpoints'
import type { LinkableNode } from '../../api/types'
import { ErrorMessage, Modal, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { DraggedPolicy } from './policyDrag'

interface Target {
  dn: string
  name: string
  /** Whether a policy may be linked here, as the server decides it. */
  linkable: boolean
}

type Outcome = { kind: 'linked' } | { kind: 'already' } | { kind: 'failed'; message: string }

/** The domain a DN belongs to, spelled the way people say it. */
function domainOf(dn: string): Target {
  const parts = dn.split(',').filter((part) => /^DC=/i.test(part))
  return {
    dn: parts.join(','),
    name: parts.map((part) => part.slice(3)).join('.'),
    // The domain always is: it is where Default Domain Policy sits.
    linkable: true,
  }
}

export function LinkPolicyDialog({
  policy,
  target,
  onClose,
  onDone,
}: {
  /**
   * The policy being linked, when there is one.
   *
   * A drop arrives holding one. The menu on a container does not — you asked
   * to link *something* here — so the dialog asks which, and everything below
   * that point is the same either way.
   */
  policy: DraggedPolicy | null
  target: Target
  onClose: () => void
  onDone: (message: string) => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const [picked, setPicked] = useState<DraggedPolicy | null>(null)
  const chosen = policy ?? picked

  // Only when there is choosing to do. Opened from a drop this never runs.
  const catalogue = useQuery({
    queryKey: ['gpos'],
    queryFn: () => api.gpos(),
    enabled: policy === null,
  })

  const [targets, setTargets] = useState<Target[]>([target])
  const [picking, setPicking] = useState(false)
  // A breadcrumb rather than a bare DN: walking back up needs the name of the
  // container being returned to, and a DN alone cannot supply one. The domain
  // is kept out of the list so that there is always somewhere to be.
  const root = domainOf(target.dn)
  const [path, setPath] = useState<Target[]>([])
  const [pending, setPending] = useState(false)
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({})
  const [error, setError] = useState<unknown>(null)

  const here = path[path.length - 1] ?? root

  // Shared with the tree this was dropped on, so opening the dialog costs no
  // second call. Used only to say what is already true — never to decide what
  // to send: it is up to thirty seconds old, and skipping a target on that
  // basis could quietly link nothing at all.
  const linkMap = useQuery({
    queryKey: ['gpo-link-map'],
    queryFn: () => api.gpoLinkMap(),
    staleTime: 30_000,
  })

  const linksThis = (guid: string) =>
    chosen !== null && guid.toUpperCase() === chosen.guid.toUpperCase()

  const alreadyAt = (dn: string) =>
    (linkMap.data?.containers ?? [])
      .find((node) => node.dn.toLowerCase() === dn.toLowerCase())
      ?.links.some((link) => linksThis(link.guid)) ?? false

  const elsewhere = (linkMap.data?.containers ?? []).filter((node) =>
    node.links.some((link) => linksThis(link.guid)),
  )

  // Deliberately the wide form: everything that can hold children, each one
  // carrying the server's verdict on whether it can hold a link. The tree
  // beside this dialog shows only the linkable ones, which is what was asked
  // of it — but a picker that cannot walk past a plain container cannot reach
  // whatever is under it, and nothing here can show that nothing ever is.
  const children = useQuery({
    queryKey: ['gpo-link-target', here.dn],
    queryFn: () => api.gpoTree(here.dn, false),
    enabled: picking,
  })

  const containersHere = children.data?.nodes ?? []

  const add = (candidate: Target) => {
    setTargets((current) =>
      current.some((item) => item.dn.toLowerCase() === candidate.dn.toLowerCase())
        ? current
        : [...current, candidate],
    )
  }

  const submit = async () => {
    if (!chosen) return
    setError(null)
    setPending(true)
    const results: Record<string, Outcome> = {}

    for (const item of targets) {
      try {
        await api.linkGpo(item.dn, chosen.dn)
        results[item.dn] = { kind: 'linked' }
      } catch (cause) {
        // Already linked is not a failure of this action. Whoever pressed the
        // button wanted the policy linked there, and it is.
        if (cause instanceof ApiError && cause.code === 'gpo_link_exists') {
          results[item.dn] = { kind: 'already' }
        } else {
          results[item.dn] = {
            kind: 'failed',
            message: cause instanceof Error ? cause.message : String(cause),
          }
        }
      }
    }

    setOutcomes(results)
    setPending(false)

    void queryClient.invalidateQueries({ queryKey: ['gpo-link-map'] })
    void queryClient.invalidateQueries({ queryKey: ['gpo-locations', chosen.guid] })

    // Stays open when something failed, with the list below saying which.
    if (targets.some((item) => results[item.dn]?.kind === 'failed')) return

    const only = targets.length === 1 ? targets[0] : undefined
    onDone(
      only
        ? t('gpo.linkedTo', { policy: chosen.name, container: only.name })
        : t('gpo.linkedToMany', { policy: chosen.name, count: targets.length }),
    )
    onClose()
  }

  return (
    <Modal
      title={chosen ? t('gpo.linkDropTitle', { policy: chosen.name }) : t('gpo.linkHere')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={pending || targets.length === 0 || !chosen}
            onClick={() => void submit()}
          >
            {t('gpo.link')}
          </button>
        </>
      }
    >
      <div className="form">
        <ErrorMessage error={error} onDismiss={() => setError(null)} />

        {/* Only when the dialog was opened without one. A drop has already
            said which policy, and asking again would be asking twice. */}
        {policy === null && (
          <label className="field">
            <span className="field__label">{t('gpo.name')}</span>
            <select
              value={picked?.dn ?? ''}
              onChange={(event) => {
                const found = (catalogue.data?.gpos ?? []).find(
                  (entry) => entry.dn === event.target.value,
                )
                setPicked(
                  found
                    ? { dn: found.dn, guid: found.guid, name: found.display_name ?? found.guid }
                    : null,
                )
              }}
            >
              <option value="">{t('gpo.pickPolicy')}</option>
              {(catalogue.data?.gpos ?? []).map((entry) => (
                <option key={entry.dn} value={entry.dn}>
                  {entry.display_name ?? entry.guid}
                </option>
              ))}
            </select>
          </label>
        )}

        <p>{t('gpo.linkDropBody')}</p>

        <ul className="plain-list">
          {targets.map((item) => {
            const outcome = outcomes[item.dn]
            return (
              <li key={item.dn}>
                <strong>{item.name}</strong> <span className="muted small mono">{item.dn}</span>
                {outcome?.kind === 'linked' && (
                  <span className="muted small"> — {t('gpo.linked')}</span>
                )}
                {(outcome?.kind === 'already' || (!outcome && alreadyAt(item.dn))) && (
                  <span className="muted small"> — {t('gpo.linkAlreadyHere')}</span>
                )}
                {!outcome && targets.length > 1 && (
                  <>
                    {' '}
                    <button
                      type="button"
                      className="link"
                      onClick={() =>
                        setTargets((current) => current.filter((other) => other.dn !== item.dn))
                      }
                    >
                      {t('action.remove')}
                    </button>
                  </>
                )}
                {outcome?.kind === 'failed' && (
                  <div className="alert alert--warning">{outcome.message}</div>
                )}
              </li>
            )
          })}
        </ul>

        {/* Where it already applies. The point of saying so here is that this
            dialog adds a place rather than changing one, and naming the others
            is the shortest way to make that plain. */}
        {elsewhere.length > 0 && (
          <p className="muted small">
            {t('gpo.linkElsewhere', {
              containers: elsewhere.map((node) => node.name).join(', '),
            })}
          </p>
        )}

        {!picking ? (
          <div className="pane__actions">
            <button type="button" className="button" onClick={() => setPicking(true)}>
              + {t('gpo.linkAddTarget')}
            </button>
          </div>
        ) : (
          <>
            <div className="pane__actions">
              <button
                type="button"
                className="button"
                disabled={path.length === 0}
                onClick={() => setPath((current) => current.slice(0, -1))}
              >
                {t('dialog.moveUp')}
              </button>
              <button
                type="button"
                className="button"
                disabled={
                  !here.linkable ||
                  targets.some((item) => item.dn.toLowerCase() === here.dn.toLowerCase())
                }
                onClick={() => add(here)}
              >
                + {here.name}
              </button>
            </div>

            {/* Said rather than left to a greyed-out button. Somewhere to
                stand that is not somewhere to link is exactly the case a
                disabled control explains badly. */}
            {!here.linkable && <p className="muted small">{t('gpo.notLinkable')}</p>}

            {children.isLoading && <Spinner label={t('status.loading')} />}
            {children.error && <ErrorMessage error={children.error} />}

            <ul className="plain-list">
              {/* Only what can hold a link. Listing every user under a
                  container would bury the handful of places worth picking. */}
              {containersHere.map((node: LinkableNode) => (
                <li key={node.dn}>
                  <button
                    type="button"
                    className="button"
                    onClick={() => setPath((current) => [...current, node])}
                  >
                    {node.name}
                  </button>
                </li>
              ))}
            </ul>

            {containersHere.length === 0 && !children.isLoading && (
              <p className="muted small">{t('dialog.moveNoChildren')}</p>
            )}
          </>
        )}

        <p className="muted small">{t('gpo.linkDropDefaults')}</p>
      </div>
    </Modal>
  )
}
