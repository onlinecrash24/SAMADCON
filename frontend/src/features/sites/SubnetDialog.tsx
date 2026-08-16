/** Create or edit a subnet and the site it maps to. */

import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { Site, Subnet } from '../../api/types'
import { ErrorMessage, Modal } from '../../components/primitives'
import { useI18n } from '../../i18n'

const UNASSIGNED = ''

interface SubnetDialogProps {
  subnet: Subnet | null
  sites: Site[]
  onClose: () => void
  onDone: () => void
}

export function SubnetDialog({ subnet, sites, onClose, onDone }: SubnetDialogProps) {
  const { t } = useI18n()
  const editing = subnet !== null

  const [name, setName] = useState(subnet?.name ?? '')
  const [siteDn, setSiteDn] = useState(subnet?.site_dn ?? UNASSIGNED)
  const [description, setDescription] = useState(subnet?.description ?? '')
  const [location, setLocation] = useState(subnet?.location ?? '')
  const [error, setError] = useState<unknown>(null)

  const save = useMutation({
    mutationFn: () => {
      if (editing) {
        return api.updateSubnet(subnet.dn, {
          // An empty selection is a deliberate "not assigned yet", which
          // site_dn alone cannot express.
          site_dn: siteDn === UNASSIGNED ? null : siteDn,
          clear_site: siteDn === UNASSIGNED,
          description: description || null,
          location: location || null,
        })
      }
      return api.createSubnet({
        name: name.trim(),
        site_dn: siteDn === UNASSIGNED ? null : siteDn,
        description: description || undefined,
        location: location || undefined,
      })
    },
    onSuccess: onDone,
    onError: setError,
  })

  return (
    <Modal
      title={editing ? t('sites.editSubnet') : t('sites.newSubnet')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!name.trim() || save.isPending}
            onClick={() => save.mutate()}
          >
            {editing ? t('action.save') : t('action.create')}
          </button>
        </>
      }
    >
      <ErrorMessage error={error} />

      <label className="field">
        <span className="field__label">{t('sites.subnet')}</span>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="192.168.1.0/24"
          // The name is the object's RDN, so renaming it is a different
          // operation than editing it — delete and recreate instead.
          disabled={editing}
          autoFocus={!editing}
        />
        <span className="field__hint">{t('sites.subnetHint')}</span>
      </label>

      <label className="field">
        <span className="field__label">{t('sites.site')}</span>
        <select value={siteDn} onChange={(event) => setSiteDn(event.target.value)}>
          <option value={UNASSIGNED}>{t('sites.unassigned')}</option>
          {sites.map((site) => (
            <option key={site.dn} value={site.dn}>
              {site.name}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span className="field__label">{t('sites.location')}</span>
        <input value={location} onChange={(event) => setLocation(event.target.value)} />
      </label>

      <label className="field">
        <span className="field__label">{t('sites.description')}</span>
        <input value={description} onChange={(event) => setDescription(event.target.value)} />
      </label>
    </Modal>
  )
}
