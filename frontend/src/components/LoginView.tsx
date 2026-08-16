import { useEffect, useMemo, useState, type FormEvent } from 'react'

import { api } from '../api/endpoints'
import type { ProbeResult, ServerInfo, ServerListing } from '../api/types'
import { useI18n } from '../i18n'
import { loadRecentServers, type RecentServer } from '../state/recentServers'
import { useSession } from '../state/session'
import { LogoLockup } from './Logo'
import { Badge, Banner, ErrorMessage, Field, Spinner } from './primitives'

/** Value of the domain selector. Anything else is a profile id. */
const CUSTOM = '__custom__'
const DEFAULT = '__default__'

export function LoginView() {
  const { t, language, setLanguage } = useI18n()
  const { login } = useSession()

  const [info, setInfo] = useState<ServerInfo | null>(null)
  const [servers, setServers] = useState<ServerListing | null>(null)
  const [recents, setRecents] = useState<RecentServer[]>([])

  const [choice, setChoice] = useState<string>(DEFAULT)
  const [host, setHost] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [insecure, setInsecure] = useState(false)

  const [probe, setProbe] = useState<ProbeResult | null>(null)
  const [probing, setProbing] = useState(false)
  const [probeError, setProbeError] = useState<unknown>(null)
  const [error, setError] = useState<unknown>(null)
  const [pending, setPending] = useState(false)

  useEffect(() => {
    api.info().then(setInfo).catch(() => setInfo(null))
    api
      .servers()
      .then((listing) => {
        setServers(listing)
        // Land on something usable: the configured default if there is one,
        // otherwise the first profile, otherwise free entry.
        if (listing.default) setChoice(DEFAULT)
        else if (listing.profiles.length > 0) setChoice(listing.profiles[0]!.id)
        else setChoice(CUSTOM)
      })
      .catch(() => setServers(null))
    setRecents(loadRecentServers())
  }, [])

  const isCustom = choice === CUSTOM
  const profile = useMemo(
    () => servers?.profiles.find((item) => item.id === choice) ?? null,
    [servers, choice],
  )

  // The realm we expect to authenticate against, for the hint under the form.
  const expectedRealm =
    probe?.realm ?? profile?.realm ?? (choice === DEFAULT ? servers?.default?.realm : null) ?? null

  async function runProbe(address: string) {
    const trimmed = address.trim()
    if (!trimmed) return
    setProbing(true)
    setProbeError(null)
    try {
      const result = await api.probeServer(trimmed, { insecure })
      setProbe(result)
      // A certificate that does not validate is the single most common reason
      // a sign-in against a test domain fails; offer the way out immediately.
      if (result.requires_insecure) setInsecure(true)
    } catch (cause) {
      setProbe(null)
      setProbeError(cause)
    } finally {
      setProbing(false)
    }
  }

  function selectServer(value: string) {
    setChoice(value)
    setProbe(null)
    setProbeError(null)

    const recent = recents.find((item) => item.host === value)
    if (recent) {
      // Recent entries are addresses, not profiles.
      setChoice(CUSTOM)
      setHost(recent.host)
      setInsecure(recent.insecure)
      void runProbe(recent.host)
      return
    }

    const chosen = servers?.profiles.find((item) => item.id === value)
    setInsecure(chosen?.insecure ?? false)
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setPending(true)
    try {
      await login(username, password, {
        server: isCustom ? host.trim() : undefined,
        profileId: profile?.id,
        insecure,
      })
    } catch (cause) {
      setError(cause)
      // Cleared on failure so a shoulder-surfer does not get a second look at
      // a typo'd credential.
      setPassword('')
    } finally {
      setPending(false)
    }
  }

  const needsServer = isCustom && !host.trim()
  const showSelector = Boolean(
    servers && (servers.profiles.length > 0 || servers.default || recents.length > 0),
  )

  return (
    <div className="login">
      <form className="login__card" onSubmit={onSubmit}>
        <header className="login__brand">
          <LogoLockup />
          <h1 className="visually-hidden">
            {t('app.title')} — {t('app.subtitle')}
          </h1>
        </header>

        {info?.ldap_insecure && <Banner tone="warning" message={t('login.insecureWarning')} />}

        <h2 className="login__heading">{t('login.heading')}</h2>

        <ErrorMessage error={error} onDismiss={() => setError(null)} />

        {showSelector && (
          <Field label={t('login.domain')}>
            <select value={choice} onChange={(event) => selectServer(event.target.value)}>
              {servers?.default && (
                <option value={DEFAULT}>
                  {servers.default.realm} ({t('login.configured')})
                </option>
              )}
              {servers?.profiles.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
              {recents.length > 0 && (
                <optgroup label={t('login.recent')}>
                  {recents.map((item) => (
                    <option key={item.host} value={item.host}>
                      {item.host} ({item.realm})
                    </option>
                  ))}
                </optgroup>
              )}
              {servers?.allow_custom_servers !== false && (
                <option value={CUSTOM}>{t('login.otherServer')}</option>
              )}
            </select>
          </Field>
        )}

        {isCustom && (
          <Field label={t('login.server')} hint={t('login.serverHint')}>
            <div className="login__server">
              <input
                type="text"
                name="server"
                autoComplete="off"
                spellCheck={false}
                value={host}
                placeholder="192.168.1.10"
                onChange={(event) => {
                  setHost(event.target.value)
                  setProbe(null)
                  setProbeError(null)
                }}
                onBlur={(event) => void runProbe(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    // Check the address instead of submitting a half-filled form.
                    event.preventDefault()
                    void runProbe(host)
                  }
                }}
              />
              <button
                type="button"
                className="button"
                onClick={() => void runProbe(host)}
                disabled={probing || !host.trim()}
              >
                {t('login.check')}
              </button>
            </div>
          </Field>
        )}

        {probing && <Spinner label={t('login.probing')} />}
        <ErrorMessage error={probeError} onDismiss={() => setProbeError(null)} />

        {probe && (
          <div className="login__probe">
            <div className="row">
              <span className="row__label">{t('login.detectedDomain')}</span>
              <span className="row__value">
                <strong>{probe.dns_domain}</strong> <span className="muted">({probe.realm})</span>
              </span>
            </div>
            {probe.dc_hostname && (
              <div className="row">
                <span className="row__label">{t('login.detectedDc')}</span>
                <span className="row__value mono">{probe.dc_hostname}</span>
              </div>
            )}
            <div className="row">
              <span className="row__label">LDAPS</span>
              <span className="row__value">
                {!probe.ldaps_reachable ? (
                  <Badge tone="danger">{t('login.ldapsUnreachable')}</Badge>
                ) : probe.ldaps_certificate_trusted ? (
                  <Badge tone="ok">{t('login.certificateTrusted')}</Badge>
                ) : (
                  <Badge tone="warn">{t('login.certificateUntrusted')}</Badge>
                )}
              </span>
            </div>
            {probe.dc_hostname && probe.dc_hostname_resolves === false && (
              <div className="row">
                <span className="row__label">DNS</span>
                <span className="row__value">
                  <Badge tone="danger">{t('login.hostnameUnresolved')}</Badge>
                </span>
              </div>
            )}
            {!probe.is_domain_controller && (
              <Banner tone="warning" message={t('login.notADomainController')} />
            )}
          </div>
        )}

        {probe?.dc_hostname && probe.dc_hostname_resolves === false && (
          <Banner
            tone="warning"
            message={t('login.hostnameUnresolvedHint', { host: probe.dc_hostname })}
          />
        )}

        {probe?.requires_insecure && (
          <Banner tone="warning" message={t('login.certificateHint')} />
        )}

        <Field label={t('login.username')}>
          <input
            type="text"
            name="username"
            autoComplete="username"
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder={expectedRealm ? `Administrator@${expectedRealm}` : 'user@REALM'}
          />
        </Field>

        <Field label={t('login.password')}>
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>

        <label className="checkbox">
          <input
            type="checkbox"
            checked={insecure}
            onChange={(event) => setInsecure(event.target.checked)}
          />
          <span>{t('login.skipCertificateCheck')}</span>
        </label>
        {insecure && <p className="login__insecure">{t('login.skipCertificateWarning')}</p>}

        <button type="submit" className="button button--primary" disabled={pending || needsServer}>
          {pending ? t('login.pending') : t('login.submit')}
        </button>

        {expectedRealm && (
          <p className="login__realm">{t('login.realmHint', { realm: expectedRealm })}</p>
        )}

        <div className="login__footer">
          <button
            type="button"
            className="link"
            onClick={() => setLanguage(language === 'de' ? 'en' : 'de')}
          >
            {language === 'de' ? 'English' : 'Deutsch'}
          </button>
          {info && <span className="login__version">v{info.version}</span>}
        </div>
      </form>
    </div>
  )
}
