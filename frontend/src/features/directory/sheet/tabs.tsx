/**
 * The tabs that are only fields, laid out the way ADUC lays them out.
 *
 * Each is a function of the draft and nothing else. A tester who used the
 * console in production asked for exactly this: the property sheet
 * "functionally modelled on the original", because an administrator who has
 * opened ADUC ten thousand times knows where the department field is without
 * looking. The pattern is not decoration — it is what makes the tool usable
 * by the people it is for.
 */

import type { GroupDetail, UserDetail } from '../../../api/types'
import { Field, TextRow } from '../../../components/primitives'
import { nameFromDn } from '../../../dn'
import { useI18n } from '../../../i18n'
import { FIELDS } from '../fieldDefs'
import { FieldInput, FieldRow } from './FieldInput'
import { useSheet } from './SheetContext'

// ---------------------------------------------------------------------------
// General
// ---------------------------------------------------------------------------

export function UserGeneralTab() {
  return (
    <>
      <FieldRow fields={[FIELDS.first_name, FIELDS.initials]} />
      <FieldInput field={FIELDS.last_name} />
      <FieldInput field={FIELDS.display_name} />
      <FieldInput field={FIELDS.description} />
      <FieldInput field={FIELDS.office} />
      <FieldInput field={FIELDS.telephone} />
      <FieldInput field={FIELDS.mail} />
      <FieldInput field={FIELDS.web_page} />
    </>
  )
}

/**
 * A group's General tab: description and mail, then scope and type as the
 * two radio groups ADUC draws. Scope and type are not attributes; they go to
 * the draft's own fields and the group endpoint's own parameters.
 */
export function GroupGeneralTab({ group }: { group: GroupDetail }) {
  const { t } = useI18n()
  const { draft, setDraft, busy } = useSheet()
  const scope = draft.scope ?? group.scope ?? ''
  const security = draft.securityGroup ?? group.security_group

  return (
    <>
      <TextRow label={t('group.samName')} value={group.sam_account_name} />
      <FieldInput field={FIELDS.description} />
      <FieldInput field={FIELDS.mail} />

      <div className="field-row">
        <fieldset className="radio-group">
          <legend>{t('group.scope')}</legend>
          {(['domain_local', 'global', 'universal'] as const).map((value) => (
            <label className="checkbox" key={value}>
              <input
                type="radio"
                name="group-scope"
                value={value}
                checked={scope === value}
                disabled={busy}
                onChange={() => setDraft((d) => ({ ...d, scope: value }))}
              />
              <span>{t(`group.scope.${value}`)}</span>
            </label>
          ))}
        </fieldset>
        <fieldset className="radio-group">
          <legend>{t('group.type')}</legend>
          <label className="checkbox">
            <input
              type="radio"
              name="group-type"
              checked={security}
              disabled={busy}
              onChange={() => setDraft((d) => ({ ...d, securityGroup: true }))}
            />
            <span>{t('group.security')}</span>
          </label>
          <label className="checkbox">
            <input
              type="radio"
              name="group-type"
              checked={!security}
              disabled={busy}
              onChange={() => setDraft((d) => ({ ...d, securityGroup: false }))}
            />
            <span>{t('group.distribution')}</span>
          </label>
        </fieldset>
      </div>

      <FieldInput field={FIELDS.notes} />
    </>
  )
}

export function ComputerGeneralTab({ samName }: { samName: string }) {
  const { t } = useI18n()
  return (
    <>
      <TextRow label={t('computer.samName')} value={samName} />
      <FieldInput field={FIELDS.dns_host_name} />
      <FieldInput field={FIELDS.description} />
      <FieldInput field={FIELDS.location} />
    </>
  )
}

export function OuGeneralTab() {
  return (
    <>
      <FieldInput field={FIELDS.description} />
      <FieldInput field={FIELDS.street} />
      <FieldRow fields={[FIELDS.city, FIELDS.state]} />
      <FieldRow fields={[FIELDS.postal_code, FIELDS.country]} />
    </>
  )
}

// ---------------------------------------------------------------------------
// Address, Telephones, Organization
// ---------------------------------------------------------------------------

export function AddressTab() {
  return (
    <>
      <FieldInput field={FIELDS.street} />
      <FieldInput field={FIELDS.post_office_box} />
      <FieldRow fields={[FIELDS.city, FIELDS.state]} />
      <FieldRow fields={[FIELDS.postal_code, FIELDS.country]} />
    </>
  )
}

export function TelephonesTab() {
  return (
    <>
      <FieldRow fields={[FIELDS.home_phone, FIELDS.pager]} />
      <FieldRow fields={[FIELDS.mobile, FIELDS.fax]} />
      <FieldInput field={FIELDS.ip_phone} />
      <FieldInput field={FIELDS.notes} />
    </>
  )
}

/** Title, department, company, the manager — and who reports to this person. */
export function OrganizationTab({ user }: { user?: UserDetail }) {
  const { t } = useI18n()
  return (
    <>
      <FieldInput field={FIELDS.title} />
      <FieldRow fields={[FIELDS.department, FIELDS.company]} />
      <FieldInput field={FIELDS.manager} />
      {user && (
        <Field label={t('user.directReports')}>
          {user.direct_reports.length === 0 ? (
            <p className="muted small">{t('user.noDirectReports')}</p>
          ) : (
            <ul className="plain-list boxed-list">
              {user.direct_reports.map((dn) => (
                <li key={dn} title={dn}>
                  {nameFromDn(dn)}
                </li>
              ))}
            </ul>
          )}
        </Field>
      )}
    </>
  )
}

/** For groups, computers and OUs: who is responsible. */
export function ManagedByTab() {
  return <FieldInput field={FIELDS.managed_by} />
}

// ---------------------------------------------------------------------------
// Profile
// ---------------------------------------------------------------------------

/**
 * Profile path, logon script, and the home folder the way ADUC asks for it:
 * either a local path, or a drive letter connected to a share. Both are the
 * same two attributes underneath — homeDirectory, and homeDrive set or not —
 * which is why the radio buttons change nothing but which inputs are shown.
 */
export function ProfileTab() {
  const { t } = useI18n()
  const { get, set, busy } = useSheet()
  const drive = get('home_drive')
  const connect = drive !== ''
  const letters = Array.from({ length: 26 }, (_, i) => `${String.fromCharCode(65 + i)}:`)

  return (
    <>
      <fieldset className="radio-group radio-group--block">
        <legend>{t('user.profile')}</legend>
        <FieldInput field={FIELDS.profile_path} />
        <FieldInput field={FIELDS.logon_script} />
      </fieldset>

      <fieldset className="radio-group radio-group--block">
        <legend>{t('user.homeFolder')}</legend>
        <label className="checkbox">
          <input
            type="radio"
            name="home-mode"
            checked={!connect}
            disabled={busy}
            onChange={() => set('home_drive', '')}
          />
          <span>{t('user.homeLocal')}</span>
        </label>
        {!connect && (
          <input
            type="text"
            value={get('home_directory')}
            disabled={busy}
            onChange={(event) => set('home_directory', event.target.value)}
          />
        )}
        <label className="checkbox">
          <input
            type="radio"
            name="home-mode"
            checked={connect}
            disabled={busy}
            onChange={() => set('home_drive', drive || 'H:')}
          />
          <span>{t('user.homeConnect')}</span>
        </label>
        {connect && (
          <div className="field-inline">
            <select
              value={drive}
              disabled={busy}
              onChange={(event) => set('home_drive', event.target.value)}
              style={{ width: 'auto' }}
            >
              {letters.map((letter) => (
                <option key={letter} value={letter}>
                  {letter}
                </option>
              ))}
            </select>
            <span className="muted">{t('user.homeTo')}</span>
            <input
              type="text"
              placeholder="\\\\server\\share\\%username%"
              value={get('home_directory')}
              disabled={busy}
              onChange={(event) => set('home_directory', event.target.value)}
            />
          </div>
        )}
      </fieldset>
    </>
  )
}
