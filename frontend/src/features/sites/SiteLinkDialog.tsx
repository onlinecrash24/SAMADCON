/** Create or edit a site link: which sites it connects, at what cost. */

import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { Site, SiteLink } from '../../api/types'
import { ErrorMessage, Modal } from '../../components/primitives'
import { useI18n } from '../../i18n'

interface SiteLinkDialogProps {
  link: SiteLink | null
  sites: Site[]
  onClose: () => void
  onDone: () => void
}

export function SiteLinkDialog({ link, sites, onClose, onDone }: SiteLinkDialogProps) {
  const { t } = useI18n()
  const editing = link !== null

  const [name, setName] = useState(link?.name ?? '')
  const [selected, setSelected] = useState<string[]>(link?.site_dns ?? [])
  const [cost, setCost] = useState(String(link?.cost ?? 100))
  const [interval, setInterval] = useState(String(link?.replication_interval ?? 180))
  const [description, setDescription] = useState(link?.description ?? '')
  const [error, setError] = useState<unknown>(null)

  const toggle = (dn: string) => {
    setSelected((current) =>
      current.includes(dn) ? current.filter((item) => item !== dn) : [...current, dn],
    )
  }

  const save = useMutation({
    mutationFn: () => {
      const numbers = { cost: Number(cost), replication_interval: Number(interval) }
      if (editing) {
        return api.updateSiteLink(link.dn, {
          site_dns: selected,
          ...numbers,
          description: description || null,
        })
      }
      return api.createSiteLink({
        name: name.trim(),
        site_dns: selected,
        ...numbers,
        description: description || undefined,
      })
    },
    onSuccess: onDone,
    onError: setError,
  })

  // A link across fewer than two sites describes no path, and the KCC ignores
  // it without saying so — better caught here than wondered about later.
  const enoughSites = selected.length >= 2

  return (
    <Modal
      title={editing ? t('sites.editLink') : t('sites.newLink')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!name.trim() || !enoughSites || save.isPending}
            onClick={() => save.mutate()}
          >
            {editing ? t('action.save') : t('action.create')}
          </button>
        </>
      }
    >
      <ErrorMessage error={error} />

      <label className="field">
        <span className="field__label">{t('sites.name')}</span>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          disabled={editing}
          autoFocus={!editing}
        />
      </label>

      <fieldset className="field">
        <legend className="field__label">{t('sites.linkedSites')}</legend>
        <div className="checklist">
          {sites.map((site) => (
            <label key={site.dn} className="checkbox">
              <input
                type="checkbox"
                checked={selected.includes(site.dn)}
                onChange={() => toggle(site.dn)}
              />
              <span>{site.name}</span>
            </label>
          ))}
        </div>
        {!enoughSites && <span className="field__hint">{t('sites.twoSitesNeeded')}</span>}
      </fieldset>

      <div className="field-row">
        <label className="field">
          <span className="field__label">{t('sites.cost')}</span>
          <input
            type="number"
            min={1}
            max={32767}
            value={cost}
            onChange={(event) => setCost(event.target.value)}
          />
          <span className="field__hint">{t('sites.costHint')}</span>
        </label>

        <label className="field">
          <span className="field__label">{t('sites.interval')}</span>
          <input
            type="number"
            min={15}
            max={10080}
            step={15}
            value={interval}
            onChange={(event) => setInterval(event.target.value)}
          />
          <span className="field__hint">{t('sites.intervalHint')}</span>
        </label>
      </div>

      <label className="field">
        <span className="field__label">{t('sites.description')}</span>
        <input value={description} onChange={(event) => setDescription(event.target.value)} />
      </label>
    </Modal>
  )
}
