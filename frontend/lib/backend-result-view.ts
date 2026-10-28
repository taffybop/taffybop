/** Optional display helpers. The response bytes remain the authoritative export. */
export function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

export function fieldText(value: unknown): string {
  if (value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

export interface PreviewCell {
  text: string;
  row: number;
  column: number;
  rowSpan: number;
  colSpan: number;
  header: boolean;
}

export interface PreviewTable {
  rows: PreviewCell[][];
  columns: number;
  representation: "cells" | "rows";
  note: string | null;
}

function rowTable(item: Record<string, unknown>, note: string | null): PreviewTable | null {
  const values = Array.isArray(item.rows) ? item.rows : Array.isArray(item.value) ? item.value : null;
  if (!values?.length || values.length > 4096 || values.some(row => !Array.isArray(row) || row.length > 256)) return null;
  const rows = values as unknown[][];
  return {
    rows: rows.map((row, rowIndex) => row.map((value, column) => ({ text: fieldText(value), row: rowIndex, column, rowSpan: 1, colSpan: 1, header: false }))),
    columns: Math.max(...rows.map(row => row.length)),
    representation: "rows",
    note,
  };
}

/** Use explicit spans only when the API's cell coordinates form a complete grid. */
export function previewTable(value: unknown): PreviewTable | null {
  const item = record(value);
  if (!item) return null;
  if (!Array.isArray(item.cells) || !item.cells.length) return rowTable(item, null);
  const invalid = () => rowTable(item, "Cell coordinates could not be displayed safely. Showing the API rows; all cell metadata is retained in Raw API JSON.");
  if (item.cells.length > 65_536) return invalid();
  const cells: PreviewCell[] = [];
  let rowCount = 0;
  let columns = 0;
  for (const raw of item.cells) {
    const cell = record(raw);
    if (!cell) return invalid();
    const row = cell.row;
    const column = cell.column;
    const rowSpan = cell.row_span ?? 1;
    const colSpan = cell.col_span ?? 1;
    if (![row, column, rowSpan, colSpan].every(Number.isInteger)
      || (row as number) < 0 || (column as number) < 0 || (rowSpan as number) < 1 || (colSpan as number) < 1
      || (row as number) + (rowSpan as number) > 4096 || (column as number) + (colSpan as number) > 256) return invalid();
    cells.push({ row: row as number, column: column as number, rowSpan: rowSpan as number, colSpan: colSpan as number, text: fieldText(cell.text ?? cell.value ?? ""), header: cell.column_header === true || cell.row_header === true });
    rowCount = Math.max(rowCount, (row as number) + (rowSpan as number));
    columns = Math.max(columns, (column as number) + (colSpan as number));
  }
  if (item.row_count !== undefined && item.row_count !== rowCount || item.column_count !== undefined && item.column_count !== columns) return invalid();
  if (rowCount * columns > 65_536) return invalid();
  const occupied = new Set<number>();
  const rows: PreviewCell[][] = Array.from({ length: rowCount }, () => []);
  for (const cell of cells) {
    for (let row = cell.row; row < cell.row + cell.rowSpan; row += 1) {
      for (let column = cell.column; column < cell.column + cell.colSpan; column += 1) {
        const coordinate = row * columns + column;
        if (occupied.has(coordinate)) return invalid();
        occupied.add(coordinate);
      }
    }
    rows[cell.row].push(cell);
  }
  if (occupied.size !== rowCount * columns) return invalid();
  rows.forEach(row => row.sort((a, b) => a.column - b.column));
  return { rows, columns, representation: "cells", note: null };
}

/** Never fetch a URL supplied by a parsed document or render its HTML/SVG. */
export function inlineApiImage(value: unknown): string | null {
  const item = record(value);
  if (!item) return null;
  const chart = record(item.chart_resolution);
  const candidates = [record(chart?.asset)?.data_uri, record(item.asset)?.data_uri, item.data_uri];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.length <= 12_000_000
      && /^data:image\/(?:png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$/u.test(candidate)) return candidate;
  }
  return null;
}

export function responseWarnings(value: unknown): string[] {
  const result = record(value);
  if (!result) return [];
  const warnings = Array.isArray(result.warnings) ? result.warnings.map(fieldText) : [];
  if (Array.isArray(result.pages)) result.pages.forEach((raw, index) => {
    const page = record(raw);
    if (!page) return;
    if (page.success === false) warnings.push(`Page ${fieldText(page.page_index ?? index + 1)}: API reported unsuccessful processing.`);
    if (Array.isArray(page.warnings)) page.warnings.forEach(warning => warnings.push(`Page ${fieldText(page.page_index ?? index + 1)}: ${fieldText(warning)}`));
    for (const collection of ["items", "detected_images"]) {
      const items = page[collection];
      if (!Array.isArray(items)) continue;
      items.forEach((rawItem, itemIndex) => {
        const item = record(rawItem);
        if (!item || !Array.isArray(item.parse_concerns)) return;
        const identity = item.id !== undefined ? fieldText(item.id) : `${collection}[${itemIndex}]`;
        item.parse_concerns.forEach(concern => warnings.push(`Page ${fieldText(page.page_index ?? index + 1)} · ${identity}: ${fieldText(concern)}`));
      });
    }
  });
  return warnings;
}
