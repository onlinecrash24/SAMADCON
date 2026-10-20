/**
 * The fields SAMADCON's settings make mandatory for a new user, as the New
 * user and Copy dialogs check them before "Create" is offered. The server
 * checks the same again; this is so the dialog can say what is missing.
 */

import type { MessageKey } from '../../i18n/messages'
import { FIELDS, type FieldDef } from './fieldDefs'

/** A field's label, by API name; the name itself for one the sheet has no field for. */
export function fieldLabel(name: string): MessageKey {
  return ((FIELDS as Record<string, FieldDef>)[name]?.label ?? name) as MessageKey
}

/** The required fields that are still empty. Spaces are empty. */
export function missingRequired(
  required: readonly string[],
  values: Record<string, string | undefined>,
  carried: readonly string[] = [],
): string[] {
  return required.filter((field) => !carried.includes(field) && !(values[field] ?? '').trim())
}

/**
 * What a copy takes from its template: the fields the server copies (it says
 * which) that the template has a value for.
 */
export function carriedFields(
  copied: readonly string[],
  template: Record<string, string | string[] | null | undefined>,
): string[] {
  return copied.filter((field) => {
    const value = template[field]
    return Array.isArray(value) ? value.length > 0 : Boolean(value?.trim())
  })
}
