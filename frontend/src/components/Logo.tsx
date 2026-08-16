/**
 * Brand assets.
 *
 * Light and dark variants are switched with <picture>/<source media>, so the
 * browser picks one before layout instead of rendering both and hiding one.
 * The app follows the system theme, which is exactly what that media query
 * reports.
 */

import lockupDark from '../assets/samadcon-lockup-dark.svg'
import lockupLight from '../assets/samadcon-lockup-light.svg'
import markDark from '../assets/samadcon-mark-dark.svg'
import markLight from '../assets/samadcon-mark-light.svg'

const ALT = 'SAMADCON — Samba AD Console'

/** Full lockup: mark plus wordmark. For the sign-in card. */
export function LogoLockup({ className }: { className?: string }) {
  return (
    <picture>
      <source srcSet={lockupDark} media="(prefers-color-scheme: dark)" />
      <img
        src={lockupLight}
        alt={ALT}
        className={className ? `logo-lockup ${className}` : 'logo-lockup'}
        width={520}
        height={132}
      />
    </picture>
  )
}

/** Mark only. For the top bar, where the product name is already text. */
export function LogoMark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <picture>
      <source srcSet={markDark} media="(prefers-color-scheme: dark)" />
      <img
        src={markLight}
        // Decorative here: the adjacent text already names the product.
        alt=""
        aria-hidden="true"
        className={className ? `logo-mark ${className}` : 'logo-mark'}
        width={size}
        height={size}
      />
    </picture>
  )
}
