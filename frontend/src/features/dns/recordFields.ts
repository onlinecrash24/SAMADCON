/**
 * What each DNS record type needs, for building its form.
 *
 * The field names match the API's payload exactly — the server validates
 * against the same set (samcon.ad.dnsrecords.validate_data), so a type added
 * on one side shows up as a clear error on the other rather than silently
 * doing nothing.
 */

import type { MessageKey } from '../../i18n/messages'

export type FieldType = 'text' | 'number' | 'lines'

export interface RecordField {
  name: string
  label: MessageKey
  type: FieldType
  placeholder?: string
  min?: number
  max?: number
}

export const RECORD_FIELDS: Record<string, RecordField[]> = {
  A: [{ name: 'address', label: 'dns.address', type: 'text', placeholder: '192.168.1.10' }],
  AAAA: [{ name: 'address', label: 'dns.address', type: 'text', placeholder: '2001:db8::1' }],
  CNAME: [{ name: 'target', label: 'dns.target', type: 'text', placeholder: 'host.example.lan' }],
  NS: [{ name: 'target', label: 'dns.nameserver', type: 'text', placeholder: 'dc1.example.lan' }],
  PTR: [{ name: 'target', label: 'dns.target', type: 'text', placeholder: 'host.example.lan' }],
  MX: [
    { name: 'preference', label: 'dns.preference', type: 'number', min: 0, max: 65535 },
    { name: 'exchange', label: 'dns.mailServer', type: 'text', placeholder: 'mail.example.lan' },
  ],
  SRV: [
    { name: 'priority', label: 'dns.priority', type: 'number', min: 0, max: 65535 },
    { name: 'weight', label: 'dns.weight', type: 'number', min: 0, max: 65535 },
    { name: 'port', label: 'dns.port', type: 'number', min: 1, max: 65535 },
    { name: 'target', label: 'dns.target', type: 'text', placeholder: 'dc1.example.lan' },
  ],
  TXT: [{ name: 'strings', label: 'dns.text', type: 'lines' }],
}

/** Types an administrator may create here. SOA is read-only by design. */
export const CREATABLE_TYPES = Object.keys(RECORD_FIELDS)

export const DEFAULT_VALUES: Record<string, Record<string, unknown>> = {
  MX: { preference: 10 },
  SRV: { priority: 0, weight: 100, port: 389 },
}

export function fieldsFor(type: string): RecordField[] {
  return RECORD_FIELDS[type] ?? []
}
