/**
 * How a preference field's choices are labelled and listed.
 *
 * Hives and registry types are spelled as the registry spells them, a drive
 * letter with its colon as GPMC shows it, everything else gets a word. A
 * value from the file that is not in the list is offered as well: a select
 * that cannot show the current value would quietly replace it on the next
 * save.
 */

export function choiceLabel(field: string, choice: string, t: (key: string) => string): string {
  if (field === 'letter') return choice ? `${choice}:` : t('pref.letter.choose')
  if (choice.startsWith('HKEY_') || choice.startsWith('REG_')) return choice
  return t(`pref.choice.${choice}`)
}

export function choicesWithCurrent(choices: readonly string[], value: string): string[] {
  return choices.includes(value) ? [...choices] : [...choices, value]
}
