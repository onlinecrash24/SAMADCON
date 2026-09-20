import { Field } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import { DnField } from '../DnField'
import type { FieldDef } from '../fieldDefs'
import { UpnField } from '../UpnField'
import { useSheet } from './SheetContext'

/**
 * One field of the sheet, drawn from its definition and bound to the draft.
 *
 * The definition says what the field is — text, a UPN, a reference to another
 * object — and the draft says what it holds. Nothing here decides when it is
 * written; that is the footer's job.
 */
export function FieldInput({ field }: { field: FieldDef }) {
  const { t } = useI18n()
  const { get, set, busy } = useSheet()
  const value = get(field.name)
  const onChange = (next: string) => set(field.name, next)

  return (
    <Field label={t(field.label)} hint={field.hint ? t(field.hint) : undefined}>
      {field.kind === 'dn' ? (
        <DnField value={value} types={field.pickTypes ?? ['user']} onChange={onChange} disabled={busy} />
      ) : field.kind === 'upn' ? (
        <UpnField value={value} onChange={onChange} disabled={busy} />
      ) : field.kind === 'multiline' ? (
        <textarea
          rows={3}
          value={value}
          maxLength={field.maxLength}
          disabled={busy}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          type={field.kind ?? 'text'}
          value={value}
          maxLength={field.maxLength}
          disabled={busy}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </Field>
  )
}

/** A row of fields side by side — first name and initials, city and state. */
export function FieldRow({ fields }: { fields: FieldDef[] }) {
  return (
    <div className="field-row">
      {fields.map((field) => (
        <FieldInput key={field.name} field={field} />
      ))}
    </div>
  )
}
