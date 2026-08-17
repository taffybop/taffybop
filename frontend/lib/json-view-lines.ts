export interface JsonFoldRange {
  startLine: number;
  endLine: number;
}

interface OpenToken {
  character: "{" | "[";
  line: number;
}

/**
 * Finds multi-line object and array ranges in valid JSON without treating
 * bracket characters inside JSON strings as structure.
 */
export function findJsonFoldRanges(value: string): Map<number, number> {
  const ranges = new Map<number, number>();
  const stack: OpenToken[] = [];
  let line = 0;
  let inString = false;
  let escaped = false;

  for (const character of value) {
    if (character === "\n") {
      line += 1;
      escaped = false;
      continue;
    }

    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === '"') {
        inString = false;
      }
      continue;
    }

    if (character === '"') {
      inString = true;
      continue;
    }

    if (character === "{" || character === "[") {
      stack.push({ character, line });
      continue;
    }

    if (character !== "}" && character !== "]") continue;

    const expected = character === "}" ? "{" : "[";
    const opened = stack.at(-1);
    if (!opened || opened.character !== expected) continue;
    stack.pop();
    if (opened.line < line) ranges.set(opened.line, line);
  }

  return ranges;
}

export function findTopLevelJsonFieldLine(
  value: string,
  field: string,
): number {
  const marker = `  ${JSON.stringify(field)}:`;
  return value
    .split("\n")
    .findIndex((line) => line.startsWith(marker));
}

