/**
 * The words for an error, from its stable code.
 *
 * Pure, so it can be checked without a React tree. The status goes into the
 * text because an answer that did not come from SAMADCON — an HTML page from
 * nginx, or from a proxy in front of it — has nothing else to tell: "The
 * upload failed." said neither what nor where, and was all an administrator
 * saw of a full nginx spool on a 14 MB upload.
 *
 * One code can stand for several reasons. The template import has five for
 * `invalid_template`, told apart by `context.reason`: the reason's own entry
 * wins over the code's. Placeholders are filled from the context — `{file}`
 * above all, because a package holds hundreds of files and the server's
 * sentence named none of them.
 */

import { ApiError } from '../api/client'

type Catalogue = Partial<Record<string, string>>

function reasonOf(error: ApiError): string | undefined {
  const reason = error.context?.reason
  return typeof reason === 'string' ? reason : undefined
}

/** The template with its placeholders filled, or undefined if one cannot be. */
function fill(template: string, error: ApiError): string | undefined {
  const values: Record<string, unknown> = { ...error.context, status: error.status }
  let complete = true
  const text = template.replace(/\{(\w+)\}/g, (whole, name: string) => {
    const value = values[name]
    if (Array.isArray(value)) return value.join(', ')
    if (typeof value === 'string' || typeof value === 'number') return String(value)
    complete = false
    return whole
  })
  return complete ? text : undefined
}

function lookup(catalogue: Catalogue, error: ApiError, suffix = ''): string | undefined {
  const reason = reasonOf(error)
  const specific = reason ? catalogue[`error.${error.code}.${reason}${suffix}`] : undefined
  return specific ?? catalogue[`error.${error.code}${suffix}`]
}

export function errorText(catalogue: Catalogue, error: unknown): string {
  if (error instanceof ApiError) {
    const template = lookup(catalogue, error)
    // An unmapped code still has a usable English message from the server,
    // and so has one whose context lacks a value the translation names: a
    // sentence with "{file}" in it is worse than the server's.
    return (template && fill(template, error)) ?? error.message
  }
  if (error instanceof Error) return error.message
  return String(error)
}

/** The advice that goes with an error: translated where we have it, else the server's. */
export function errorHint(catalogue: Catalogue, error: unknown): string | undefined {
  if (!(error instanceof ApiError)) return undefined
  const template = lookup(catalogue, error, '.hint')
  return (template && fill(template, error)) ?? error.hint
}
