import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import { composeUpn, splitUpn, upnOptions } from './upn'

/**
 * A user principal name as two parts: the name, and a suffix chosen from
 * what the forest actually offers.
 *
 * ADUC draws it this way beside the logon name, and a tester with several
 * suffixes asked for the same. The list comes from the directory — the
 * domain, the forest's other domains, and whatever was added under Domains
 * and Trusts — so a suffix is offered because it exists, not because someone
 * remembered it. A value already carrying a suffix outside that list keeps it:
 * it is shown as one more option rather than silently replaced.
 *
 * The value is one string, "name@suffix", so callers store it exactly as the
 * attribute is written. Emptying the name empties the value, which the
 * property sheet reads as "remove the attribute".
 */
export function UpnField({
  value,
  onChange,
  disabled,
  required,
  maxLength,
}: {
  value: string
  onChange: (next: string) => void
  disabled?: boolean
  /** Both apply to the name half only; the suffix is chosen, not typed. */
  required?: boolean
  maxLength?: number
}) {
  const suffixes = useQuery({ queryKey: ['upn-suffixes'], queryFn: () => api.upnSuffixes() })
  const offered = suffixes.data?.suffixes ?? []

  const { local, suffix } = splitUpn(value)
  const options = upnOptions(offered, suffix)
  const chosen = suffix || options[0] || ''

  const compose = (nextLocal: string, nextSuffix: string) =>
    onChange(composeUpn(nextLocal, nextSuffix))

  return (
    <div className="upn">
      <input
        type="text"
        autoComplete="off"
        spellCheck={false}
        value={local}
        disabled={disabled}
        required={required}
        maxLength={maxLength}
        onChange={(event) => compose(event.target.value, chosen)}
      />
      <span className="upn__at" aria-hidden="true">
        @
      </span>
      <select
        value={chosen}
        disabled={disabled || options.length === 0}
        onChange={(event) => compose(local, event.target.value)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </div>
  )
}
