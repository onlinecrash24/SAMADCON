/**
 * Sites and services.
 *
 * RSAT splits this across a tree of sites, each with servers, plus separate
 * folders for subnets and inter-site transports. That layout mirrors the
 * directory, not the questions people ask of it — "which subnet belongs where"
 * and "how are the sites connected" are two lists, so they are two tabs here.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { Site, SiteLink, Subnet } from '../../api/types'
import { Badge, ErrorMessage, Modal, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import { SiteLinkDialog } from './SiteLinkDialog'
import { SubnetDialog } from './SubnetDialog'

type Tab = 'sites' | 'subnets' | 'links'

interface SitesViewProps {
  onChanged: (message: string) => void
}

export function SitesView({ onChanged }: SitesViewProps) {
  const { t, tn } = useI18n()
  const queryClient = useQueryClient()

  const [tab, setTab] = useState<Tab>('sites')
  const [error, setError] = useState<unknown>(null)
  const [newSite, setNewSite] = useState(false)
  const [editingSubnet, setEditingSubnet] = useState<Subnet | null>(null)
  const [newSubnet, setNewSubnet] = useState(false)
  const [editingLink, setEditingLink] = useState<SiteLink | null>(null)
  const [newLink, setNewLink] = useState(false)
  const [confirm, setConfirm] = useState<{ kind: Tab; dn: string; name: string } | null>(null)

  const topology = useQuery({ queryKey: ['topology'], queryFn: () => api.topology() })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['topology'] })
  }

  const remove = useMutation({
    mutationFn: ({ kind, dn }: { kind: Tab; dn: string }) => {
      if (kind === 'subnets') return api.deleteSubnet(dn)
      if (kind === 'links') return api.deleteSiteLink(dn)
      return api.deleteSite(dn)
    },
    onSuccess: () => {
      setError(null)
      setConfirm(null)
      refresh()
      onChanged(t('sites.deleted'))
    },
    onError: setError,
  })

  if (topology.isLoading) return <Spinner label={t('status.loading')} />
  if (topology.error) return <ErrorMessage error={topology.error} />

  const data = topology.data
  if (!data) return null

  return (
    <>
      <div className="pane__header">
        <div className="tabs">
          <button
            type="button"
            className={tab === 'sites' ? 'tabs__tab tabs__tab--active' : 'tabs__tab'}
            onClick={() => setTab('sites')}
          >
            {t('sites.tabSites')} ({data.sites.length})
          </button>
          <button
            type="button"
            className={tab === 'subnets' ? 'tabs__tab tabs__tab--active' : 'tabs__tab'}
            onClick={() => setTab('subnets')}
          >
            {t('sites.tabSubnets')} ({data.subnets.length})
          </button>
          <button
            type="button"
            className={tab === 'links' ? 'tabs__tab tabs__tab--active' : 'tabs__tab'}
            onClick={() => setTab('links')}
          >
            {t('sites.tabLinks')} ({data.links.length})
          </button>
        </div>

        <div className="pane__actions">
          {tab === 'sites' && (
            <button type="button" className="button" onClick={() => setNewSite(true)}>
              + {t('sites.newSite')}
            </button>
          )}
          {tab === 'subnets' && (
            <button type="button" className="button" onClick={() => setNewSubnet(true)}>
              + {t('sites.newSubnet')}
            </button>
          )}
          {tab === 'links' && (
            <button type="button" className="button" onClick={() => setNewLink(true)}>
              + {t('sites.newLink')}
            </button>
          )}
        </div>
      </div>

      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      {tab === 'sites' && (
        <SiteTable sites={data.sites} onDelete={(site) =>
          setConfirm({ kind: 'sites', dn: site.dn, name: site.name })
        } />
      )}

      {tab === 'subnets' && (
        <SubnetTable
          subnets={data.subnets}
          onEdit={setEditingSubnet}
          onDelete={(subnet) => setConfirm({ kind: 'subnets', dn: subnet.dn, name: subnet.name })}
        />
      )}

      {tab === 'links' && (
        <LinkTable
          links={data.links}
          onEdit={setEditingLink}
          onDelete={(link) => setConfirm({ kind: 'links', dn: link.dn, name: link.name })}
        />
      )}

      {newSite && (
        <NewSiteDialog
          onClose={() => setNewSite(false)}
          onDone={() => {
            setNewSite(false)
            refresh()
            onChanged(t('sites.created'))
          }}
        />
      )}

      {(newSubnet || editingSubnet) && (
        <SubnetDialog
          subnet={editingSubnet}
          sites={data.sites}
          onClose={() => {
            setNewSubnet(false)
            setEditingSubnet(null)
          }}
          onDone={() => {
            setNewSubnet(false)
            setEditingSubnet(null)
            refresh()
            onChanged(t('sites.saved'))
          }}
        />
      )}

      {(newLink || editingLink) && (
        <SiteLinkDialog
          link={editingLink}
          sites={data.sites}
          onClose={() => {
            setNewLink(false)
            setEditingLink(null)
          }}
          onDone={() => {
            setNewLink(false)
            setEditingLink(null)
            refresh()
            onChanged(t('sites.saved'))
          }}
        />
      )}

      {confirm && (
        <Modal
          title={t('sites.confirmDeleteTitle')}
          onClose={() => setConfirm(null)}
          footer={
            <>
              <button type="button" className="button" onClick={() => setConfirm(null)}>
                {t('action.cancel')}
              </button>
              <button
                type="button"
                className="button button--danger"
                disabled={remove.isPending}
                onClick={() => remove.mutate({ kind: confirm.kind, dn: confirm.dn })}
              >
                {t('action.delete')}
              </button>
            </>
          }
        >
          <p>{t('sites.confirmDelete', { name: confirm.name })}</p>
        </Modal>
      )}

      {tab === 'sites' && data.sites.length > 0 && (
        <p className="muted small pane__footnote">
          {tn('sites.serverCount', data.sites.reduce((sum, site) => sum + (site.servers?.length ?? 0), 0))}
        </p>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

function SiteTable({ sites, onDelete }: { sites: Site[]; onDelete: (site: Site) => void }) {
  const { t } = useI18n()

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>{t('sites.name')}</th>
            <th>{t('sites.servers')}</th>
            <th>{t('sites.subnets')}</th>
            <th>{t('sites.description')}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {sites.map((site) => (
            <tr key={site.dn}>
              <td>
                <strong>{site.name}</strong>
                {site.location && <div className="muted small">{site.location}</div>}
              </td>
              <td>
                {(site.servers ?? []).length === 0 ? (
                  <span className="muted">—</span>
                ) : (
                  <div className="stack-tight">
                    {(site.servers ?? []).map((server) => (
                      <div key={server.dn}>
                        {server.name}{' '}
                        {server.is_global_catalog && <Badge tone="ok">{t('sites.gc')}</Badge>}
                        {!server.is_dc && <Badge tone="muted">{t('sites.notDc')}</Badge>}
                      </div>
                    ))}
                  </div>
                )}
              </td>
              <td>{site.subnet_count ?? 0}</td>
              <td className="muted">{site.description ?? ''}</td>
              <td className="table__actions">
                <button type="button" className="link link--danger" onClick={() => onDelete(site)}>
                  {t('action.delete')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SubnetTable({
  subnets,
  onEdit,
  onDelete,
}: {
  subnets: Subnet[]
  onEdit: (subnet: Subnet) => void
  onDelete: (subnet: Subnet) => void
}) {
  const { t } = useI18n()

  if (subnets.length === 0) {
    return <p className="placeholder muted">{t('sites.noSubnets')}</p>
  }

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>{t('sites.subnet')}</th>
            <th>{t('sites.site')}</th>
            <th>{t('sites.location')}</th>
            <th>{t('sites.description')}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {subnets.map((subnet) => (
            <tr key={subnet.dn}>
              <td className="mono">{subnet.name}</td>
              <td>
                {subnet.site ?? <Badge tone="warn">{t('sites.unassigned')}</Badge>}
              </td>
              <td className="muted">{subnet.location ?? ''}</td>
              <td className="muted">{subnet.description ?? ''}</td>
              <td className="table__actions">
                <button type="button" className="link" onClick={() => onEdit(subnet)}>
                  {t('action.edit')}
                </button>
                <button
                  type="button"
                  className="link link--danger"
                  onClick={() => onDelete(subnet)}
                >
                  {t('action.delete')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LinkTable({
  links,
  onEdit,
  onDelete,
}: {
  links: SiteLink[]
  onEdit: (link: SiteLink) => void
  onDelete: (link: SiteLink) => void
}) {
  const { t } = useI18n()

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>{t('sites.name')}</th>
            <th>{t('sites.linkedSites')}</th>
            <th>{t('sites.cost')}</th>
            <th>{t('sites.interval')}</th>
            <th>{t('sites.transport')}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {links.map((link) => (
            <tr key={link.dn}>
              <td>
                <strong>{link.name}</strong>
                {link.description && <div className="muted small">{link.description}</div>}
              </td>
              <td>{link.sites.join(', ')}</td>
              <td>{link.cost}</td>
              <td>{t('sites.minutes', { count: link.replication_interval })}</td>
              <td>
                <Badge tone={link.transport === 'IP' ? 'muted' : 'warn'}>{link.transport}</Badge>
              </td>
              <td className="table__actions">
                <button type="button" className="link" onClick={() => onEdit(link)}>
                  {t('action.edit')}
                </button>
                <button type="button" className="link link--danger" onClick={() => onDelete(link)}>
                  {t('action.delete')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// New site
// ---------------------------------------------------------------------------

function NewSiteDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { t } = useI18n()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<unknown>(null)

  const create = useMutation({
    mutationFn: () => api.createSite({ name: name.trim(), description: description || undefined }),
    onSuccess: onDone,
    onError: setError,
  })

  return (
    <Modal
      title={t('sites.newSite')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!name.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            {t('action.create')}
          </button>
        </>
      }
    >
      <ErrorMessage error={error} />
      <label className="field">
        <span className="field__label">{t('sites.name')}</span>
        <input value={name} onChange={(event) => setName(event.target.value)} autoFocus />
        <span className="field__hint">{t('sites.nameHint')}</span>
      </label>
      <label className="field">
        <span className="field__label">{t('sites.description')}</span>
        <input value={description} onChange={(event) => setDescription(event.target.value)} />
      </label>
    </Modal>
  )
}
