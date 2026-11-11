// SPDX-License-Identifier: AGPL-3.0-only
export function businessCode(prefix: string, sequence: number | string, requirementNumbers: Record<string, number>) {
  const number = requirementNumbers[String(sequence)];
  return number ? `${prefix}-R-${number}` : `${prefix}-T-${sequence}`;
}
