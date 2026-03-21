/**
 * Money utilities.
 *
 * The API returns all monetary values as decimal strings (e.g. "100.00").
 * parseFloat is used ONLY for display via Intl.NumberFormat — never for
 * arithmetic or storage.
 */

/** Format a decimal string as a currency amount for display. */
export function formatMoney(
  amount: string | null | undefined,
  currency = 'ZAR',
): string {
  if (amount == null) return '—'
  const num = parseFloat(amount)
  if (isNaN(num)) return amount
  return new Intl.NumberFormat('en-ZA', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num)
}

/** Format a decimal string as a plain number with 2dp (no currency symbol). */
export function formatAmount(amount: string | null | undefined): string {
  if (amount == null) return '—'
  const num = parseFloat(amount)
  if (isNaN(num)) return amount
  return num.toFixed(2)
}
