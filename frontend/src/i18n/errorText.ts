/**
 * The words for an error, from its stable code.
 *
 * Pure, so it can be checked without a React tree. The status goes into the
 * text because an answer that did not come from SAMADCON — an HTML page from
 * nginx, or from a proxy in front of it — has nothing else to tell: "The
 * upload failed." said neither what nor where, and was all an administrator
 * saw of a full nginx spool on a 14 MB upload.
 */

import { ApiError } from '../api/client'

export function errorText(catalogue: Partial<Record<string, string>>, error: unknown): string {
  if (error instanceof ApiError) {
    const template = catalogue[`error.${error.code}`]
    // An unmapped code still has a usable English message from the server.
    if (template === undefined) return error.message
    return template.replaceAll('{status}', String(error.status))
  }
  if (error instanceof Error) return error.message
  return String(error)
}
