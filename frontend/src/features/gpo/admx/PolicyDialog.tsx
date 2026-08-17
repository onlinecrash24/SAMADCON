/**
 * One setting: three states, and a form built from the template.
 *
 * The inputs come from the ADML's presentation — the order and the labels
 * Microsoft chose — falling back to one input per element when a template
 * names no presentation. Plainer than GPMC in that case, but no element is
 * ever left unreachable.
 *
 * The inputs are disabled unless the policy is enabled, because that is what
 * the GPO does: element values are written only in that state. A form that
 * let them be edited otherwise would be showing something that is not there.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api } from '../../../api/endpoints'
import type {
  AdmxControl,
  AdmxElement,
  AdmxPolicySummary,
  Gpo,
  PolicyState,
} from '../../../api/types'
import { ErrorMessage, Modal, Spinner } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import { admlLanguage } from './language'

interface PolicyDialogProps {
  gpo: Gpo
  policy: AdmxPolicySummary
  half: string
  onClose: () => void
  onSaved: (message: string) => void
}

export function PolicyDialog({ gpo, policy, half, onClose, onSaved }: PolicyDialogProps) {
  const { t, language } = useI18n()
  const wanted = admlLanguage(language)

  const [state, setState] = useState<PolicyState>('not_configured')
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [version, setVersion] = useState<number | undefined>(undefined)
  const [error, setError] = useState<unknown>(null)

  const definition = useQuery({
    queryKey: ['admx-policy', policy.id, wanted],
    queryFn: () => api.admxPolicy(policy.id, wanted),
  })

  const current = useQuery({
    queryKey: ['admx-state', gpo.dn, policy.id, half],
    queryFn: () => api.admxState(gpo.dn, policy.id, half),
  })

  // Fill the form once, from what the GPO actually says.
  useEffect(() => {
    if (!current.data) return
    setState(current.data.state)
    setValues(current.data.values ?? {})
    setVersion(current.data.version)
  }, [current.data])

  /**
   * Switching a setting on fills its empty inputs with the defaults the
   * template names, the way GPMC does.
   *
   * Not cosmetic: an author who writes `defaultValue` means *this is the value
   * to use*, and an empty input writes nothing at all. Somebody who does not
   * know what to enter — which is most people, most of the time — otherwise
   * enables a policy whose options stay unset, and the difference is invisible
   * until a client behaves unexpectedly. Values already there are never
   * touched, so this cannot overwrite a deliberate choice.
   */
  const chooseState = (next: PolicyState) => {
    setState(next)
    if (next !== 'enabled' || !definition.data) return

    const defaults = presentationDefaults(definition.data.presentation, definition.data.elements)
    setValues((all) => {
      const filled = { ...all }
      for (const [id, value] of Object.entries(defaults)) {
        if (filled[id] === undefined || filled[id] === '') filled[id] = value
      }
      return filled
    })
  }

  const save = useMutation({
    mutationFn: () =>
      api.applyPolicy(gpo.dn, {
        policy: policy.id,
        half,
        state,
        values,
        expected_version: version,
      }),
    onSuccess: (result) =>
      onSaved(result.changed ? t('admx.saved') : t('admx.unchanged')),
    onError: setError,
  })

  const loading = definition.isLoading || current.isLoading
  const controls = definition.data?.presentation ?? []
  const elements = definition.data?.elements ?? []

  return (
    <Modal
      title={policy.display_name}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={loading || save.isPending}
            onClick={() => save.mutate()}
          >
            {t('action.save')}
          </button>
        </>
      }
    >
      <ErrorMessage error={error ?? definition.error ?? current.error} />
      {loading && <Spinner label={t('status.loading')} />}

      {definition.data && (
        <div className="stack-tight">
          <fieldset className="field">
            <legend className="field__label">{t('admx.state')}</legend>
            {(['not_configured', 'enabled', 'disabled'] as PolicyState[]).map((option) => (
              <label key={option} className="checkbox">
                <input
                  type="radio"
                  name="policy-state"
                  checked={state === option}
                  onChange={() => chooseState(option)}
                />
                <span>{t(`admx.state.${option}` as never)}</span>
              </label>
            ))}
          </fieldset>

          {elements.length > 0 && (
            <fieldset className="field" disabled={state !== 'enabled'}>
              <legend className="field__label">{t('admx.options')}</legend>
              {state !== 'enabled' && (
                <p className="muted small">{t('admx.optionsOnlyWhenEnabled')}</p>
              )}
              <PolicyForm
                controls={controls}
                elements={elements}
                values={values}
                onChange={(id, value) => setValues((all) => ({ ...all, [id]: value }))}
              />
            </fieldset>
          )}

          {definition.data.explain && (
            // Open by default. GPMC keeps the explanation on screen the whole
            // time, and it is the only thing in the dialog that says what the
            // setting actually does.
            <details className="explain" open>
              <summary>{t('admx.explain')}</summary>
              <p>{definition.data.explain}</p>
            </details>
          )}

          <dl className="facts">
            <dt>{t('admx.registryKey')}</dt>
            <dd className="mono small">{definition.data.key}</dd>
            {definition.data.supported_on && (
              <>
                <dt>{t('admx.supportedOn')}</dt>
                <dd className="small">{definition.data.supported_on}</dd>
              </>
            )}
            {/* No row at all when the reference does not resolve. It names a
                namespace generated by the tool that built the template and
                installable nowhere, so neither the identifier nor a note about
                it tells a reader anything they can use. */}
          </dl>
        </div>
      )}
    </Modal>
  )
}

/**
 * The defaults the ADML names, keyed by the element each control belongs to.
 *
 * Which attribute carries the default depends on the control: a number or text
 * box names a value, a check box names `defaultChecked`, a drop-down names the
 * *position* of an item rather than its value. Controls that name none — list
 * and multi-line boxes — simply do not appear here.
 */
function presentationDefaults(
  controls: AdmxControl[],
  elements: AdmxElement[],
): Record<string, unknown> {
  const defaults: Record<string, unknown> = {}

  for (const control of controls) {
    if (!control.ref) continue
    const element = elements.find((item) => item.id === control.ref)
    if (!element) continue

    if (element.kind === 'enum') {
      const item = (element.items ?? [])[control.default_item ?? -1]
      if (item) defaults[element.id] = item.index
    } else if (element.kind === 'boolean') {
      if (typeof control.default === 'boolean') defaults[element.id] = control.default
    } else if (element.kind === 'decimal' || element.kind === 'longDecimal') {
      const number = Number(control.default)
      if (control.default !== undefined && !Number.isNaN(number)) defaults[element.id] = number
    } else if (typeof control.default === 'string' && control.default !== '') {
      defaults[element.id] = control.default
    }
  }

  return defaults
}

// ---------------------------------------------------------------------------

function PolicyForm({
  controls,
  elements,
  values,
  onChange,
}: {
  controls: AdmxControl[]
  elements: AdmxElement[]
  values: Record<string, unknown>
  onChange: (id: string, value: unknown) => void
}) {
  // The presentation decides the order and the labels; anything it does not
  // mention still gets an input, so no element is unreachable.
  const mentioned = new Set(controls.map((control) => control.ref).filter(Boolean))
  const rest = elements.filter((element) => !mentioned.has(element.id))

  return (
    <>
      {controls.map((control, index) => {
        if (!control.ref) {
          return (
            <p key={`text-${index}`} className="muted small">
              {control.text}
            </p>
          )
        }
        const element = elements.find((item) => item.id === control.ref)
        if (!element) return null
        return (
          <ElementInput
            key={element.id}
            element={element}
            label={control.label ?? element.id}
            value={values[element.id]}
            onChange={onChange}
          />
        )
      })}

      {rest.map((element) => (
        <ElementInput
          key={element.id}
          element={element}
          label={element.id}
          value={values[element.id]}
          onChange={onChange}
        />
      ))}
    </>
  )
}

function ElementInput({
  element,
  label,
  value,
  onChange,
}: {
  element: AdmxElement
  label: string
  value: unknown
  onChange: (id: string, value: unknown) => void
}) {
  if (element.kind === 'boolean') {
    return (
      <label className="checkbox">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(element.id, event.target.checked)}
        />
        <span>{label}</span>
      </label>
    )
  }

  if (element.kind === 'enum') {
    return (
      <label className="field">
        <span className="field__label">{label}</span>
        <select
          value={value === undefined ? '' : String(value)}
          onChange={(event) =>
            onChange(element.id, event.target.value === '' ? undefined : Number(event.target.value))
          }
        >
          <option value="" />
          {(element.items ?? []).map((item) => (
            <option key={item.index} value={item.index}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
    )
  }

  if (element.kind === 'decimal' || element.kind === 'longDecimal') {
    // The bounds are in the template and were until now only enforced, never
    // shown — which leaves the reader guessing at exactly the moment they are
    // being asked for a number.
    const bounds =
      element.min !== null && element.min !== undefined && element.max !== null && element.max !== undefined
        ? `${element.min} – ${element.max}`
        : null

    return (
      <label className="field">
        <span className="field__label">{label}</span>
        <input
          type="number"
          min={element.min ?? undefined}
          max={element.max ?? undefined}
          value={value === undefined || value === null ? '' : String(value)}
          onChange={(event) =>
            onChange(element.id, event.target.value === '' ? undefined : Number(event.target.value))
          }
        />
        {bounds && <span className="field__hint">{bounds}</span>}
      </label>
    )
  }

  if (element.kind === 'multiText' || element.kind === 'list') {
    // Both are several values; one per line is the shape people already know
    // from every other tool that edits them.
    const text = Array.isArray(value) ? value.join('\n') : String(value ?? '')
    return (
      <label className="field">
        <span className="field__label">{label}</span>
        <textarea
          rows={4}
          value={text}
          onChange={(event) =>
            onChange(
              element.id,
              event.target.value.split('\n').filter((line) => line.trim() !== ''),
            )
          }
        />
      </label>
    )
  }

  return (
    <label className="field">
      <span className="field__label">{label}</span>
      <input
        maxLength={element.max_length ?? undefined}
        value={value === undefined || value === null ? '' : String(value)}
        onChange={(event) =>
          onChange(element.id, event.target.value === '' ? undefined : event.target.value)
        }
      />
    </label>
  )
}
