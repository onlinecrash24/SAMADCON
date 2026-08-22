/**
 * The consoles, as a strip across the top.
 *
 * They were roots of the navigation tree until now. A tester asked for the
 * opposite, and the reason holds up: in RSAT each console is a separate
 * program with its own window and its own tree. Stacking six of them as
 * siblings above a directory hierarchy is MMC's arrangement, not the one
 * anybody arrives already knowing — and it left the tree mixing two kinds of
 * thing, consoles and organisational units, in one column.
 *
 * A plain nav of buttons, deliberately not role="tablist". A tablist promises
 * an adjacent tabpanel and roving tabindex, and roving tabindex would make
 * five of the six consoles unreachable by Tab. What these do is switch the
 * whole application view — three panes and a remembered position. That is
 * navigation. Arrow keys can be added later without changing the role; taking
 * a role back is the move that breaks assistive software.
 */

import { SNAPINS, type SnapinId } from './snapins'
import { Icon } from '../../components/primitives'
import { useI18n } from '../../i18n'

export function ConsoleTabs({
  active,
  onSelect,
  windowCounts,
}: {
  active: SnapinId
  onSelect: (id: SnapinId) => void
  /** How many windows each console is holding out of sight. */
  windowCounts?: Partial<Record<SnapinId, number>>
}) {
  const { t } = useI18n()

  return (
    <nav className="console__tabs" aria-label={t('nav.consoles')}>
      {SNAPINS.map((snapin) => {
        const label = t(snapin.label)
        return (
          <button
            key={snapin.id}
            type="button"
            className={
              active === snapin.id ? 'console__tab console__tab--active' : 'console__tab'
            }
            // aria-current, not aria-selected: this is a set of destinations,
            // and only a tab in a tablist may claim to be selected.
            aria-current={active === snapin.id ? 'page' : undefined}
            disabled={!snapin.available}
            onClick={() => onSelect(snapin.id)}
            // Carries the name when the label is dropped on a narrow window.
            title={label}
          >
            <Icon type={snapin.icon} />
            <span className="console__tab-label">{label}</span>
            {/* Windows of an inactive console are hidden, not closed. Without
                saying how many, the two are indistinguishable and somebody
                concludes their half-typed sheet was thrown away. */}
            {(windowCounts?.[snapin.id] ?? 0) > 0 && (
              <span className="console__tab-count">({windowCounts?.[snapin.id]})</span>
            )}
          </button>
        )
      })}
    </nav>
  )
}
