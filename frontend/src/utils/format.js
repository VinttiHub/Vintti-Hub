export function formatCurrency(value) {
  if (value == null || value === '') return '—';
  const number = Number(value);
  if (Number.isNaN(number)) return value;
  return `$${number.toLocaleString()}`;
}
