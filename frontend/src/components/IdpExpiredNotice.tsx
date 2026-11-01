/**
 * The identity provider in front has let its session go.
 *
 * Every call the console makes then meets the proxy instead of SAMADCON, and
 * each would fail on its own with a message about itself. The client tells
 * this component once per such call (api/client.ts, onIdpSessionExpired), and
 * it asks once: reload, which takes the browser through the identity
 * provider's sign-in and back — SAMADCON's own session is still there — or
 * later, for someone who wants to copy something off the screen first. Later
 * holds until the next call meets the proxy again.
 */

import { useEffect, useState } from 'react'

import { onIdpSessionExpired } from '../api/client'
import { useI18n } from '../i18n'
import { Modal } from './primitives'

export function IdpExpiredNotice() {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)

  useEffect(() => onIdpSessionExpired(() => setOpen(true)), [])

  if (!open) return null
  return (
    <Modal
      title={t('idp.expiredTitle')}
      onClose={() => setOpen(false)}
      footer={
        <>
          <button type="button" className="button" onClick={() => setOpen(false)}>
            {t('idp.later')}
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={() => window.location.reload()}
          >
            {t('idp.reload')}
          </button>
        </>
      }
    >
      <p>{t('idp.expiredBody')}</p>
    </Modal>
  )
}
