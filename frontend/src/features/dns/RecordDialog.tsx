/**
 * Creating and editing a DNS record.
 *
 * When editing, the values the record currently has travel back to the server
 * as ``old_data``: a name holds several records without identifiers, so that
 * is how the right one is found. If it no longer looks that way, someone else
 * changed it and the server refuses instead of overwriting.
 */

import { useMutation } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'

import { api } from '../../api/endpoints'
import type { DnsRecord, DnsRecordData } from '../../api/types'
import { ErrorMessage, Field, Modal } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'
import { CREATABLE_TYPES, DEFAULT_VALUES, fieldsFor } from './recordFields'

interface RecordDialogProps {
  zone: string
  zoneDn: string
  defaultTtl: number
  /** Absent when creating. */
  existing?: DnsRecord
  onClose: () => void
  onDone: (message: string) => void
}

export function RecordDialog({
  zone,
  zoneDn,
  defaultTtl,
  existing,
  onClose,
  onDone,
}: RecordDialogProps) {
  const { t } = useI18n()
  const editing = Boolean(existing)

  const [type, setType] = useState(existing?.type ?? 'A')
  const [name, setName] = useState(existing?.node ?? '')
  const [ttl, setTtl] = useState(String(existing?.ttl ?? defaultTtl))
  const [data, setData] = useState<Record<string, unknown>>(
    () => ({ ...(DEFAULT_VALUES[existing?.type ?? 'A'] ?? {}), ...(existing?.data ?? {}) }),
  )

  const fields = useMemo(() => fieldsFor(type), [type])

  const save = useMutation({
    mutationFn: () => {
      const payload = buildData(type, data)
      const seconds = Number(ttl)
      // '@' is how the zone's own records are addressed; an empty field means
      // the same thing and is friendlier to type.
      const target = name.trim() || '@'

      return editing
        ? api.updateDnsRecord(zoneDn, {
            zone,
            name: existing!.node,
            type,
            old_data: existing!.data,
            data: payload,
            ttl: seconds,
          })
        : api.createDnsRecord(zoneDn, { zone, name: target, type, data: payload, ttl: seconds })
    },
    onSuccess: () => onDone(t(editing ? 'status.saved' : 'dns.recordCreated')),
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }

  return (
    <Modal
      title={t(editing ? 'dns.editRecord' : 'dns.newRecord')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="submit"
            form="dns-record"
            className="button button--primary"
            disabled={save.isPending}
          >
            {t(editing ? 'action.save' : 'action.create')}
          </button>
        </>
      }
    >
      <form id="dns-record" className="form" onSubmit={submit}>
        <ErrorMessage error={save.error} />

        <Field label={t('dns.recordType')}>
          <select
            value={type}
            // Changing the type on an existing record would be a different
            // record; only creation offers the choice.
            disabled={editing}
            onChange={(event) => {
              setType(event.target.value)
              setData({ ...(DEFAULT_VALUES[event.target.value] ?? {}) })
            }}
          >
            {CREATABLE_TYPES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </Field>

        <Field label={t('dns.recordName')} hint={t('dns.recordNameHint', { zone })}>
          <input
            value={name}
            disabled={editing}
            placeholder="@"
            onChange={(event) => setName(event.target.value)}
          />
        </Field>

        {fields.map((field) => (
          <Field key={field.name} label={t(field.label)}>
            {field.type === 'lines' ? (
              <textarea
                rows={3}
                value={toLines(data[field.name])}
                onChange={(event) =>
                  setData((current) => ({ ...current, [field.name]: event.target.value }))
                }
              />
            ) : (
              <input
                type={field.type === 'number' ? 'number' : 'text'}
                min={field.min}
                max={field.max}
                placeholder={field.placeholder}
                value={String(data[field.name] ?? '')}
                onChange={(event) =>
                  setData((current) => ({ ...current, [field.name]: event.target.value }))
                }
              />
            )}
          </Field>
        ))}

        <Field label={t('dns.ttl')} hint={t('dns.ttlHint')}>
          <input
            type="number"
            min={0}
            value={ttl}
            onChange={(event) => setTtl(event.target.value)}
          />
        </Field>
      </form>
    </Modal>
  )
}

function toLines(value: unknown): string {
  if (Array.isArray(value)) return value.join('\n')
  return String(value ?? '')
}

/** Shape the form state into the payload the API expects for this type. */
function buildData(type: string, raw: Record<string, unknown>): DnsRecordData {
  const result: DnsRecordData = {}
  for (const field of fieldsFor(type)) {
    const value = raw[field.name]
    if (field.type === 'number') {
      result[field.name] = Number(value)
    } else if (field.type === 'lines') {
      result[field.name] = toLines(value)
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line.length > 0)
    } else {
      result[field.name] = String(value ?? '').trim()
    }
  }
  return result
}

/** Title for the delete confirmation, shared with the zone view. */
export function describeRecord(record: DnsRecord, t: (key: MessageKey) => string): string {
  return `${record.name} ${record.type} ${record.display}` || t('dns.record')
}
