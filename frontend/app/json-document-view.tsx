"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import {
  type KeyboardEvent,
  type ReactNode,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  findJsonFoldRanges,
  findTopLevelJsonFieldLine,
} from "@/lib/json-view-lines";

export interface JsonSummaryRow {
  field: string;
  data: string;
  type: string;
}

interface VisibleJsonLine {
  index: number;
  text: string;
  collapsedEnd?: number;
}

function highlightJson(value: string): ReactNode[] {
  const tokenPattern =
    /("(?:\\.|[^"\\])*"\s*:)|("(?:\\.|[^"\\])*")|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;
  const tokens: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = tokenPattern.exec(value)) !== null) {
    if (match.index > cursor) tokens.push(value.slice(cursor, match.index));
    const className = match[1]
      ? "syntax-key"
      : match[2]
        ? "syntax-string"
        : match[3]
          ? "syntax-literal"
          : "syntax-number";
    tokens.push(
      <span className={className} key={`${match.index}-${className}`}>
        {match[0]}
      </span>,
    );
    cursor = tokenPattern.lastIndex;
  }

  if (cursor < value.length) tokens.push(value.slice(cursor));
  return tokens;
}

export function DocumentJsonView({
  value,
  summary,
  wrap,
}: {
  value: string;
  summary: JsonSummaryRow[];
  wrap: boolean;
}) {
  const lines = useMemo(() => value.split("\n"), [value]);
  const foldRanges = useMemo(() => findJsonFoldRanges(value), [value]);
  const [collapsed, setCollapsed] = useState<Set<number>>(() => new Set());
  const lineRefs = useRef(new Map<number, HTMLDivElement>());

  const visibleLines = useMemo(() => {
    const visible: VisibleJsonLine[] = [];
    let index = 0;

    while (index < lines.length) {
      const endLine = collapsed.has(index) ? foldRanges.get(index) : undefined;
      visible.push({
        index,
        text: lines[index],
        collapsedEnd: endLine,
      });
      index = endLine === undefined ? index + 1 : endLine + 1;
    }

    return visible;
  }, [collapsed, foldRanges, lines]);

  const toggleFold = (line: number) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(line)) next.delete(line);
      else next.add(line);
      return next;
    });
  };

  const scrollToField = (field: string) => {
    const targetLine = findTopLevelJsonFieldLine(value, field);
    if (targetLine < 0) return;

    setCollapsed((current) => {
      const next = new Set(current);
      for (const startLine of current) {
        const endLine = foldRanges.get(startLine);
        if (
          endLine !== undefined &&
          startLine < targetLine &&
          targetLine <= endLine
        ) {
          next.delete(startLine);
        }
      }
      return next;
    });

    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        const target = lineRefs.current.get(targetLine);
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
        target?.focus({ preventScroll: true });
      });
    });
  };

  const collapseTopLevelSections = () => {
    const next = new Set<number>();
    for (const row of summary) {
      const line = findTopLevelJsonFieldLine(value, row.field);
      if (line >= 0 && foldRanges.has(line)) next.add(line);
    }
    setCollapsed(next);
  };

  const activateSummaryRow = (
    event: KeyboardEvent<HTMLTableRowElement>,
    field: string,
  ) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    scrollToField(field);
  };

  return (
    <div className="document-json-view">
      <section className="json-summary-shell" aria-labelledby="json-summary-title">
        <div className="json-summary-heading">
          <span id="json-summary-title">Document JSON structure</span>
          <small>Select a row to jump to its raw JSON section.</small>
        </div>
        <div className="json-summary-scroll">
          <table className="json-summary-table">
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Data</th>
                <th scope="col">Type</th>
              </tr>
            </thead>
            <tbody>
              {summary.map((row) => (
                <tr
                  key={row.field}
                  tabIndex={0}
                  onClick={() => scrollToField(row.field)}
                  onKeyDown={(event) => activateSummaryRow(event, row.field)}
                  title={`Jump to ${row.field}`}
                >
                  <th scope="row">
                    <code>{row.field}</code>
                  </th>
                  <td>{row.data}</td>
                  <td>
                    <code>{row.type}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="json-raw-shell" aria-labelledby="raw-json-title">
        <div className="json-raw-heading">
          <span id="raw-json-title">Raw JSON</span>
          <div>
            <button type="button" onClick={collapseTopLevelSections}>
              Collapse sections
            </button>
            <button
              type="button"
              disabled={collapsed.size === 0}
              onClick={() => setCollapsed(new Set())}
            >
              Expand all
            </button>
          </div>
        </div>
        <div
          className={`json-code-view ${wrap ? "wrap" : ""}`}
          role="region"
          aria-label="Complete document JSON"
          tabIndex={0}
        >
          <code>
            {visibleLines.map((line) => {
              const foldEnd = foldRanges.get(line.index);
              const isCollapsed = line.collapsedEnd !== undefined;
              const closing =
                isCollapsed && line.collapsedEnd !== undefined
                  ? lines[line.collapsedEnd].trim()
                  : "";
              return (
                <div
                  className="json-code-line"
                  key={line.index}
                  ref={(node) => {
                    if (node) lineRefs.current.set(line.index, node);
                    else lineRefs.current.delete(line.index);
                  }}
                  tabIndex={-1}
                >
                  <span className="json-line-number" aria-hidden="true">
                    {line.index + 1}
                  </span>
                  <span className="json-fold-gutter">
                    {foldEnd !== undefined ? (
                      <button
                        type="button"
                        aria-label={`${isCollapsed ? "Expand" : "Collapse"} JSON at line ${
                          line.index + 1
                        }`}
                        aria-expanded={!isCollapsed}
                        onClick={() => toggleFold(line.index)}
                      >
                        {isCollapsed ? (
                          <ChevronRight aria-hidden="true" size={13} />
                        ) : (
                          <ChevronDown aria-hidden="true" size={13} />
                        )}
                      </button>
                    ) : null}
                  </span>
                  <span className="json-line-content">
                    {highlightJson(line.text)}
                    {isCollapsed ? (
                      <span className="json-fold-placeholder">
                        {" "}
                        … {line.collapsedEnd! - line.index - 1} lines … {closing}
                      </span>
                    ) : null}
                  </span>
                </div>
              );
            })}
          </code>
        </div>
      </section>
    </div>
  );
}
