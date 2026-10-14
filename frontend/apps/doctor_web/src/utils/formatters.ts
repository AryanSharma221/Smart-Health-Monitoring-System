import type { MetricUnit } from '../types';

/**
 * Formats a vital reading value with its unit.
 * CRITICAL RULE: If the value is null or undefined (missing), returns "—" (unavailable).
 * NEVER converts null to 0 or an invented default.
 */
export function formatVitalValue(
  value: number | null | undefined,
  unit?: MetricUnit,
  precision: number = 1
): string {
  if (value === null || value === undefined || isNaN(value)) {
    return '—';
  }

  const formattedNum = Number.isInteger(value)
    ? value.toString()
    : value.toFixed(precision);

  return unit ? `${formattedNum} ${unit}` : formattedNum;
}

/**
 * Formats timestamp for clinical log view.
 */
export function formatTimestamp(isoString: string | null | undefined): string {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString; // fallback to raw string if non-ISO (e.g. Kaggle string)
    return d.toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return isoString;
  }
}
