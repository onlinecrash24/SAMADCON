/**
 * Samba's own administrative templates, shipped inside the image.
 *
 * They matter more than "some extra templates" suggests. `samba.admx`
 * defines the settings samba-gpupdate applies on Linux members — smb.conf
 * options, the Unix cron scripts, sudo rights — and those are ordinary
 * registry policy, so the editor could always *write* them. What was missing
 * was the definitions that let it *show* them.
 *
 * Offered in two places: when the domain has no central store at all, and
 * beside a store that has one but not these.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../../api/endpoints'
import { ErrorMessage } from '../../../components/primitives'
import { useI18n } from '../../../i18n'

export function BundledTemplates({ onDone }: { onDone: () => void }) {
  const { t } = useI18n()
  const [error, setError] = useState<unknown>(null)

  const bundled = useQuery({
    queryKey: ['admx-bundled'],
    queryFn: () => api.bundledTemplates(),
    // The image does not change under us; asking once per session is enough.
    staleTime: Infinity,
  })

  const install = useMutation({
    mutationFn: () => api.installBundledTemplates(),
    onSuccess: onDone,
    onError: setError,
  })

  // Nothing shipped: an older image, or a build where the templates were not
  // unpacked. Saying nothing beats offering a button that cannot work.
  if (!bundled.data?.present) return null

  return (
    <div className="stack-tight">
      <p className="muted small">
        {t('admx.bundledHint', { names: bundled.data.templates.join(', ') })}
      </p>

      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      <div>
        <button
          type="button"
          className="button"
          disabled={install.isPending}
          onClick={() => install.mutate()}
        >
          {install.isPending ? t('status.loading') : t('admx.installBundled')}
        </button>
      </div>
    </div>
  )
}

/** Whether the store already holds the templates the image ships. */
export function useBundledMissing(installed: string[] | undefined): boolean {
  const bundled = useQuery({
    queryKey: ['admx-bundled'],
    queryFn: () => api.bundledTemplates(),
    staleTime: Infinity,
  })

  if (!bundled.data?.present || installed === undefined) return false
  const have = new Set(installed.map((name) => name.toLowerCase()))
  return bundled.data.templates.some((name) => !have.has(name.toLowerCase()))
}
