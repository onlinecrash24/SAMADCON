/**
 * Dragging a policy onto a container.
 *
 * The two ends of this gesture sit in different panes — the list on the right
 * starts it, the tree on the left accepts it — and they never see each other.
 * What they share is this format, which is why it lives here rather than being
 * written out at both ends: a payload one side spelled slightly differently
 * from the other fails as a silently ignored drop, with nothing to read.
 *
 * The custom media type does double duty. It carries the payload, and it is
 * the only thing a drop target can inspect while a drag is still in the air —
 * getData is deliberately blocked until the drop, so a tree that wanted to
 * light up under the pointer has nothing else to go on. Anything dragged in
 * from outside the application therefore simply does not register.
 */

import type { DragEvent } from 'react'

export const POLICY_DRAG_TYPE = 'application/x-samadcon-gpo'

export interface DraggedPolicy {
  /** The policy's own DN — what the link is written against. */
  dn: string
  guid: string
  name: string
}

export function startPolicyDrag(event: DragEvent, policy: DraggedPolicy): void {
  event.dataTransfer.setData(POLICY_DRAG_TYPE, JSON.stringify(policy))
  // A link, not a move: the policy stays where it is and gains a place where
  // it applies. The pointer says so before anything is dropped.
  event.dataTransfer.effectAllowed = 'link'
}

/** Whether the thing under the pointer is one of ours, mid-drag. */
export function isPolicyDrag(event: DragEvent): boolean {
  return event.dataTransfer.types.includes(POLICY_DRAG_TYPE)
}

export function readPolicyDrag(event: DragEvent): DraggedPolicy | null {
  const raw = event.dataTransfer.getData(POLICY_DRAG_TYPE)
  if (!raw) return null

  try {
    const value = JSON.parse(raw) as Partial<DraggedPolicy>
    // Checked rather than trusted. The payload crosses a browser API that any
    // page can write to, and a half-formed one would reach the confirmation
    // dialog as a policy with no name.
    if (typeof value.dn === 'string' && typeof value.guid === 'string') {
      return { dn: value.dn, guid: value.guid, name: value.name ?? value.guid }
    }
  } catch {
    // Not ours, or not intact. Either way there is nothing to link.
  }
  return null
}
