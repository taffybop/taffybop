interface JsonRecord {
  bbox?: unknown;
  bold?: unknown;
  candidate_id?: unknown;
  cell_id?: unknown;
  cell_ids?: unknown;
  cells?: unknown;
  cells_sha256?: unknown;
  claimed_col_span?: unknown;
  claimed_row_span?: unknown;
  col_span?: unknown;
  column?: unknown;
  column_count?: unknown;
  column_header?: unknown;
  concern_codes?: unknown;
  concerns?: unknown;
  confidence?: unknown;
  confidence_dimensions?: unknown;
  content_sha256?: unknown;
  continuation?: unknown;
  covered_by_cell_id?: unknown;
  csv?: unknown;
  csv_sha256?: unknown;
  dimension?: unknown;
  emitted_col_span?: unknown;
  emitted_row_span?: unknown;
  engine?: unknown;
  evidence?: unknown;
  evidence_ids?: unknown;
  font_name?: unknown;
  gate?: unknown;
  geometry?: unknown;
  grid?: unknown;
  grid_shape?: unknown;
  header?: unknown;
  height?: unknown;
  html?: unknown;
  html_sha256?: unknown;
  id?: unknown;
  kind?: unknown;
  markdown_sha256?: unknown;
  md?: unknown;
  method?: unknown;
  object_type?: unknown;
  outcome?: unknown;
  page_index?: unknown;
  policy_id?: unknown;
  raw_ref?: unknown;
  reconciliation?: unknown;
  representation_custody?: unknown;
  row?: unknown;
  row_count?: unknown;
  row_header?: unknown;
  row_section?: unknown;
  row_span?: unknown;
  role?: unknown;
  rows?: unknown;
  rows_sha256?: unknown;
  scope?: unknown;
  serializer_policy_id?: unknown;
  slots?: unknown;
  source?: unknown;
  source_object_ids?: unknown;
  source_objects?: unknown;
  span_decision_id?: unknown;
  span_decisions?: unknown;
  status?: unknown;
  structure?: unknown;
  table_evidence?: unknown;
  table_id?: unknown;
  target_column?: unknown;
  target_row?: unknown;
  text?: unknown;
  type?: unknown;
  unit?: unknown;
  value?: unknown;
  version?: unknown;
  width?: unknown;
  words?: unknown;
  x?: unknown;
  y?: unknown;
}

interface ValidatedTableBBox {
  x: number;
  y: number;
  width: number;
  height: number;
  unit: "pt";
}

interface ValidatedConfidenceDimensions {
  text: number | null;
  geometry: number | null;
  structure: number | null;
  header: number | null;
}

interface ValidatedTableCell {
  id: string;
  row: number;
  column: number;
  rowSpan: number;
  colSpan: number;
  text: string;
  columnHeader: boolean;
  rowHeader: boolean;
  rowSection: boolean;
  bbox: ValidatedTableBBox | null;
  source: "native" | "ocr";
  pageIndex: number;
  evidenceIds: string[];
  sourceObjectIds: string[];
  spanDecisionId: string | null;
  confidenceDimensions: ValidatedConfidenceDimensions;
  sourceCellIndex: number;
}

interface ValidatedTableSlot {
  id: string;
  row: number;
  column: number;
  kind: "anchor" | "explicit_blank" | "covered";
  cellId: string | null;
  coveredByCellId: string | null;
}

interface ValidatedTableRow {
  row: number;
  cells: ValidatedTableCell[];
  columnHeaderRow: boolean;
}

interface ValidatedDoclingSourceObject {
  id: string;
  engine: "docling";
  objectType: "table_cell" | "table_geometry" | "table_grid";
  pageIndex: number;
  rawRef: string;
  contentSha256: string;
}

interface ValidatedTableWord {
  id: string;
  text: string;
  bbox: ValidatedTableBBox;
  fontName: string;
  bold: boolean;
}

interface ValidatedPdfplumberWordSetSourceObject {
  id: string;
  engine: "pdfplumber";
  objectType: "table_word_set";
  pageIndex: number;
  rawRef: null;
  role: "header" | "body_control" | "bottom_row";
  targetRow: number;
  targetColumn: number;
  words: ValidatedTableWord[];
  contentSha256: string;
}

type ValidatedSourceObject =
  | ValidatedDoclingSourceObject
  | ValidatedPdfplumberWordSetSourceObject;

interface ValidatedEvidence {
  id: string;
  method: string;
  dimension: string;
  pageIndex: number;
  bbox: ValidatedTableBBox | null;
  sourceObjectIds: string[];
  confidence: number;
  contentSha256: string;
}

interface ValidatedSpanDecision {
  id: string;
  cellId: string;
  claimedRowSpan: number;
  claimedColSpan: number;
  emittedRowSpan: number;
  emittedColSpan: number;
  outcome: "supported";
  evidenceIds: string[];
  concernCodes: string[];
}

interface ValidatedRepresentationCustody {
  serializerPolicyId: "p04-table-grid-serializer-v1";
  gridShape: number[];
  cellsSha256: string;
  rowsSha256: string;
  htmlSha256: string;
  markdownSha256: string;
  csvSha256: string;
}

interface ValidatedTableSemantics {
  policyId: "p04-table-evidence-v1";
  version: "1.1";
  tableId: string;
  candidateId: string;
  pageIndex: number;
  rowCount: number;
  columnCount: number;
  headerRowCount: number;
  rows: ValidatedTableRow[];
  cells: ValidatedTableCell[];
  slots: ValidatedTableSlot[];
  sourceObjects: ValidatedSourceObject[];
  evidence: ValidatedEvidence[];
  spanDecisions: ValidatedSpanDecision[];
  representationCustody: ValidatedRepresentationCustody;
  concerns: string[];
}

interface TableSemanticsContext {
  sourceSha256: string;
  pageIndex: number;
  pageWidth: number;
  pageHeight: number;
  unit: "pt";
}

const MAX_TABLE_BYTES = 8_388_608;
const MAX_TABLE_NODES = 4_194_304;
const MAX_TABLE_DEPTH = 32;
const UTF8_ENCODER = new TextEncoder();
const SHA256_CONSTANTS = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
  0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
  0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
  0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
  0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
  0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);
// SHA-256 is synchronous and invokes no callbacks, so one private schedule can
// be reused safely without exposing mutable state or retaining input bytes.
const SHA256_WORDS = new Uint32Array(64);
const HEX_BYTES = Array.from(
  { length: 256 },
  (_, value) => value.toString(16).padStart(2, "0"),
);
const FLOAT64_BUFFER = new ArrayBuffer(8);
const FLOAT64_VIEW = new DataView(FLOAT64_BUFFER);
const FLOAT64_BYTES = new Uint8Array(FLOAT64_BUFFER);

function utf8ByteLength(value: string): number | null {
  let byteLength = 0;
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (codeUnit <= 0x7f) {
      byteLength += 1;
    } else if (codeUnit <= 0x7ff) {
      byteLength += 2;
    } else if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
      const trailing = value.charCodeAt(index + 1);
      if (!(trailing >= 0xdc00 && trailing <= 0xdfff)) return null;
      byteLength += 4;
      index += 1;
    } else if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
      return null;
    } else {
      byteLength += 3;
    }
  }
  return byteLength;
}

function utf8Bytes(value: string): Uint8Array | null {
  return utf8ByteLength(value) === null ? null : UTF8_ENCODER.encode(value);
}

function boundedJsonStringByteLength(
  value: string,
  maximumRawBytes: number,
): number | null {
  let rawBytes = 0;
  let jsonBytes = 2;
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    let encodedBytes = 0;
    if (codeUnit <= 0x7f) {
      encodedBytes = 1;
    } else if (codeUnit <= 0x7ff) {
      encodedBytes = 2;
    } else if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
      const trailing = value.charCodeAt(index + 1);
      if (!(trailing >= 0xdc00 && trailing <= 0xdfff)) return null;
      encodedBytes = 4;
      index += 1;
    } else if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
      return null;
    } else {
      encodedBytes = 3;
    }
    rawBytes += encodedBytes;
    if (rawBytes > maximumRawBytes) return null;
    if (codeUnit === 0x22 || codeUnit === 0x5c) {
      jsonBytes += 2;
    } else if (codeUnit < 0x20) {
      jsonBytes +=
        codeUnit === 0x08 ||
        codeUnit === 0x09 ||
        codeUnit === 0x0a ||
        codeUnit === 0x0c ||
        codeUnit === 0x0d
          ? 2
          : 6;
    } else {
      jsonBytes += encodedBytes;
    }
  }
  return jsonBytes;
}

function markedTableFitsResourceBounds(value: unknown): boolean {
  type Pending = { value: unknown; depth: number; leaving: boolean };
  const pending: Pending[] = [{ value, depth: 0, leaving: false }];
  const active = new Set<object>();
  let nodeCount = 0;
  let encodedBytes = 0;
  const addBytes = (count: number): boolean => {
    encodedBytes += count;
    return encodedBytes <= MAX_TABLE_BYTES;
  };

  while (pending.length > 0) {
    const current = pending.pop();
    if (current === undefined) return false;
    if (current.leaving) {
      if (typeof current.value === "object" && current.value !== null) {
        active.delete(current.value);
      }
      continue;
    }
    nodeCount += 1;
    if (nodeCount > MAX_TABLE_NODES || current.depth > MAX_TABLE_DEPTH) {
      return false;
    }
    const entry = current.value;
    if (entry === null) {
      if (!addBytes(4)) return false;
      continue;
    }
    if (typeof entry === "boolean") {
      if (!addBytes(entry ? 4 : 5)) return false;
      continue;
    }
    if (typeof entry === "number") {
      if (!Number.isFinite(entry)) return false;
      const serialized = JSON.stringify(Object.is(entry, -0) ? 0 : entry);
      if (serialized === undefined || !addBytes(serialized.length)) return false;
      continue;
    }
    if (typeof entry === "string") {
      const jsonByteLength = boundedJsonStringByteLength(entry, 1_048_576);
      if (jsonByteLength === null || !addBytes(jsonByteLength)) return false;
      continue;
    }
    if (typeof entry !== "object") return false;
    if (active.has(entry)) return false;
    if (current.depth >= MAX_TABLE_DEPTH) return false;
    active.add(entry);
    pending.push({ value: entry, depth: current.depth, leaving: true });

    if (Array.isArray(entry)) {
      if (
        entry.length > 65_536 ||
        Object.keys(entry).length !== entry.length ||
        !addBytes(2 + Math.max(entry.length - 1, 0))
      ) {
        return false;
      }
      for (let index = entry.length - 1; index >= 0; index -= 1) {
        pending.push({
          value: entry[index],
          depth: current.depth + 1,
          leaving: false,
        });
      }
      continue;
    }

    const keys = Object.keys(entry);
    if (keys.length > 4_096 || !addBytes(2 + Math.max(keys.length - 1, 0))) {
      return false;
    }
    for (let index = keys.length - 1; index >= 0; index -= 1) {
      const key = keys[index];
      if (key === undefined) return false;
      const keyJsonByteLength = boundedJsonStringByteLength(key, 1_048_576);
      if (keyJsonByteLength === null || !addBytes(keyJsonByteLength + 1)) {
        return false;
      }
      pending.push({
        value: (entry as Record<string, unknown>)[key],
        depth: current.depth + 1,
        leaving: false,
      });
    }
  }
  return true;
}

function sha256Hex(bytes: Uint8Array): string {
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const bitLength = bytes.length * 8;
  const lengthView = new DataView(padded.buffer);
  lengthView.setUint32(paddedLength - 8, Math.floor(bitLength / 0x1_0000_0000), false);
  lengthView.setUint32(paddedLength - 4, bitLength >>> 0, false);
  let hash0 = 0x6a09e667;
  let hash1 = 0xbb67ae85;
  let hash2 = 0x3c6ef372;
  let hash3 = 0xa54ff53a;
  let hash4 = 0x510e527f;
  let hash5 = 0x9b05688c;
  let hash6 = 0x1f83d9ab;
  let hash7 = 0x5be0cd19;
  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      SHA256_WORDS[index] = lengthView.getUint32(offset + index * 4, false);
    }
    for (let index = 16; index < 64; index += 1) {
      const before15 = SHA256_WORDS[index - 15];
      const before2 = SHA256_WORDS[index - 2];
      const sigma0 =
        ((before15 >>> 7) | (before15 << 25)) ^
        ((before15 >>> 18) | (before15 << 14)) ^
        (before15 >>> 3);
      const sigma1 =
        ((before2 >>> 17) | (before2 << 15)) ^
        ((before2 >>> 19) | (before2 << 13)) ^
        (before2 >>> 10);
      SHA256_WORDS[index] =
        (SHA256_WORDS[index - 16] + sigma0 + SHA256_WORDS[index - 7] + sigma1) >>> 0;
    }

    let a = hash0;
    let b = hash1;
    let c = hash2;
    let d = hash3;
    let e = hash4;
    let f = hash5;
    let g = hash6;
    let h = hash7;
    for (let index = 0; index < 64; index += 1) {
      const upper1 =
        ((e >>> 6) | (e << 26)) ^
        ((e >>> 11) | (e << 21)) ^
        ((e >>> 25) | (e << 7));
      const choice = (e & f) ^ (~e & g);
      const temporary1 =
        (h + upper1 + choice + SHA256_CONSTANTS[index] + SHA256_WORDS[index]) >>> 0;
      const upper0 =
        ((a >>> 2) | (a << 30)) ^
        ((a >>> 13) | (a << 19)) ^
        ((a >>> 22) | (a << 10));
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temporary2 = (upper0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temporary1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temporary1 + temporary2) >>> 0;
    }
    hash0 = (hash0 + a) >>> 0;
    hash1 = (hash1 + b) >>> 0;
    hash2 = (hash2 + c) >>> 0;
    hash3 = (hash3 + d) >>> 0;
    hash4 = (hash4 + e) >>> 0;
    hash5 = (hash5 + f) >>> 0;
    hash6 = (hash6 + g) >>> 0;
    hash7 = (hash7 + h) >>> 0;
  }
  return [hash0, hash1, hash2, hash3, hash4, hash5, hash6, hash7]
    .map((value) => value.toString(16).padStart(8, "0"))
    .join("");
}

function float64Hex(value: number): string {
  FLOAT64_VIEW.setFloat64(0, Object.is(value, -0) ? 0 : value, false);
  let result = "";
  for (let index = 0; index < FLOAT64_BYTES.length; index += 1) {
    result += HEX_BYTES[FLOAT64_BYTES[index] ?? 0];
  }
  return result;
}

function canonicalCustodyJson(value: unknown): string | null {
  const fragments: string[] = [];
  let byteCount = 0;
  const append = (fragment: string, byteLength: number): boolean => {
    if (byteCount + byteLength > 8_388_608) return false;
    fragments.push(fragment);
    byteCount += byteLength;
    return true;
  };
  const appendJsonString = (entry: string, suffix = ""): boolean => {
    const byteLength = boundedJsonStringByteLength(entry, 8_388_608);
    return (
      byteLength !== null &&
      append(`${JSON.stringify(entry)}${suffix}`, byteLength + suffix.length)
    );
  };
  const visit = (entry: unknown): boolean => {
    if (entry === null) return append("null", 4);
    if (typeof entry === "boolean") {
      return append(entry ? "true" : "false", entry ? 4 : 5);
    }
    if (typeof entry === "string") return appendJsonString(entry);
    if (typeof entry === "number") {
      if (!Number.isFinite(entry)) return false;
      const fragment = `{"$p04_f64":"${float64Hex(entry)}"}`;
      return append(fragment, fragment.length);
    }
    if (Array.isArray(entry)) {
      if (!append("[", 1)) return false;
      for (let index = 0; index < entry.length; index += 1) {
        if ((index > 0 && !append(",", 1)) || !visit(entry[index])) return false;
      }
      return append("]", 1);
    }
    if (typeof entry !== "object") return false;
    const record = entry as Record<string, unknown>;
    if (!append("{", 1)) return false;
    const keys = Object.keys(record).sort();
    for (let index = 0; index < keys.length; index += 1) {
      const key = keys[index];
      if (
        key === undefined ||
        key === "$p04_f64" ||
        (index > 0 && !append(",", 1)) ||
        !appendJsonString(key, ":") ||
        !visit(record[key])
      ) {
        return false;
      }
    }
    return append("}", 1);
  };
  return visit(value) ? fragments.join("") : null;
}

function custodySha256(value: unknown): string | null {
  const canonical = canonicalCustodyJson(value);
  if (canonical === null) return null;
  const bytes = utf8Bytes(canonical);
  return bytes === null ? null : sha256Hex(bytes);
}

function textSha256(value: string): string | null {
  const bytes = utf8Bytes(value);
  return bytes === null ? null : sha256Hex(bytes);
}

function escapeTableHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#x27;")
    .replaceAll("\n", "<br>");
}

function serializeCsvField(value: string, singleEmptyField: boolean): string {
  if (
    singleEmptyField ||
    value.includes(",") ||
    value.includes('"') ||
    value.includes("\r") ||
    value.includes("\n")
  ) {
    return `"${value.replaceAll('"', '""')}"`;
  }
  return value;
}

function replayTableGrid(
  cells: ValidatedTableCell[],
  slots: ValidatedTableSlot[],
  rowCount: number,
  columnCount: number,
): {
  rows: string[][];
  html: string;
  csv: string;
  headerRowCount: number;
  renderedRows: ValidatedTableRow[];
} | null {
  const cellsById = new Map(cells.map((cell) => [cell.id, cell]));
  if (cellsById.size !== cells.length) return null;
  const rows: string[][] = [];
  const slotRows: ValidatedTableSlot[][] = [];
  const renderedRows: ValidatedTableRow[] = [];
  let cursor = 0;

  for (let row = 0; row < rowCount; row += 1) {
    const rowValues: string[] = [];
    const rowSlots: ValidatedTableSlot[] = [];
    const rowCells: ValidatedTableCell[] = [];
    for (let column = 0; column < columnCount; column += 1) {
      const slot = slots[cursor];
      cursor += 1;
      if (slot === undefined || slot.row !== row || slot.column !== column) {
        return null;
      }
      rowSlots.push(slot);
      if (slot.kind === "covered") {
        rowValues.push("");
        continue;
      }
      if (slot.cellId === null) return null;
      const cell = cellsById.get(slot.cellId);
      if (cell === undefined) return null;
      rowValues.push(cell.text);
      rowCells.push(cell);
    }
    rows.push(rowValues);
    slotRows.push(rowSlots);
    renderedRows.push({ row, cells: rowCells, columnHeaderRow: false });
  }
  if (cursor !== slots.length) return null;

  let headerRowCount = 0;
  for (const rowSlots of slotRows) {
    let headerAnchorCount = 0;
    let nonHeaderAnchorCount = 0;
    for (const slot of rowSlots) {
      if (slot.kind === "covered" || slot.cellId === null) continue;
      const cell = cellsById.get(slot.cellId);
      if (cell === undefined) return null;
      if (cell.columnHeader) headerAnchorCount += 1;
      else nonHeaderAnchorCount += 1;
    }
    if (headerAnchorCount > 0 && nonHeaderAnchorCount === 0) {
      headerRowCount += 1;
    } else {
      break;
    }
  }
  for (let row = 0; row < renderedRows.length; row += 1) {
    const rendered = renderedRows[row];
    if (rendered === undefined) return null;
    rendered.columnHeaderRow = row < headerRowCount;
  }

  const htmlLines = ["<table>"];
  for (let row = 0; row < rowCount; row += 1) {
    if (row === 0 && headerRowCount > 0) htmlLines.push("  <thead>");
    if (row === headerRowCount) {
      if (headerRowCount > 0) htmlLines.push("  </thead>");
      htmlLines.push("  <tbody>");
    }
    htmlLines.push("    <tr>");
    const rowSlots = slotRows[row];
    if (rowSlots === undefined) return null;
    for (const slot of rowSlots) {
      if (slot.kind === "covered") continue;
      if (slot.cellId === null) return null;
      const cell = cellsById.get(slot.cellId);
      if (cell === undefined) return null;
      let tag = "td";
      let attributes = "";
      if (cell.columnHeader) {
        tag = "th";
        attributes += ' scope="col"';
      } else if (cell.rowHeader) {
        tag = "th";
        attributes += ' scope="row"';
      }
      if (cell.rowSpan > 1) attributes += ` rowspan="${cell.rowSpan}"`;
      if (cell.colSpan > 1) attributes += ` colspan="${cell.colSpan}"`;
      htmlLines.push(
        `      <${tag}${attributes}>${escapeTableHtml(cell.text)}</${tag}>`,
      );
    }
    htmlLines.push("    </tr>");
  }
  htmlLines.push(headerRowCount === rowCount ? "  </thead>" : "  </tbody>");
  htmlLines.push("</table>");
  const html = htmlLines.join("\n");
  const csv = rows
    .map((row) =>
      row
        .map((value) => serializeCsvField(value, row.length === 1 && value === ""))
        .join(","),
    )
    .join("\n");
  if (
    (utf8ByteLength(html) ?? MAX_TABLE_BYTES + 1) > MAX_TABLE_BYTES ||
    (utf8ByteLength(csv) ?? MAX_TABLE_BYTES + 1) > MAX_TABLE_BYTES
  ) {
    return null;
  }
  return { rows, html, csv, headerRowCount, renderedRows };
}

function matricesAreEqual(left: string[][], right: string[][]): boolean {
  return left.every(
    (row, rowIndex) =>
      right[rowIndex] !== undefined &&
      row.every((value, columnIndex) => value === right[rowIndex]?.[columnIndex]),
  );
}

function tableBboxesAreEqual(
  left: ValidatedTableBBox | null,
  right: ValidatedTableBBox | null,
): boolean {
  if (left === null || right === null) return left === right;
  return (
    left.x === right.x &&
    left.y === right.y &&
    left.width === right.width &&
    left.height === right.height &&
    left.unit === right.unit
  );
}

function pythonFloatJson(value: number): string | null {
  if (!Number.isFinite(value)) return null;
  if (Object.is(value, -0)) return "-0.0";
  const negative = value < 0;
  const rendered = Math.abs(value).toString();
  let digits: string;
  let decimalExponent: number;
  const exponentIndex = rendered.indexOf("e");
  if (exponentIndex >= 0) {
    const coefficient = rendered.slice(0, exponentIndex);
    const decimalIndex = coefficient.indexOf(".");
    const wholeDigits = decimalIndex < 0 ? coefficient.length : decimalIndex;
    digits = coefficient.replace(".", "");
    decimalExponent =
      Number(rendered.slice(exponentIndex + 1)) + wholeDigits - 1;
  } else {
    const decimalIndex = rendered.indexOf(".");
    const wholeDigits = decimalIndex < 0 ? rendered.length : decimalIndex;
    const combined = rendered.replace(".", "");
    const firstNonzero = combined.search(/[1-9]/u);
    if (firstNonzero < 0) return negative ? "-0.0" : "0.0";
    digits = combined.slice(firstNonzero).replace(/0+$/u, "");
    decimalExponent = wholeDigits - firstNonzero - 1;
  }

  const sign = negative ? "-" : "";
  if (decimalExponent < -4 || decimalExponent >= 16) {
    const mantissa =
      digits.length === 1 ? digits : `${digits.charAt(0)}.${digits.slice(1)}`;
    const exponentSign = decimalExponent >= 0 ? "+" : "-";
    const exponentMagnitude = Math.abs(decimalExponent)
      .toString()
      .padStart(2, "0");
    return `${sign}${mantissa}e${exponentSign}${exponentMagnitude}`;
  }
  if (decimalExponent < 0) {
    return `${sign}0.${"0".repeat(-decimalExponent - 1)}${digits}`;
  }
  const wholeLength = decimalExponent + 1;
  if (digits.length <= wholeLength) {
    return `${sign}${digits}${"0".repeat(wholeLength - digits.length)}.0`;
  }
  return `${sign}${digits.slice(0, wholeLength)}.${digits.slice(wholeLength)}`;
}

function canonicalPdfWordBBox(bbox: ValidatedTableBBox): string | null {
  const height = pythonFloatJson(bbox.height);
  const width = pythonFloatJson(bbox.width);
  const x = pythonFloatJson(bbox.x);
  const y = pythonFloatJson(bbox.y);
  if (height === null || width === null || x === null || y === null) return null;
  return `{"height":${height},"unit":"pt","width":${width},"x":${x},"y":${y}}`;
}

function expectedPdfWordIdentity(
  context: TableSemanticsContext,
  tableReference: string,
  predecessorRows: number,
  predecessorColumns: number,
  source: ValidatedPdfplumberWordSetSourceObject,
  word: ValidatedTableWord,
): string | null {
  const bbox = canonicalPdfWordBBox(word.bbox);
  if (bbox === null) return null;
  return textSha256(
    `["p04-pdfplumber-word-id-v1",${JSON.stringify(context.sourceSha256)},${context.pageIndex},${JSON.stringify(tableReference)},${predecessorRows},${predecessorColumns},${JSON.stringify(source.role)},${source.targetRow},${source.targetColumn},${bbox}]`,
  );
}

function expectedPdfWordSetContent(
  source: ValidatedPdfplumberWordSetSourceObject,
): string | null {
  const words: string[] = [];
  for (const word of source.words) {
    const bbox = canonicalPdfWordBBox(word.bbox);
    if (bbox === null) return null;
    words.push(
      `[${JSON.stringify(word.id)},${JSON.stringify(word.text)},${bbox},${JSON.stringify(word.fontName)},${word.bold ? "true" : "false"}]`,
    );
  }
  return textSha256(
    `["p04-pdfplumber-word-set-content-v1",${JSON.stringify(source.role)},${source.targetRow},${source.targetColumn},[${words.join(",")}]]`,
  );
}

function expectedPdfWordSetIdentity(
  context: TableSemanticsContext,
  tableReference: string,
  predecessorRows: number,
  predecessorColumns: number,
  source: ValidatedPdfplumberWordSetSourceObject,
): string | null {
  return textSha256(
    `["p04-pdfplumber-word-set-id-v1",${JSON.stringify(context.sourceSha256)},${context.pageIndex},${JSON.stringify(tableReference)},${predecessorRows},${predecessorColumns},${JSON.stringify(source.role)},${source.targetRow},${source.targetColumn},[${source.words.map((word) => JSON.stringify(word.id)).join(",")}]]`,
  );
}

function canonicalStringArray(values: string[]): string {
  return `[${values.map((value) => JSON.stringify(value)).join(",")}]`;
}

function canonicalDoclingBBoxVariants(bbox: ValidatedTableBBox): string[] {
  const values = [bbox.height, bbox.width, bbox.x, bbox.y];
  const variants: string[][] = [];
  for (const value of values) {
    const floatValue = pythonFloatJson(value);
    if (floatValue === null) return [];
    const integerValue = Number.isInteger(value) ? JSON.stringify(value) : floatValue;
    variants.push(integerValue === floatValue ? [floatValue] : [integerValue, floatValue]);
  }
  const rendered: string[] = [];
  for (const height of variants[0] ?? []) {
    for (const width of variants[1] ?? []) {
      for (const x of variants[2] ?? []) {
        for (const y of variants[3] ?? []) {
          rendered.push(
            `{"height":${height},"unit":"pt","width":${width},"x":${x},"y":${y}}`,
          );
        }
      }
    }
  }
  return rendered;
}

function expectedRecoveredHeaderEvidence(
  context: TableSemanticsContext,
  tableReference: string,
  predecessorRows: number,
  predecessorColumns: number,
  column: number,
  gridSourceId: string,
  headerSource: ValidatedPdfplumberWordSetSourceObject,
  bodySource: ValidatedPdfplumberWordSetSourceObject,
  targetBBox: ValidatedTableBBox,
  evidence: ValidatedEvidence,
): boolean {
  const sourceIds = [gridSourceId, headerSource.id, bodySource.id].sort();
  if (
    evidence.sourceObjectIds.length !== sourceIds.length ||
    evidence.sourceObjectIds.some((id, index) => id !== sourceIds[index])
  ) {
    return false;
  }
  for (const bbox of canonicalDoclingBBoxVariants(targetBBox)) {
    const contentSha256 = textSha256(
      `["p04-recovered-header-content-v1",0,${column},${JSON.stringify(gridSourceId)},${JSON.stringify(headerSource.contentSha256)},${JSON.stringify(bodySource.contentSha256)},${bbox},[true,false]]`,
    );
    const evidenceId = textSha256(
      `["p04-recovered-header-evidence-id-v1",${JSON.stringify(context.sourceSha256)},${context.pageIndex},${JSON.stringify(tableReference)},${predecessorRows},${predecessorColumns},0,${column},${canonicalStringArray(sourceIds)},${bbox},${JSON.stringify(contentSha256)}]`,
    );
    if (evidence.contentSha256 === contentSha256 && evidence.id === evidenceId) {
      return true;
    }
  }
  return false;
}

function expectedRecoveredBottomIdentity(
  tag:
    | "p04-recovered-cell-id-v1"
    | "p04-recovered-text-evidence-id-v1"
    | "p04-recovered-geometry-evidence-id-v1",
  context: TableSemanticsContext,
  tableReference: string,
  predecessorRows: number,
  predecessorColumns: number,
  sourceId: string,
  bbox: ValidatedTableBBox,
  row: number,
  column: number,
): string | null {
  const canonicalBBox = canonicalPdfWordBBox(bbox);
  if (canonicalBBox === null) return null;
  return textSha256(
    `[${JSON.stringify(tag)},[${JSON.stringify(context.sourceSha256)},${context.pageIndex},${JSON.stringify(tableReference)},${predecessorRows},${predecessorColumns},${JSON.stringify(sourceId)},${canonicalBBox},${row},${column}]]`,
  );
}

function canonicalDoclingBBoxCandidates(
  bbox: ValidatedTableBBox | null,
): string[] {
  if (bbox === null) return ["null"];
  return canonicalDoclingBBoxVariants(bbox);
}

interface ExpectedDoclingCellFacts {
  bboxJson: string;
  cellId: string;
  sourceId: string;
  textEvidenceId: string;
  geometryEvidenceId: string | null;
  decisionId: string | null;
  contentSha256: string;
}

function expectedDoclingCellFacts(
  context: TableSemanticsContext,
  rawReference: string,
  cell: ValidatedTableCell,
  originalColumnHeader: boolean,
  includeSpanFacts: boolean,
): ExpectedDoclingCellFacts[] {
  return canonicalDoclingBBoxCandidates(cell.bbox).map((bboxJson) => {
    const identityTail = `[${JSON.stringify(context.sourceSha256)},${context.pageIndex},"docling",${JSON.stringify(rawReference)},${bboxJson},${cell.row},${cell.column},${cell.rowSpan},${cell.colSpan}]`;
    const identity = (tag: string): string =>
      textSha256(`[${JSON.stringify(tag)},${identityTail}]`) ?? "";
    return {
      bboxJson,
      cellId: identity("p04-cell-id-v1"),
      sourceId: identity("p04-cell-source-id-v1"),
      textEvidenceId: identity("p04-text-evidence-id-v1"),
      geometryEvidenceId: includeSpanFacts
        ? identity("p04-cell-geometry-evidence-id-v1")
        : null,
      decisionId: includeSpanFacts
        ? identity("p04-span-decision-id-v1")
        : null,
      contentSha256: textSha256(
        `["p04-cell-content-v1",${JSON.stringify(rawReference)},${bboxJson},${cell.row},${cell.column},${cell.rowSpan},${cell.colSpan},${JSON.stringify(cell.text)},${originalColumnHeader ? "true" : "false"},${cell.rowHeader ? "true" : "false"},${cell.rowSection ? "true" : "false"}]`,
      ) ?? "",
    };
  });
}

export function readTableSemantics(
  item: unknown,
  context?: TableSemanticsContext,
): ValidatedTableSemantics | null {
  const sidecarKeys = [
    "policy_id",
    "version",
    "scope",
    "status",
    "table_id",
    "candidate_id",
    "page_index",
    "grid",
    "slots",
    "source_objects",
    "evidence",
    "span_decisions",
    "representation_custody",
    "reconciliation",
    "gate",
    "continuation",
    "concerns",
  ];
  const gridKeys = ["row_count", "column_count", "cell_ids"];
  const slotKeys = [
    "id",
    "row",
    "column",
    "kind",
    "cell_id",
    "covered_by_cell_id",
  ];
  const cellKeys = [
    "id",
    "row",
    "column",
    "row_span",
    "col_span",
    "text",
    "column_header",
    "row_header",
    "row_section",
    "bbox",
    "source",
    "page_index",
    "evidence_ids",
    "source_object_ids",
    "span_decision_id",
    "confidence_dimensions",
  ];
  const bboxKeys = ["x", "y", "width", "height", "unit"];
  const confidenceKeys = ["text", "geometry", "structure", "header"];
  const doclingSourceObjectKeys = [
    "id",
    "engine",
    "object_type",
    "page_index",
    "raw_ref",
    "content_sha256",
  ];
  const wordSetSourceObjectKeys = [
    "id",
    "engine",
    "object_type",
    "page_index",
    "raw_ref",
    "role",
    "target_row",
    "target_column",
    "words",
    "content_sha256",
  ];
  const wordKeys = ["id", "text", "bbox", "font_name", "bold"];
  const evidenceKeys = [
    "id",
    "method",
    "dimension",
    "page_index",
    "bbox",
    "source_object_ids",
    "confidence",
    "content_sha256",
  ];
  const spanKeys = [
    "id",
    "cell_id",
    "claimed_row_span",
    "claimed_col_span",
    "emitted_row_span",
    "emitted_col_span",
    "outcome",
    "evidence_ids",
    "concern_codes",
  ];
  const custodyKeys = [
    "serializer_policy_id",
    "grid_shape",
    "cells_sha256",
    "rows_sha256",
    "html_sha256",
    "markdown_sha256",
    "csv_sha256",
  ];
  const concernValues = [
    "table_ambiguous_border_evidence",
    "table_malformed_source_evidence",
    "table_resource_limit_exceeded",
    "table_source_cell_bbox_unresolved",
    "table_source_cell_grid_unresolved",
    "table_source_form_grid_topology_unresolved",
    "table_source_header_ownership_unresolved",
    "table_source_provenance_unresolved",
    "table_source_rotation_mapping_unresolved",
    "table_source_row_boundary_unresolved",
    "table_source_span_evidence_unresolved",
  ];
  const evidenceMethods = [
    "embedded_grid",
    "model_structure",
    "native_text",
    "ocr_text",
    "recovered_structure",
    "source_grid",
  ];
  const evidenceDimensions = ["geometry", "header", "structure", "text"];
  const isRecord = (value: unknown): value is JsonRecord =>
    value !== null && typeof value === "object" && !Array.isArray(value);

  const exactKeys = (value: unknown, expected: string[]): value is JsonRecord => {
    if (!isRecord(value)) return false;
    const actualKeys = Object.keys(value);
    return (
      actualKeys.length === expected.length &&
      expected.every((key) => actualKeys.includes(key))
    );
  };

  const isInteger = (value: unknown, minimum: number, maximum: number): value is number =>
    typeof value === "number" &&
    Number.isFinite(value) &&
    value % 1 === 0 &&
    value >= minimum &&
    value <= maximum;

  const isBoundedText = (
    value: unknown,
    maximumBytes: number,
    allowEmpty: boolean,
    allowLineBreaks: boolean,
  ): value is string => {
    if (typeof value !== "string" || (!allowEmpty && value.length === 0)) {
      return false;
    }
    let byteLength = 0;
    for (let index = 0; index < value.length; index += 1) {
      const codeUnit = value.charCodeAt(index);
      if (
        (codeUnit < 0x20 &&
          !(allowLineBreaks && (codeUnit === 0x09 || codeUnit === 0x0a))) ||
        codeUnit === 0x7f
      ) {
        return false;
      }
      if (codeUnit <= 0x7f) {
        byteLength += 1;
      } else if (codeUnit <= 0x7ff) {
        byteLength += 2;
      } else if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
        const trailing = value.charCodeAt(index + 1);
        if (!(trailing >= 0xdc00 && trailing <= 0xdfff)) return false;
        byteLength += 4;
        index += 1;
      } else if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
        return false;
      } else {
        byteLength += 3;
      }
      if (byteLength > maximumBytes) return false;
    }
    return true;
  };

  const validatedSha256Values = new Set<string>();
  const isSha256 = (value: unknown): value is string => {
    if (typeof value !== "string" || value.length !== 64) return false;
    if (validatedSha256Values.has(value)) return true;
    for (let index = 0; index < value.length; index += 1) {
      const codeUnit = value.charCodeAt(index);
      if (
        !(
          (codeUnit >= 0x30 && codeUnit <= 0x39) ||
          (codeUnit >= 0x61 && codeUnit <= 0x66)
        )
      ) {
        return false;
      }
    }
    if (validatedSha256Values.size < 262_144) {
      validatedSha256Values.add(value);
    }
    return true;
  };

  const readOrderedHashes = (
    value: unknown,
    maximum: number,
  ): string[] | null => {
    if (!Array.isArray(value) || value.length > maximum) return null;
    const orderedHashValues: string[] = [];
    let previous = "";
    for (const entry of value) {
      if (!isSha256(entry) || (previous.length > 0 && entry <= previous)) {
        return null;
      }
      previous = entry;
      orderedHashValues.push(entry);
    }
    return orderedHashValues;
  };

  const readOrderedConcerns = (
    value: unknown,
  ): string[] | null => {
    if (!Array.isArray(value) || value.length > 64) return null;
    const orderedConcernValues = Object.values(value);
    const allowedConcernValues = Object.values(concernValues);
    let previous = "";
    const concernsOrdered = orderedConcernValues.every((entry) => {
      if (
        typeof entry !== "string" ||
        !allowedConcernValues.includes(entry) ||
        (previous.length > 0 && entry <= previous)
      ) {
        return false;
      }
      previous = entry;
      return true;
    });
    if (!concernsOrdered) return null;
    const validatedConcernValues = orderedConcernValues.filter((entry): entry is string => typeof entry === "string");
    return validatedConcernValues;
  };

  const isOrderedSubset = (
    references: string[],
    candidates: ReadonlySet<string>,
  ): boolean => {
    return references.every((reference) => candidates.has(reference));
  };

  const readBBox = (value: unknown): ValidatedTableBBox | null | false => {
    if (value === null) return null;
    if (!exactKeys(value, bboxKeys)) return false;
    if (
      typeof value.x !== "number" ||
      !Number.isFinite(value.x) ||
      value.x < 0 ||
      typeof value.y !== "number" ||
      !Number.isFinite(value.y) ||
      value.y < 0 ||
      typeof value.width !== "number" ||
      !Number.isFinite(value.width) ||
      value.width <= 0 ||
      typeof value.height !== "number" ||
      !Number.isFinite(value.height) ||
      value.height <= 0 ||
      value.unit !== "pt"
    ) {
      return false;
    }
    const validated = {
      x: value.x,
      y: value.y,
      width: value.width,
      height: value.height,
      unit: "pt",
    } as ValidatedTableBBox;
    if (
      context === undefined ||
      validated.x + validated.width > context.pageWidth + 0.000_001 ||
      validated.y + validated.height > context.pageHeight + 0.000_001
    ) {
      return false;
    }
    return validated;
  };

  const readConfidence = (value: unknown): ValidatedConfidenceDimensions | null => {
    if (!exactKeys(value, confidenceKeys)) return null;
    const confidenceValues = [value.text, value.geometry, value.structure, value.header];
    if (
      !confidenceValues.every(
        (entry) =>
          entry === null ||
          (typeof entry === "number" &&
            Number.isFinite(entry) &&
            entry >= 0 &&
            entry <= 1),
      )
    ) {
      return null;
    }
    return {
      text: value.text as number | null,
      geometry: value.geometry as number | null,
      structure: value.structure as number | null,
      header: value.header as number | null,
    };
  };

  if (!isRecord(item)) return null;
  const itemKeys = Object.keys(item);
  if (item.type !== "table" || !itemKeys.includes("table_evidence")) {
    return null;
  }
  if (
    !markedTableFitsResourceBounds(item) ||
    context === undefined ||
    !isSha256(context.sourceSha256) ||
    !isInteger(context.pageIndex, 1, 1_000_000) ||
    typeof context.pageWidth !== "number" ||
    !Number.isFinite(context.pageWidth) ||
    context.pageWidth <= 0 ||
    typeof context.pageHeight !== "number" ||
    !Number.isFinite(context.pageHeight) ||
    context.pageHeight <= 0 ||
    context.unit !== "pt"
  ) {
    return null;
  }
  const sidecar = item.table_evidence;
  if (!exactKeys(sidecar, sidecarKeys) || sidecar.status !== "valid") return null;
  if (!Array.isArray(sidecar.scope) || sidecar.scope.length !== 1) return null;
  const scopeValues = sidecar.scope;
  if (
    sidecar.policy_id !== "p04-table-evidence-v1" ||
    sidecar.version !== "1.1" ||
    !scopeValues.every((entry) => entry === "P04-US01") ||
    !isSha256(sidecar.table_id) ||
    !isSha256(sidecar.candidate_id) ||
    !isInteger(sidecar.page_index, 1, 1_000_000) ||
    sidecar.page_index !== context.pageIndex ||
    sidecar.reconciliation !== null ||
    sidecar.gate !== null ||
    sidecar.continuation !== null
  ) {
    return null;
  }

  const concerns = readOrderedConcerns(sidecar.concerns);
  if (!concerns || !exactKeys(sidecar.grid, gridKeys)) return null;
  const validatedConcerns = Object.values(concerns);
  const grid = sidecar.grid;
  if (
    !isInteger(grid.row_count, 1, 4096) ||
    !isInteger(grid.column_count, 1, 256) ||
    grid.row_count * grid.column_count > 65_536
  ) {
    return null;
  }
  const rowCount = grid.row_count;
  const columnCount = grid.column_count;
  const pageIndex = sidecar.page_index;

  const isSafeDoclingReference = (value: unknown): value is string => {
    if (
      !isBoundedText(value, 256, false, false) ||
      !value.startsWith("#/") ||
      value.includes("\\")
    ) {
      return false;
    }
    for (let index = 0; index < value.length; index += 1) {
      if (value.charCodeAt(index) > 0x7f) return false;
    }
    const components = value.slice(2).split("/");
    return (
      components.length > 0 &&
      components.length <= 256 &&
      components.every(
        (component) =>
          component.length > 0 &&
          component !== "." &&
          component !== ".." &&
          Array.from(component).every((character) => {
            const code = character.codePointAt(0);
            return code !== undefined && code >= 0x21 && code <= 0x7e;
          }),
      )
    );
  };

  if (
    !Array.isArray(sidecar.source_objects) ||
    sidecar.source_objects.length < 1 ||
    sidecar.source_objects.length > 65_536
  ) {
    return null;
  }
  let wordSetCount = 0;
  const observedWordIds = new Set<string>();
  const observedWordGeometry = new Set<string>();
  const sourceValues = sidecar.source_objects;
  const sourceObjects = sourceValues.map((entry) => {
    if (exactKeys(entry, doclingSourceObjectKeys)) {
      if (
        !isSha256(entry.id) ||
        entry.engine !== "docling" ||
        (entry.object_type !== "table_cell" &&
          entry.object_type !== "table_geometry" &&
          entry.object_type !== "table_grid") ||
        entry.page_index !== pageIndex ||
        !isSafeDoclingReference(entry.raw_ref) ||
        !isSha256(entry.content_sha256)
      ) {
        return null;
      }
      return {
        id: entry.id,
        engine: "docling",
        objectType: entry.object_type,
        pageIndex: entry.page_index,
        rawRef: entry.raw_ref,
        contentSha256: entry.content_sha256,
      } as ValidatedDoclingSourceObject;
    }
    if (!exactKeys(entry, wordSetSourceObjectKeys)) return null;
    wordSetCount += 1;
    if (
      wordSetCount > 48 ||
      !isSha256(entry.id) ||
      entry.engine !== "pdfplumber" ||
      entry.object_type !== "table_word_set" ||
      entry.page_index !== pageIndex ||
      entry.raw_ref !== null ||
      (entry.role !== "header" &&
        entry.role !== "body_control" &&
        entry.role !== "bottom_row") ||
      !isInteger(entry.target_row, 0, rowCount - 1) ||
      !isInteger(entry.target_column, 0, columnCount - 1) ||
      !Array.isArray(entry.words) ||
      entry.words.length < 1 ||
      entry.words.length > 64 ||
      !isSha256(entry.content_sha256)
    ) {
      return null;
    }
    if (entry.role === "bottom_row" && entry.target_row !== rowCount - 1) {
      return null;
    }
    const words: ValidatedTableWord[] = [];
    let previousGeometry: [number, number, number, number] | null = null;
    for (const word of Object.values(entry.words)) {
      if (!exactKeys(word, wordKeys)) return null;
      const wordBBox = readBBox(word.bbox);
      if (
        !isSha256(word.id) ||
        observedWordIds.has(word.id) ||
        !isBoundedText(word.text, 16_384, false, false) ||
        word.text.trim().length === 0 ||
        wordBBox === false ||
        wordBBox === null ||
        !isBoundedText(word.font_name, 256, false, false) ||
        typeof word.bold !== "boolean" ||
        word.bold !== word.font_name.toLowerCase().includes("bold")
      ) {
        return null;
      }
      const geometry: [number, number, number, number] = [
        wordBBox.y,
        wordBBox.x,
        wordBBox.height,
        wordBBox.width,
      ];
      const geometryKey = geometry.map((value) => float64Hex(value)).join(":");
      if (observedWordGeometry.has(geometryKey)) return null;
      if (previousGeometry !== null) {
        let comparison = 0;
        for (let index = 0; index < geometry.length; index += 1) {
          const left = geometry[index];
          const right = previousGeometry[index];
          if (left === undefined || right === undefined) return null;
          if (left < right) {
            comparison = -1;
            break;
          }
          if (left > right) {
            comparison = 1;
            break;
          }
        }
        if (comparison <= 0) return null;
      }
      previousGeometry = geometry;
      observedWordIds.add(word.id);
      observedWordGeometry.add(geometryKey);
      words.push({
        id: word.id,
        text: word.text,
        bbox: wordBBox,
        fontName: word.font_name,
        bold: word.bold,
      });
    }
    return {
      id: entry.id,
      engine: "pdfplumber",
      objectType: "table_word_set",
      pageIndex: entry.page_index,
      rawRef: null,
      role: entry.role,
      targetRow: entry.target_row,
      targetColumn: entry.target_column,
      words,
      contentSha256: entry.content_sha256,
    } as ValidatedPdfplumberWordSetSourceObject;
  });
  const sourceObjectResults = sourceObjects;
  if (!sourceObjectResults.every(Boolean)) return null;
  const validatedSourceObjects = sourceObjectResults as ValidatedSourceObject[];
  const sourceIds = validatedSourceObjects.map((entry) => entry.id);
  if (!sourceIds.every((entry, index) => index === 0 || entry > sourceIds[index - 1])) {
    return null;
  }
  const sourceIdSet = new Set(sourceIds);
  const sourceById = new Map(
    validatedSourceObjects.map((sourceObject) => [sourceObject.id, sourceObject]),
  );
  if (sourceById.size !== validatedSourceObjects.length) return null;
  const geometrySources = validatedSourceObjects.filter(
    (source): source is ValidatedDoclingSourceObject =>
      source.objectType === "table_geometry",
  );
  const gridSources = validatedSourceObjects.filter(
    (source): source is ValidatedDoclingSourceObject =>
      source.objectType === "table_grid",
  );
  const wordSetSources = validatedSourceObjects.filter(
    (source): source is ValidatedPdfplumberWordSetSourceObject =>
      source.engine === "pdfplumber" && source.objectType === "table_word_set",
  );
  const tableBBox = readBBox(item.bbox);
  if (
    geometrySources.length !== 1 ||
    gridSources.length !== 1 ||
    geometrySources[0]?.rawRef !== gridSources[0]?.rawRef ||
    tableBBox === false ||
    tableBBox === null ||
    item.engine !== "docling" ||
    (item.source !== "native" && item.source !== "ocr")
  ) {
    return null;
  }
  const hasBottomRecovery = wordSetSources.some(
    (source) => source.role === "bottom_row",
  );
  const hasRecovery = wordSetSources.length > 0;
  const predecessorRows = rowCount - (hasBottomRecovery ? 1 : 0);
  if (predecessorRows < 1) return null;
  const tableReference = gridSources[0]?.rawRef;
  if (tableReference === undefined) return null;
  for (const source of wordSetSources) {
    if (
      (source.role === "bottom_row" && source.targetRow !== predecessorRows) ||
      (source.role !== "bottom_row" && source.targetRow >= predecessorRows) ||
      source.words.some(
        (word) =>
          expectedPdfWordIdentity(
            context,
            tableReference,
            predecessorRows,
            columnCount,
            source,
            word,
          ) !== word.id,
      ) ||
      expectedPdfWordSetContent(source) !== source.contentSha256 ||
      expectedPdfWordSetIdentity(
        context,
        tableReference,
        predecessorRows,
        columnCount,
        source,
      ) !== source.id
    ) {
      return null;
    }
  }

  if (!Array.isArray(sidecar.evidence) || sidecar.evidence.length > 65_536) return null;
  const evidenceValues = sidecar.evidence;
  const allowedEvidenceMethods = Object.values(evidenceMethods);
  const allowedEvidenceDimensions = Object.values(evidenceDimensions);
  const evidence = evidenceValues.map((entry) => {
    if (!exactKeys(entry, evidenceKeys)) return null;
    const bbox = readBBox(entry.bbox);
    const sourceObjectIds = readOrderedHashes(entry.source_object_ids, 64);
    if (
      !isSha256(entry.id) ||
      typeof entry.method !== "string" ||
      !allowedEvidenceMethods.includes(entry.method) ||
      typeof entry.dimension !== "string" ||
      !allowedEvidenceDimensions.includes(entry.dimension) ||
      entry.page_index !== pageIndex ||
      bbox === false ||
      !sourceObjectIds ||
      sourceObjectIds.length === 0 ||
      !isOrderedSubset(sourceObjectIds, sourceIdSet) ||
      typeof entry.confidence !== "number" ||
      !Number.isFinite(entry.confidence) ||
      entry.confidence !== 1 ||
      !isSha256(entry.content_sha256)
    ) {
      return null;
    }
    return {
      id: entry.id,
      method: entry.method,
      dimension: entry.dimension,
      pageIndex: entry.page_index,
      bbox,
      sourceObjectIds,
      confidence: entry.confidence,
      contentSha256: entry.content_sha256,
    } as ValidatedEvidence;
  });
  const evidenceResults = evidence;
  if (!evidenceResults.every(Boolean)) return null;
  const validatedEvidence = evidenceResults as ValidatedEvidence[];
  const evidenceIds = validatedEvidence.map((entry) => entry.id);
  if (!evidenceIds.every((entry, index) => index === 0 || entry > evidenceIds[index - 1])) {
    return null;
  }
  const evidenceIdSet = new Set(evidenceIds);
  const evidenceById = new Map(validatedEvidence.map((entry) => [entry.id, entry]));
  if (evidenceById.size !== validatedEvidence.length) return null;
  const evidenceTypesAreCoherent = validatedEvidence.every((record) => {
    const linkedSources = record.sourceObjectIds.map((id) => sourceById.get(id));
    if (linkedSources.some((source) => source === undefined)) return false;
    const sources = linkedSources.filter(
      (source): source is ValidatedSourceObject => source !== undefined,
    );
    const matchesSingleDocling = (
      objectTypes: ValidatedDoclingSourceObject["objectType"][],
    ): boolean =>
      sources.length === 1 &&
      sources[0]?.engine === "docling" &&
      objectTypes.includes(sources[0].objectType);
    if (record.method === "native_text" || record.method === "ocr_text") {
      if (record.dimension !== "text" || sources.length !== 1) return false;
      const source = sources[0];
      if (
        source === undefined ||
        !(
          (source.engine === "docling" && source.objectType === "table_cell") ||
          (source.engine === "pdfplumber" &&
            source.objectType === "table_word_set" &&
            source.role === "bottom_row")
        )
      ) {
        return false;
      }
      return (
        source.engine === "pdfplumber" ||
        record.contentSha256 === source.contentSha256
      );
    }
    if (record.method === "embedded_grid") {
      return (
        record.dimension === "geometry" &&
        matchesSingleDocling(["table_cell", "table_geometry"]) &&
        record.contentSha256 === sources[0]?.contentSha256
      );
    }
    if (record.method === "source_grid") {
      return (
        record.dimension === "structure" &&
        matchesSingleDocling(["table_grid"]) &&
        record.contentSha256 === sources[0]?.contentSha256
      );
    }
    if (record.method === "model_structure") {
      return (
        record.dimension === "header" &&
        matchesSingleDocling(["table_grid"]) &&
        record.contentSha256 === sources[0]?.contentSha256
      );
    }
    if (record.method !== "recovered_structure") return false;
    if (
      record.dimension !== "header" &&
      record.dimension !== "geometry" &&
      record.dimension !== "structure"
    ) {
      return false;
    }
    const wordSources = sources.filter(
      (source): source is ValidatedPdfplumberWordSetSourceObject =>
        source.engine === "pdfplumber" && source.objectType === "table_word_set",
    );
    if (wordSources.length === 0) return false;
    return sources.every(
      (source) =>
        source.engine === "pdfplumber" || source.objectType === "table_grid",
    );
  });
  if (!evidenceTypesAreCoherent) return null;
  const geometrySource = geometrySources[0];
  const gridSource = gridSources[0];
  if (geometrySource === undefined || gridSource === undefined) return null;
  const rootGeometryEvidence = validatedEvidence.filter(
    (record) =>
      record.method === "embedded_grid" &&
      record.dimension === "geometry" &&
      record.sourceObjectIds.length === 1 &&
      record.sourceObjectIds[0] === geometrySource.id,
  );
  const sourceGridRootEvidence = validatedEvidence.filter(
    (record) =>
      record.method === "source_grid" &&
      record.dimension === "structure" &&
      record.sourceObjectIds.length === 1 &&
      record.sourceObjectIds[0] === gridSource.id,
  );
  const recoveredStructureRootEvidence = validatedEvidence.filter(
    (record) =>
      record.method === "recovered_structure" &&
      record.dimension === "structure",
  );
  const activeStructureEvidence = hasRecovery
    ? recoveredStructureRootEvidence[0]
    : sourceGridRootEvidence[0];
  if (
    rootGeometryEvidence.length !== 1 ||
    sourceGridRootEvidence.length !== (hasRecovery ? 0 : 1) ||
    recoveredStructureRootEvidence.length !== (hasRecovery ? 1 : 0) ||
    activeStructureEvidence === undefined ||
    !tableBboxesAreEqual(rootGeometryEvidence[0]?.bbox ?? null, tableBBox) ||
    !tableBboxesAreEqual(activeStructureEvidence.bbox, tableBBox)
  ) {
    return null;
  }

  if (!Array.isArray(item.cells) || item.cells.length < 1 || item.cells.length > 65_536) {
    return null;
  }
  const cellValues = item.cells;
  const cells = cellValues.map((entry, sourceCellIndex) => {
    if (!exactKeys(entry, cellKeys)) return null;
    const bbox = readBBox(entry.bbox);
    const confidence = readConfidence(entry.confidence_dimensions);
    const cellEvidenceIds = readOrderedHashes(entry.evidence_ids, 64);
    const cellSourceIds = readOrderedHashes(entry.source_object_ids, 64);
    if (
      !isSha256(entry.id) ||
      !isInteger(entry.row, 0, rowCount - 1) ||
      !isInteger(entry.column, 0, columnCount - 1) ||
      !isInteger(entry.row_span, 1, rowCount) ||
      !isInteger(entry.col_span, 1, columnCount) ||
      entry.row + entry.row_span > rowCount ||
      entry.column + entry.col_span > columnCount ||
      !isBoundedText(entry.text, 16_384, true, true) ||
      typeof entry.column_header !== "boolean" ||
      typeof entry.row_header !== "boolean" ||
      typeof entry.row_section !== "boolean" ||
      bbox === false ||
      (entry.source !== "native" && entry.source !== "ocr") ||
      entry.page_index !== pageIndex ||
      !cellEvidenceIds ||
      cellEvidenceIds.length === 0 ||
      !isOrderedSubset(cellEvidenceIds, evidenceIdSet) ||
      !cellSourceIds ||
      cellSourceIds.length === 0 ||
      !isOrderedSubset(cellSourceIds, sourceIdSet) ||
      !confidence ||
      !(entry.span_decision_id === null || isSha256(entry.span_decision_id))
    ) {
      return null;
    }
    return {
      id: entry.id,
      row: entry.row,
      column: entry.column,
      rowSpan: entry.row_span,
      colSpan: entry.col_span,
      text: entry.text,
      columnHeader: entry.column_header,
      rowHeader: entry.row_header,
      rowSection: entry.row_section,
      bbox,
      source: entry.source,
      pageIndex: entry.page_index,
      evidenceIds: cellEvidenceIds,
      sourceObjectIds: cellSourceIds,
      spanDecisionId: entry.span_decision_id,
      confidenceDimensions: confidence,
      sourceCellIndex,
    } as ValidatedTableCell;
  });
  const cellResults = cells;
  if (!cellResults.every(Boolean)) return null;
  const validatedCells = cellResults as ValidatedTableCell[];
  const cellById = new Map(validatedCells.map((cell) => [cell.id, cell]));
  if (cellById.size !== validatedCells.length) return null;
  const cellByCoordinate = new Map(
    validatedCells.map((cell) => [`${cell.row}:${cell.column}`, cell]),
  );
  if (cellByCoordinate.size !== validatedCells.length) return null;

  if (!Array.isArray(grid.cell_ids) || grid.cell_ids.length !== validatedCells.length) {
    return null;
  }
  const gridCellIds = grid.cell_ids;
  if (
    !gridCellIds.every((entry, index) => {
      const cell = validatedCells[index];
      return isSha256(entry) && cell !== undefined && entry === cell.id;
    })
  ) {
    return null;
  }

  if (!Array.isArray(sidecar.span_decisions) || sidecar.span_decisions.length > 65_536) {
    return null;
  }
  const spanValues = sidecar.span_decisions;
  const spanDecisions = spanValues.map((entry) => {
    if (!exactKeys(entry, spanKeys)) return null;
    const spanEvidenceIds = readOrderedHashes(entry.evidence_ids, 64);
    const spanConcerns = readOrderedConcerns(entry.concern_codes);
    const decisionCell =
      typeof entry.cell_id === "string" ? cellById.get(entry.cell_id) : undefined;
    const decisionEvidence = spanEvidenceIds?.map((id) => evidenceById.get(id));
    const decisionDimensions = decisionEvidence?.map((record) => record?.dimension);
    if (
      !isSha256(entry.id) ||
      !isSha256(entry.cell_id) ||
      decisionCell === undefined ||
      !isInteger(entry.claimed_row_span, 1, rowCount - decisionCell.row) ||
      !isInteger(entry.claimed_col_span, 1, columnCount - decisionCell.column) ||
      (entry.claimed_row_span === 1 && entry.claimed_col_span === 1) ||
      entry.emitted_row_span !== entry.claimed_row_span ||
      entry.emitted_col_span !== entry.claimed_col_span ||
      decisionCell.rowSpan !== entry.emitted_row_span ||
      decisionCell.colSpan !== entry.emitted_col_span ||
      decisionCell.spanDecisionId !== entry.id ||
      entry.outcome !== "supported" ||
      !spanEvidenceIds ||
      spanEvidenceIds.length !== 2 ||
      !isOrderedSubset(spanEvidenceIds, evidenceIdSet) ||
      decisionDimensions === undefined ||
      [...decisionDimensions].sort().join(":") !== "geometry:structure" ||
      !spanConcerns ||
      spanConcerns.length !== 0
    ) {
      return null;
    }
    return {
      id: entry.id,
      cellId: entry.cell_id,
      claimedRowSpan: entry.claimed_row_span,
      claimedColSpan: entry.claimed_col_span,
      emittedRowSpan: entry.emitted_row_span,
      emittedColSpan: entry.emitted_col_span,
      outcome: "supported",
      evidenceIds: spanEvidenceIds,
      concernCodes: spanConcerns,
    } as ValidatedSpanDecision;
  });
  const spanDecisionResults = spanDecisions;
  if (!spanDecisionResults.every(Boolean)) return null;
  const validatedSpanDecisions = spanDecisionResults as ValidatedSpanDecision[];
  const decisionById = new Map(validatedSpanDecisions.map((decision) => [decision.id, decision]));
  if (decisionById.size !== validatedSpanDecisions.length) return null;
  const decisionByCellId = new Map(
    validatedSpanDecisions.map((decision) => [decision.cellId, decision]),
  );
  if (decisionByCellId.size !== validatedSpanDecisions.length) return null;
  const decisionCells = validatedCells.filter((cell) => cell.spanDecisionId !== null);
  if (decisionCells.length !== validatedSpanDecisions.length) return null;
  if (
    !decisionCells.every((cell, index) => {
      const decision = validatedSpanDecisions[index];
      if (
        decision === undefined ||
        decision.id !== cell.spanDecisionId ||
        decision.cellId !== cell.id ||
        cellById.get(decision.cellId) !== cell ||
        decisionByCellId.get(cell.id) !== decision
      ) {
        return false;
      }
      return true;
    })
  ) {
    return null;
  }
  if (
    validatedCells.some(
      (cell) =>
        ((cell.rowSpan > 1 || cell.colSpan > 1) &&
          decisionByCellId.get(cell.id)?.id !== cell.spanDecisionId) ||
        (cell.rowSpan === 1 &&
          cell.colSpan === 1 &&
          cell.spanDecisionId !== null),
    )
  ) {
    return null;
  }

  if (
    !Array.isArray(sidecar.slots) ||
    sidecar.slots.length !== rowCount * columnCount ||
    sidecar.slots.length > 65_536
  ) {
    return null;
  }
  const slotValues = sidecar.slots;
  const slots = slotValues.map((entry) => {
    if (!exactKeys(entry, slotKeys)) return null;
    if (
      !isSha256(entry.id) ||
      !isInteger(entry.row, 0, rowCount - 1) ||
      !isInteger(entry.column, 0, columnCount - 1) ||
      (entry.kind !== "anchor" &&
        entry.kind !== "explicit_blank" &&
        entry.kind !== "covered")
    ) {
      return null;
    }
    if (entry.kind === "covered") {
      if (entry.cell_id !== null || !isSha256(entry.covered_by_cell_id)) return null;
    } else if (!isSha256(entry.cell_id) || entry.covered_by_cell_id !== null) {
      return null;
    }
    return {
      id: entry.id,
      row: entry.row,
      column: entry.column,
      kind: entry.kind,
      cellId: entry.cell_id,
      coveredByCellId: entry.covered_by_cell_id,
    } as ValidatedTableSlot;
  });
  const slotResults = slots;
  if (!slotResults.every(Boolean)) return null;
  const validatedSlots = slotResults as ValidatedTableSlot[];
  const slotIds = new Set(validatedSlots.map((slot) => slot.id));
  if (slotIds.size !== validatedSlots.length) return null;
  let cellCursor = 0;
  const coveredSlotCounts = new Map<string, number>();
  const slotsAreCoherent = validatedSlots.every((slot, slotIndex) => {
    const expectedRow = Math.floor(slotIndex / columnCount);
    const expectedColumn = slotIndex % columnCount;
    if (slot.row !== expectedRow || slot.column !== expectedColumn) return null;
    if (slot.kind === "covered") {
      const coveringCell =
        slot.coveredByCellId === null ? undefined : cellById.get(slot.coveredByCellId);
      if (
        coveringCell === undefined ||
        (coveringCell.rowSpan === 1 && coveringCell.colSpan === 1) ||
        coveringCell.row > slot.row ||
        slot.row >= coveringCell.row + coveringCell.rowSpan ||
        coveringCell.column > slot.column ||
        slot.column >= coveringCell.column + coveringCell.colSpan ||
        (slot.row === coveringCell.row && slot.column === coveringCell.column)
      ) {
        return false;
      }
      coveredSlotCounts.set(
        coveringCell.id,
        (coveredSlotCounts.get(coveringCell.id) ?? 0) + 1,
      );
    } else {
      const cell = validatedCells[cellCursor];
      if (
        cell === undefined ||
        slot.cellId !== cell.id ||
        slot.row !== cell.row ||
        slot.column !== cell.column ||
        (slot.kind === "explicit_blank" && cell.text !== "") ||
        (slot.kind === "anchor" && cell.text.length === 0)
      ) {
        return false;
      }
      cellCursor += 1;
    }
    return true;
  });
  if (!slotsAreCoherent || cellCursor !== validatedCells.length) {
    return null;
  }
  if (
    !validatedCells.every(
      (cell) =>
        (coveredSlotCounts.get(cell.id) ?? 0) ===
        cell.rowSpan * cell.colSpan - 1,
    )
  ) {
    return null;
  }

  const wordSetByTarget = new Map<string, ValidatedPdfplumberWordSetSourceObject>();
  for (const source of wordSetSources) {
    const key = `${source.role}:${source.targetRow}:${source.targetColumn}`;
    if (wordSetByTarget.has(key)) return null;
    wordSetByTarget.set(key, source);
  }
  const headerWordSets = wordSetSources.filter((source) => source.role === "header");
  const bodyControlWordSets = wordSetSources.filter(
    (source) => source.role === "body_control",
  );
  const bottomWordSets = wordSetSources.filter((source) => source.role === "bottom_row");
  const hasHeaderRecovery = headerWordSets.length > 0 || bodyControlWordSets.length > 0;
  if (
    (hasHeaderRecovery &&
      (predecessorRows < 2 ||
        headerWordSets.length !== columnCount ||
        bodyControlWordSets.length !== columnCount ||
        Array.from({ length: columnCount }, (_, column) => column).some(
          (column) =>
            !wordSetByTarget.has(`header:0:${column}`) ||
            !wordSetByTarget.has(`body_control:1:${column}`),
        ))) ||
    (bottomWordSets.length > 0 &&
      (bottomWordSets.length !== columnCount ||
        Array.from({ length: columnCount }, (_, column) => column).some(
          (column) => !wordSetByTarget.has(`bottom_row:${predecessorRows}:${column}`),
        )))
  ) {
    return null;
  }
  if (!hasHeaderRecovery && bottomWordSets.length === 0 && hasRecovery) return null;

  if (hasRecovery) {
    const recoverySourceIds = [gridSource.id, ...wordSetSources.map((source) => source.id)]
      .sort();
    if (
      activeStructureEvidence.sourceObjectIds.length !== recoverySourceIds.length ||
      activeStructureEvidence.sourceObjectIds.some(
        (sourceId, index) => sourceId !== recoverySourceIds[index],
      )
    ) {
      return null;
    }

    let rowPitchJson = "null";
    let sameLineBandJson = "null";
    let columnStartsJson = "null";
    const bottomAssignments: Array<{
      column: number;
      word: ValidatedTableWord;
    }> = [];
    const emittedBottomCoordinates: string[] = [];
    if (bottomWordSets.length > 0) {
      const previousFirst = cellByCoordinate.get(`${predecessorRows - 2}:0`);
      const lastFirst = cellByCoordinate.get(`${predecessorRows - 1}:0`);
      if (
        previousFirst?.bbox === null ||
        previousFirst?.bbox === undefined ||
        lastFirst?.bbox === null ||
        lastFirst?.bbox === undefined
      ) {
        return null;
      }
      const numericRowPitch = lastFirst.bbox.y - previousFirst.bbox.y;
      const rowPitch = pythonFloatJson(numericRowPitch);
      if (numericRowPitch < 4 || numericRowPitch > 64) return null;
      if (rowPitch === null) return null;
      rowPitchJson = rowPitch;
      const columnStarts: string[] = [];
      let previousColumnStart: number | null = null;
      for (let column = 0; column < columnCount; column += 1) {
        const predecessorCell = cellByCoordinate.get(
          `${predecessorRows - 1}:${column}`,
        );
        const bottomCell = cellByCoordinate.get(`${predecessorRows}:${column}`);
        const bottomSource = wordSetByTarget.get(
          `bottom_row:${predecessorRows}:${column}`,
        );
        if (
          predecessorCell?.bbox === null ||
          predecessorCell?.bbox === undefined ||
          bottomCell?.bbox === null ||
          bottomCell?.bbox === undefined ||
          bottomSource === undefined
        ) {
          return null;
        }
        const start = pythonFloatJson(predecessorCell.bbox.x);
        const bottomBBox = canonicalPdfWordBBox(bottomCell.bbox);
        if (
          start === null ||
          bottomBBox === null ||
          (previousColumnStart !== null && predecessorCell.bbox.x <= previousColumnStart)
        ) {
          return null;
        }
        previousColumnStart = predecessorCell.bbox.x;
        columnStarts.push(start);
        emittedBottomCoordinates.push(
          `[${bottomCell.row},${bottomCell.column},${bottomBBox},${JSON.stringify(bottomCell.text)}]`,
        );
        for (const word of bottomSource.words) {
          bottomAssignments.push({ column, word });
        }
      }
      columnStartsJson = `[${columnStarts.join(",")}]`;
      bottomAssignments.sort((left, right) => {
        const leftGeometry = [
          left.word.bbox.y,
          left.word.bbox.x,
          left.word.bbox.height,
          left.word.bbox.width,
        ];
        const rightGeometry = [
          right.word.bbox.y,
          right.word.bbox.x,
          right.word.bbox.height,
          right.word.bbox.width,
        ];
        for (let index = 0; index < leftGeometry.length; index += 1) {
          const difference = (leftGeometry[index] ?? 0) - (rightGeometry[index] ?? 0);
          if (difference !== 0) return difference;
        }
        return 0;
      });
      const top = Math.min(...bottomAssignments.map(({ word }) => word.bbox.y));
      const bottom = Math.max(
        ...bottomAssignments.map(({ word }) => word.bbox.y + word.bbox.height),
      );
      if (
        bottomAssignments.some(
          ({ word }) =>
            Math.abs(word.bbox.y - top) > 1 ||
            Math.abs(word.bbox.y + word.bbox.height - bottom) > 1,
        )
      ) {
        return null;
      }
      const topJson = pythonFloatJson(top);
      const bottomJson = pythonFloatJson(bottom);
      if (topJson === null || bottomJson === null) return null;
      sameLineBandJson = `{"bottom":${bottomJson},"tolerance":1.0,"top":${topJson}}`;
    }
    const bottomAssignmentsJson = `[${bottomAssignments
      .map(({ column, word }) => {
        const wordBBox = canonicalPdfWordBBox(word.bbox);
        return wordBBox === null
          ? "null"
          : `[${JSON.stringify(word.id)},${column},${wordBBox}]`;
      })
      .join(",")}]`;
    if (bottomAssignmentsJson.includes("null")) return null;
    const emittedHeaderCoordinates = Array.from(
      { length: hasHeaderRecovery ? columnCount : 0 },
      (_, column) => `[0,${column},"column_header"]`,
    );
    const emittedCoordinatesJson = `[${[
      ...emittedHeaderCoordinates,
      ...emittedBottomCoordinates,
    ].join(",")}]`;
    const contentSha256 = textSha256(
      `["p04-recovered-table-structure-content-v1","p04-table-recovery-rule-v1",${JSON.stringify(gridSource.id)},[${predecessorRows},${columnCount}],${rowPitchJson},${sameLineBandJson},${columnStartsJson},${bottomAssignmentsJson},${emittedCoordinatesJson},${canonicalStringArray(recoverySourceIds)}]`,
    );
    const evidenceId = textSha256(
      `["p04-recovered-table-structure-evidence-id-v1",${JSON.stringify(context.sourceSha256)},${context.pageIndex},${JSON.stringify(tableReference)},${predecessorRows},${columnCount},${canonicalStringArray(recoverySourceIds)},${JSON.stringify(contentSha256)}]`,
    );
    if (
      activeStructureEvidence.contentSha256 !== contentSha256 ||
      activeStructureEvidence.id !== evidenceId
    ) {
      return null;
    }
  }

  const normalizeRecoveredWords = (source: ValidatedPdfplumberWordSetSourceObject): string =>
    source.words.map((word) => word.text).join(" ");
  const exactDoclingBBoxByCellId = new Map<string, string>();
  const cellEvidenceIsCoherent = validatedCells.every((cell) => {
    if (cell.sourceObjectIds.length !== 1) return false;
    const cellSource = sourceById.get(cell.sourceObjectIds[0] ?? "");
    if (cellSource === undefined) return false;
    const textEvidence: ValidatedEvidence[] = [];
    const geometryEvidence: ValidatedEvidence[] = [];
    const structureEvidence: ValidatedEvidence[] = [];
    const headerEvidence: ValidatedEvidence[] = [];
    for (const evidenceId of cell.evidenceIds) {
      const record = evidenceById.get(evidenceId);
      if (record === undefined) return false;
      if (record.dimension === "text") textEvidence.push(record);
      else if (record.dimension === "geometry") geometryEvidence.push(record);
      else if (record.dimension === "structure") structureEvidence.push(record);
      else headerEvidence.push(record);
    }
    const hasSpan = cell.rowSpan > 1 || cell.colSpan > 1;
    const hasHeader = cell.columnHeader || cell.rowHeader;
    const hasRecoveredHeader =
      headerEvidence.length === 1 &&
      headerEvidence[0]?.method === "recovered_structure";
    if (
      textEvidence.length !== 1 ||
      headerEvidence.length !== (hasHeader ? 1 : 0) ||
      cell.confidenceDimensions.text !== 1 ||
      cell.confidenceDimensions.geometry !== (cell.bbox === null ? null : 1) ||
      cell.confidenceDimensions.structure !== 1 ||
      cell.confidenceDimensions.header !== (hasHeader ? 1 : null)
    ) {
      return false;
    }

    const textRecord = textEvidence[0];
    if (
      textRecord === undefined ||
      !tableBboxesAreEqual(textRecord.bbox, cell.bbox) ||
      textRecord.sourceObjectIds.length !== 1 ||
      textRecord.sourceObjectIds[0] !== cellSource.id
    ) {
      return false;
    }

    if (cellSource.engine === "docling") {
      const originalColumnHeader = hasRecoveredHeader
        ? false
        : cell.columnHeader;
      let expectedFacts: ExpectedDoclingCellFacts | undefined;
      for (const facts of expectedDoclingCellFacts(
        context,
        cellSource.rawRef,
        cell,
        originalColumnHeader,
        hasSpan,
      )) {
        if (
          cellSource.contentSha256 === facts.contentSha256 &&
          cell.id === facts.cellId &&
          cellSource.id === facts.sourceId &&
          textRecord.id === facts.textEvidenceId
        ) {
          expectedFacts = facts;
          break;
        }
      }
      if (
        cellSource.objectType !== "table_cell" ||
        expectedFacts === undefined ||
        textRecord.method !==
          (cell.source === "native" ? "native_text" : "ocr_text") ||
        textRecord.contentSha256 !== cellSource.contentSha256 ||
        geometryEvidence.length !== (hasSpan ? 1 : 0) ||
        structureEvidence.length !== (hasSpan || hasRecoveredHeader ? 1 : 0)
      ) {
        return false;
      }
      exactDoclingBBoxByCellId.set(cell.id, expectedFacts.bboxJson);
      if (
        structureEvidence.length === 1 &&
        structureEvidence[0]?.id !== activeStructureEvidence.id
      ) {
        return false;
      }
      if (hasSpan) {
        const geometryRecord = geometryEvidence[0];
        const structureRecord = structureEvidence[0];
        const expectedGeometryId = expectedFacts.geometryEvidenceId;
        const expectedDecisionId = expectedFacts.decisionId;
        if (expectedGeometryId === null || expectedDecisionId === null) {
          return false;
        }
        const decision =
          cell.spanDecisionId === null
            ? undefined
            : decisionById.get(cell.spanDecisionId);
        const expectedDecisionEvidenceIds = [
          expectedGeometryId,
          activeStructureEvidence.id,
        ].sort();
        if (
          geometryRecord === undefined ||
          geometryRecord.id !== expectedGeometryId ||
          geometryRecord.method !== "embedded_grid" ||
          geometryRecord.sourceObjectIds.length !== 1 ||
          geometryRecord.sourceObjectIds[0] !== cellSource.id ||
          geometryRecord.contentSha256 !== cellSource.contentSha256 ||
          !tableBboxesAreEqual(geometryRecord.bbox, cell.bbox) ||
          structureRecord === undefined ||
          structureRecord.id !== activeStructureEvidence.id ||
          cell.spanDecisionId !== expectedDecisionId ||
          decision === undefined ||
          decision.id !== expectedDecisionId ||
          decision.evidenceIds.length !== expectedDecisionEvidenceIds.length ||
          decision.evidenceIds.some(
            (evidenceId, index) => evidenceId !== expectedDecisionEvidenceIds[index],
          )
        ) {
          return false;
        }
      }
      if (hasHeader) {
        const headerRecord = headerEvidence[0];
        if (headerRecord === undefined) return false;
        if (headerRecord.method === "model_structure") {
          if (
            headerRecord.sourceObjectIds.length !== 1 ||
            headerRecord.sourceObjectIds[0] !== gridSource.id ||
            !tableBboxesAreEqual(headerRecord.bbox, tableBBox)
          ) {
            return false;
          }
        } else if (
          headerRecord.method === "recovered_structure" &&
          cell.columnHeader &&
          cell.row === 0
        ) {
          const headerSet = wordSetByTarget.get(
            `header:0:${cell.column}`,
          );
          const controlSet = wordSetByTarget.get(
            `body_control:1:${cell.column}`,
          );
          const bodyCell = cellByCoordinate.get(`1:${cell.column}`);
          const wordsFitCell = (
            source: ValidatedPdfplumberWordSetSourceObject,
            target: ValidatedTableBBox,
          ): boolean =>
            source.words.every((word) => {
              const centerX = word.bbox.x + word.bbox.width / 2;
              const centerY = word.bbox.y + word.bbox.height / 2;
              return (
                target.x - 1 <= centerX &&
                centerX <= target.x + target.width + 1 &&
                target.y - 1 <= centerY &&
                centerY <= target.y + target.height + 1
              );
            });
          if (
            headerSet === undefined ||
            controlSet === undefined ||
            bodyCell?.bbox === null ||
            bodyCell?.bbox === undefined ||
            cell.bbox === null ||
            headerSet.words.some((word) => !word.bold) ||
            controlSet.words.some((word) => word.bold) ||
            !wordsFitCell(headerSet, cell.bbox) ||
            !wordsFitCell(controlSet, bodyCell.bbox) ||
            normalizeRecoveredWords(headerSet) !== cell.text ||
            !tableBboxesAreEqual(headerRecord.bbox, cell.bbox) ||
            !expectedRecoveredHeaderEvidence(
              context,
              tableReference,
              predecessorRows,
              columnCount,
              cell.column,
              gridSource.id,
              headerSet,
              controlSet,
              cell.bbox,
              headerRecord,
            )
          ) {
            return false;
          }
          if (
            normalizeRecoveredWords(controlSet) !== bodyCell.text
          ) {
            return false;
          }
        } else {
          return false;
        }
      }
      return true;
    }

    if (
      cellSource.role !== "bottom_row" ||
      cellSource.targetRow !== cell.row ||
      cellSource.targetColumn !== cell.column ||
      cell.source !== "native" ||
      normalizeRecoveredWords(cellSource) !== cell.text ||
      textRecord.method !== "native_text" ||
      geometryEvidence.length !== 1 ||
      structureEvidence.length !== 1 ||
      headerEvidence.length !== 0 ||
      cell.bbox === null ||
      cell.id !==
        expectedRecoveredBottomIdentity(
          "p04-recovered-cell-id-v1",
          context,
          tableReference,
          predecessorRows,
          columnCount,
          cellSource.id,
          cell.bbox,
          cell.row,
          cell.column,
        ) ||
      textRecord.id !==
        expectedRecoveredBottomIdentity(
          "p04-recovered-text-evidence-id-v1",
          context,
          tableReference,
          predecessorRows,
          columnCount,
          cellSource.id,
          cell.bbox,
          cell.row,
          cell.column,
        ) ||
      textRecord.contentSha256 !== cellSource.contentSha256
    ) {
      return false;
    }
    const geometryRecord = geometryEvidence[0];
    const structureRecord = structureEvidence[0];
    if (
      geometryRecord === undefined ||
      geometryRecord.method !== "recovered_structure" ||
      geometryRecord.sourceObjectIds.length !== 1 ||
      geometryRecord.sourceObjectIds[0] !== cellSource.id ||
      !tableBboxesAreEqual(geometryRecord.bbox, cell.bbox) ||
      geometryRecord.id !==
        expectedRecoveredBottomIdentity(
          "p04-recovered-geometry-evidence-id-v1",
          context,
          tableReference,
          predecessorRows,
          columnCount,
          cellSource.id,
          cell.bbox,
          cell.row,
          cell.column,
        ) ||
      geometryRecord.contentSha256 !== cellSource.contentSha256 ||
      structureRecord === undefined ||
      structureRecord.id !== activeStructureEvidence.id
    ) {
      return false;
    }
    const wordLeft = Math.min(...cellSource.words.map((word) => word.bbox.x));
    const wordTop = Math.min(...cellSource.words.map((word) => word.bbox.y));
    const wordRight = Math.max(
      ...cellSource.words.map((word) => word.bbox.x + word.bbox.width),
    );
    const wordBottom = Math.max(
      ...cellSource.words.map((word) => word.bbox.y + word.bbox.height),
    );
    return tableBboxesAreEqual(cell.bbox, {
      x: wordLeft,
      y: wordTop,
      width: wordRight - wordLeft,
      height: wordBottom - wordTop,
      unit: "pt",
    });
  });
  if (!cellEvidenceIsCoherent) return null;

  const expectedGridSourceId = textSha256(
    `["p04-structure-source-id-v1",${JSON.stringify(context.sourceSha256)},${pageIndex},"docling",${JSON.stringify(tableReference)},${predecessorRows},${columnCount}]`,
  );
  let exactTableIdentity:
    | {
        geometryContentSha256: string | null;
        geometrySourceId: string | null;
        geometryEvidenceId: string | null;
        tableId: string | null;
        candidateId: string | null;
      }
    | undefined;
  for (const bboxJson of canonicalDoclingBBoxCandidates(tableBBox)) {
    const identity = {
      geometryContentSha256: textSha256(
        `["p04-geometry-source-content-v1",${bboxJson},${pageIndex}]`,
      ),
      geometrySourceId: textSha256(
        `["p04-geometry-source-id-v1",${JSON.stringify(context.sourceSha256)},${pageIndex},"docling",${JSON.stringify(tableReference)},${bboxJson}]`,
      ),
      geometryEvidenceId: textSha256(
        `["p04-geometry-evidence-id-v1",${JSON.stringify(context.sourceSha256)},${pageIndex},"docling",${JSON.stringify(tableReference)},${bboxJson}]`,
      ),
      tableId: textSha256(
        `["p04-table-id-v1",${JSON.stringify(context.sourceSha256)},${pageIndex},"docling",${JSON.stringify(tableReference)},${bboxJson},${rowCount},${columnCount}]`,
      ),
      candidateId: textSha256(
        `["p04-candidate-id-v1",${JSON.stringify(context.sourceSha256)},${pageIndex},"docling",${JSON.stringify(tableReference)},${bboxJson},${predecessorRows},${columnCount}]`,
      ),
    };
    if (
        sidecar.table_id === identity.tableId &&
        sidecar.candidate_id === identity.candidateId &&
        geometrySource.id === identity.geometrySourceId &&
        geometrySource.contentSha256 === identity.geometryContentSha256 &&
        rootGeometryEvidence[0]?.id === identity.geometryEvidenceId &&
        rootGeometryEvidence[0]?.contentSha256 ===
          identity.geometryContentSha256
    ) {
      exactTableIdentity = identity;
      break;
    }
  }
  if (exactTableIdentity === undefined || gridSource.id !== expectedGridSourceId) {
    return null;
  }
  const expectedTableId = exactTableIdentity.tableId;
  const expectedCandidateId = exactTableIdentity.candidateId;

  const normalizedDoclingCells: string[] = [];
  const observedDirectReferences = new Set<string>();
  for (const cell of validatedCells) {
    const sourceId = cell.sourceObjectIds[0];
    const source = sourceId === undefined ? undefined : sourceById.get(sourceId);
    if (source?.engine !== "docling" || source.objectType !== "table_cell") continue;
    if (cell.row >= predecessorRows) return null;
    if (source.rawRef !== tableReference) {
      if (observedDirectReferences.has(source.rawRef)) return null;
      observedDirectReferences.add(source.rawRef);
    }
    const canonicalCellBBox = exactDoclingBBoxByCellId.get(cell.id);
    if (canonicalCellBBox === undefined) return null;
    const originalColumnHeader =
      hasHeaderRecovery && cell.row === 0 ? false : cell.columnHeader;
    normalizedDoclingCells.push(
      `[${cell.row},${cell.column},${cell.rowSpan},${cell.colSpan},${JSON.stringify(cell.text)},${originalColumnHeader ? "true" : "false"},${cell.rowHeader ? "true" : "false"},${cell.rowSection ? "true" : "false"},${canonicalCellBBox},${JSON.stringify(source.rawRef)}]`,
    );
  }
  const expectedGridContentSha256 = textSha256(
    `["p04-structure-source-content-v1",${JSON.stringify(tableReference)},${predecessorRows},${columnCount},[${normalizedDoclingCells.join(",")}]]`,
  );
  if (gridSource.contentSha256 !== expectedGridContentSha256) return null;

  if (!hasRecovery) {
    const expectedStructureEvidenceId = textSha256(
      `["p04-structure-evidence-id-v1",${JSON.stringify(context.sourceSha256)},${pageIndex},"docling",${JSON.stringify(tableReference)},${rowCount},${columnCount}]`,
    );
    if (
      activeStructureEvidence.id !== expectedStructureEvidenceId ||
      activeStructureEvidence.contentSha256 !== expectedGridContentSha256
    ) {
      return null;
    }
  }

  const modelHeaderEvidence = validatedEvidence.filter(
    (record) => record.method === "model_structure" && record.dimension === "header",
  );
  const hasNativeHeader = validatedCells.some(
    (cell) => {
      if (!cell.columnHeader && !cell.rowHeader) return false;
      return !cell.evidenceIds.some((evidenceId) => {
        const record = evidenceById.get(evidenceId);
        return (
          record?.dimension === "header" &&
          record.method === "recovered_structure"
        );
      });
    },
  );
  if (modelHeaderEvidence.length !== (hasNativeHeader ? 1 : 0)) return null;
  if (hasNativeHeader) {
    const expectedHeaderEvidenceId = textSha256(
      `["p04-header-evidence-id-v1",${JSON.stringify(context.sourceSha256)},${pageIndex},"docling",${JSON.stringify(tableReference)},${rowCount},${columnCount}]`,
    );
    const headerRecord = modelHeaderEvidence[0];
    if (
      headerRecord?.id !== expectedHeaderEvidenceId ||
      headerRecord.contentSha256 !== expectedGridContentSha256
    ) {
      return null;
    }
  }

  for (const slot of validatedSlots) {
    const expectedSlotId = textSha256(
      `["p04-slot-id-v1",${JSON.stringify(context.sourceSha256)},${pageIndex},${JSON.stringify(expectedTableId)},${JSON.stringify(expectedCandidateId)},${slot.row},${slot.column}]`,
    );
    if (slot.id !== expectedSlotId) return null;
  }

  const cellSourceUseCount = new Map<string, number>();
  for (const cell of validatedCells) {
    const sourceId = cell.sourceObjectIds[0];
    if (sourceId === undefined) return null;
    cellSourceUseCount.set(sourceId, (cellSourceUseCount.get(sourceId) ?? 0) + 1);
  }
  if (
    validatedSourceObjects.some((source) => {
      const useCount = cellSourceUseCount.get(source.id) ?? 0;
      if (source.engine === "docling" && source.objectType === "table_cell") {
        return useCount !== 1;
      }
      if (source.engine === "pdfplumber" && source.role === "bottom_row") {
        return useCount !== 1;
      }
      return useCount !== 0;
    })
  ) {
    return null;
  }

  const reachableEvidenceIds = new Set<string>([
    rootGeometryEvidence[0]?.id ?? "",
    activeStructureEvidence.id,
  ]);
  for (const cell of validatedCells) {
    for (const evidenceId of cell.evidenceIds) reachableEvidenceIds.add(evidenceId);
  }
  for (const decision of validatedSpanDecisions) {
    for (const evidenceId of decision.evidenceIds) {
      reachableEvidenceIds.add(evidenceId);
    }
  }
  reachableEvidenceIds.delete("");
  if (
    reachableEvidenceIds.size !== evidenceIdSet.size ||
    evidenceIds.some((id) => !reachableEvidenceIds.has(id))
  ) {
    return null;
  }
  const reachableSourceIds = new Set<string>();
  for (const cell of validatedCells) {
    for (const sourceId of cell.sourceObjectIds) reachableSourceIds.add(sourceId);
  }
  for (const evidenceId of reachableEvidenceIds) {
    const evidenceRecord = evidenceById.get(evidenceId);
    if (evidenceRecord === undefined) return null;
    for (const sourceId of evidenceRecord.sourceObjectIds) {
      reachableSourceIds.add(sourceId);
    }
  }
  if (
    reachableSourceIds.size !== sourceIdSet.size ||
    sourceIds.some((id) => !reachableSourceIds.has(id))
  ) {
    return null;
  }

  if (!exactKeys(sidecar.representation_custody, custodyKeys)) return null;
  const custody = sidecar.representation_custody;
  if (!Array.isArray(custody.grid_shape) || custody.grid_shape.length !== 2) {
    return null;
  }
  const custodyGridShape = custody.grid_shape;
  if (
    custody.serializer_policy_id !== "p04-table-grid-serializer-v1" ||
    !custodyGridShape.every(
      (entry, index) => entry === (index === 0 ? rowCount : columnCount),
    ) ||
    !isSha256(custody.cells_sha256) ||
    !isSha256(custody.rows_sha256) ||
    !isSha256(custody.html_sha256) ||
    !isSha256(custody.markdown_sha256) ||
    !isSha256(custody.csv_sha256)
  ) {
    return null;
  }

  const readMatrix = (
    value: unknown,
  ): unknown[] | null => {
    if (!Array.isArray(value) || value.length !== rowCount) return null;
    const sourceMatrixRows = value;
    const matrix = sourceMatrixRows.map((row) => {
      if (!Array.isArray(row) || row.length !== columnCount) return null;
      const sourceMatrixValues = row;
      if (!sourceMatrixValues.every((entry) => isBoundedText(entry, 16_384, true, true))) {
        return null;
      }
      const matrixTextValues = sourceMatrixValues.filter((entry): entry is string => typeof entry === "string");
      return matrixTextValues;
    });
    const matrixResults = matrix;
    if (!matrixResults.every(Boolean)) return null;
    const validatedMatrix = matrixResults.filter(Boolean);
    return validatedMatrix;
  };

  const rows = readMatrix(item.rows);
  const valueRows = readMatrix(item.value);
  if (!rows || !valueRows || item.row_count !== rowCount || item.column_count !== columnCount) {
    return null;
  }
  if (
    !isBoundedText(item.html, 8_388_608, true, true) ||
    !isBoundedText(item.md, 8_388_608, true, true) ||
    !isBoundedText(item.csv, 8_388_608, true, true)
  ) {
    return null;
  }
  const replayed = replayTableGrid(
    validatedCells,
    validatedSlots,
    rowCount,
    columnCount,
  );
  if (
    replayed === null ||
    !matricesAreEqual(rows as string[][], replayed.rows) ||
    !matricesAreEqual(valueRows as string[][], replayed.rows) ||
    item.html !== replayed.html ||
    item.md !== replayed.html ||
    item.csv !== replayed.csv
  ) {
    return null;
  }
  const htmlSha256 = textSha256(item.html);
  if (
    custodySha256(item.cells) !== custody.cells_sha256 ||
    custodySha256(item.rows) !== custody.rows_sha256 ||
    htmlSha256 !== custody.html_sha256 ||
    htmlSha256 !== custody.markdown_sha256 ||
    textSha256(item.csv) !== custody.csv_sha256
  ) {
    return null;
  }

  if (
    validatedCells.some((cell) => cell.bbox === null) &&
    !validatedConcerns.includes("table_source_cell_bbox_unresolved")
  ) {
    return null;
  }
  if (
    validatedCells.some((cell) => {
      if (!cell.columnHeader && !cell.rowHeader) return false;
      if (cell.confidenceDimensions.header === null) return true;
      return !cell.evidenceIds.some(
        (id) => evidenceById.get(id)?.dimension === "header",
      );
    })
  ) {
    return null;
  }

  return {
    policyId: "p04-table-evidence-v1",
    version: "1.1",
    tableId: sidecar.table_id,
    candidateId: sidecar.candidate_id,
    pageIndex,
    rowCount,
    columnCount,
    headerRowCount: replayed.headerRowCount,
    rows: replayed.renderedRows,
    cells: validatedCells,
    slots: validatedSlots,
    sourceObjects: validatedSourceObjects,
    evidence: validatedEvidence,
    spanDecisions: validatedSpanDecisions,
    representationCustody: {
      serializerPolicyId: "p04-table-grid-serializer-v1",
      gridShape: [rowCount, columnCount],
      cellsSha256: custody.cells_sha256,
      rowsSha256: custody.rows_sha256,
      htmlSha256: custody.html_sha256,
      markdownSha256: custody.markdown_sha256,
      csvSha256: custody.csv_sha256,
    },
    concerns: validatedConcerns,
  };
}
