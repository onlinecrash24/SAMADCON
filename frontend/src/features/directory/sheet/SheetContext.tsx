import { createContext, useContext, type ReactNode } from 'react'

import type { DirectoryObject } from '../../../api/types'
import type { Draft, SheetBase } from './draft'

/**
 * What every tab of a property sheet sees: the object, what the directory
 * said about it, and the one draft the whole window shares.
 *
 * A tab reads a field with `get` and writes it with `set`; it never keeps a
 * value of its own and never calls the API. That is the rule that makes OK,
 * Apply and Cancel mean the same thing on every tab — the sheet owns the
 * draft, and the footer is the only place it is written from.
 */
export interface SheetApi {
  object: DirectoryObject
  base: SheetBase
  draft: Draft
  setDraft: (update: (current: Draft) => Draft) => void
  /** A field's current value: the draft's if touched, else the directory's. */
  get: (name: string) => string
  set: (name: string, value: string) => void
  /** The "Other…" lists: several values under one name. */
  getList: (name: string) => string[]
  setList: (name: string, values: string[]) => void
  flag: (name: string) => boolean
  setFlag: (name: string, value: boolean) => void
  /** Apply is running; inputs go quiet rather than accepting a second edit mid-write. */
  busy: boolean
}

const Context = createContext<SheetApi | null>(null)

export function SheetProvider({ value, children }: { value: SheetApi; children: ReactNode }) {
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useSheet(): SheetApi {
  const api = useContext(Context)
  if (!api) throw new Error('useSheet() outside a property sheet')
  return api
}
