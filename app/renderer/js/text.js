// Plain fixed-width text tables, for the black-and-white UI. A port of ui/text.py.

export function fmt(value, kind = '') {
  if (value == null || Number.isNaN(value)) return '-';
  if (kind === 'pct') return `${Math.round(value)}%`;
  if (kind === 'signed') return `${value >= 0 ? '+' : ''}${Math.round(value)}`;
  if (typeof value === 'number' && !Number.isInteger(value)) return value.toFixed(1);
  return String(value);
}

// rows: [{...}], index: [[key, header]] (left-aligned), columns: [[key, header, kind]] (right-aligned).
//   color  games  score
//   -----  -----  -----
//   white     42    55%
export function table(rows, index, columns) {
  if (!rows.length) return 'No games.';
  const header = [...index.map(i => i[1]), ...columns.map(c => c[1])];
  const body = rows.map(r => [...index.map(([k]) => String(r[k] ?? '')), ...columns.map(([k, , kind]) => fmt(r[k], kind))]);
  const widths = header.map((h, i) => Math.max(h.length, ...body.map(b => b[i].length)));
  const line = cells => cells.map((c, i) => (i < index.length ? c.padEnd(widths[i]) : c.padStart(widths[i]))).join('  ').trimEnd();
  return [line(header), line(widths.map(w => '-'.repeat(w))), ...body.map(line)].join('\n');
}
