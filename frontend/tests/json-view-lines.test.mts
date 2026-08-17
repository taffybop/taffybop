import assert from "node:assert/strict";
import { test } from "node:test";

import {
  findJsonFoldRanges,
  findTopLevelJsonFieldLine,
} from "../lib/json-view-lines.ts";

const sample = `{
  "text": {
    "pages": [
      {
        "value": "brackets in a string: { [ ] }"
      }
    ]
  },
  "metadata": {
    "text": "nested key must not be selected"
  }
}`;

test("JSON fold ranges ignore brackets inside strings", () => {
  const ranges = findJsonFoldRanges(sample);

  assert.equal(ranges.get(0), 11);
  assert.equal(ranges.get(1), 7);
  assert.equal(ranges.get(2), 6);
  assert.equal(ranges.get(3), 5);
  assert.equal(ranges.get(8), 10);
});

test("top-level field navigation does not match nested keys", () => {
  assert.equal(findTopLevelJsonFieldLine(sample, "text"), 1);
  assert.equal(findTopLevelJsonFieldLine(sample, "metadata"), 8);
  assert.equal(findTopLevelJsonFieldLine(sample, "missing"), -1);
});

