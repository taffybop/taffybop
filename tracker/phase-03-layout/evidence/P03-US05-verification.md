# P03-US05 Verification Evidence

Date: 2026-07-31  
Status: Pass

## Scope and compatibility

- `PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED` defaults off and requires shared
  normalization, canonical serialization, and P03-US04 relationship order.
- Flag off performs zero US05 extractor calls and restores the exact P03-US04
  public, canonical, Markdown, and internal serialized-IR predecessor.
- Empty `text_rules`, `text_runs`, and per-element `text_run_ids` remain typed
  internally but are absent from predecessor serialization. All 15 sealed
  Phase 01 canonical IR hashes and sizes match exactly.
- Flag on adds self-contained item fields and typed internal records. Public
  ParseResult and strict canonical-presentation schemas stay at `1.0`;
  source-visible item values and canonical text remain authoritative.
- The frontend accepts only exact validated overlays, recomputes scalar
  redline Markdown, renders safe nodes, and never geometry-sorts or infers
  change state.

## Exact reviewed result

| Case / control | Expected result | Retained result |
|---|---:|---:|
| Purchase sparse runs / rules | 28 / 13 | 28 / 13 |
| Expert omission repairs | 3/3 | 3/3 |
| Deleted logical groups | 6/6 | 6/6 |
| Unique group/rule edges | 7/7 | 7/7 |
| Deleted run/rule links | 9/9 | 9/9 |
| Blue runs / underline links | 2/2 / 4/4 | 2/2 / 4/4 |
| PDF insertion/replacement inference | 0 | 0 |
| False deletion controls | 0 | 0 |
| Postal italic cell targets | 20, 21, 66, 67 | exact |
| Finance bold runs / deleted | 26 / 0 | 26 / 0 |
| Purchase source composition | 7/7 | 7/7 |
| P03-US04 order | 41/41 | 41/41 |

Every scored run retains an allowlisted target path, exact target digest and
half-open code-point slice, source text and character indexes, page-space
bbox, font/size/bold/italic/color, orthogonal state/decorations/placeholder,
raw rule links, method, derivation, and deterministic order. Active text omits
only proven deletions and names every omitted run ID.

## Failure, security, and resource behavior

- Quote matching is strict, with the single policy-authorized source-curly
  apostrophe fallback; divergent strict/fallback results refuse ambiguity.
- NFKC alignment requires whole source clusters. Partial expansions, competing
  target slots, non-identical scalar/child candidates, unsupported transforms,
  non-finite/out-of-page geometry, and cross-page ownership fail closed.
- Markdown control characters and one-or-more-character setext forms are
  escaped. Complete source-visible text is never replaced by a partial
  projection.
- Extraction is page-transactional for page-local source/geometry/rule
  failures. Document character, deadline, and report-size failures refuse the
  document. Projection snapshots restore the exact affected page.
- Frozen limits cover 500,000 source characters; 4,096 runs/rules per page;
  10,000 runs/rules per document; 8,192/65,536 target slots; 1/8 MiB target
  text; 16 KiB per run; 256 UTF-8 bytes per font name; 64 rules per run;
  65,536 comparisons and rule associations; 8 MiB reports; bounded traversal,
  alignment work, concerns, and deadlines.
- Deterministic reduced-bound exact/max+1 tests exercise every resource class.
  The retained 64-link case completes; 65 links make only that page
  unavailable with `text_run_rule_limit`, no partial runs/rules, and a usable
  fail-closed document report.

## Performance and custody

| Isolated stage | p50 | p95 | max | Peak traced allocation |
|---|---:|---:|---:|---:|
| Source extraction | 107.093 ms | 118.615 ms | 134.893 ms | 9,753,721 bytes |
| Association/projection | 9.235 ms | 9.884 ms | 10.996 ms | 1,222,889 bytes |

The extraction report is 27,170 bytes. The projected IR is 124,533 bytes.
Both latency/allocation/size gates pass. The exact 64-link boundary completes
in 6.173 ms; the 65-link fail-closed case completes in 5.664 ms, both below
250 ms.

Five alternating fresh-process purchase pairs recorded clipped inclusive p95
overhead of 0.161812 s, or 2.24727% of the current 7.200387 s paired
predecessor. This is below both the 5% ceiling of 0.360019 s and the absolute
0.309 s ceiling. Operating-system caches were not explicitly flushed, so no
cold-cache claim is made.

Purchase flag-off/on median wall time is 6.203529/6.324927 s, with maxima of
7.428094/6.626299 s and maximum RSS of
1,478,098,944/1,489,289,216 bytes. Semantic JSON is
49,579/82,421 bytes, raw JSON 49,598/82,440 bytes, and Markdown
3,370/3,426 bytes. All five flag-off samples made zero extractor calls,
contained no US05 projection, and retained deterministic predecessor semantic
bytes.

Uber flag-off/on semantic JSON is 186,160/186,979 bytes, raw JSON
186,180/186,999 bytes, and Markdown 1,152/1,152 bytes. Maximum off/on worker
high-water RSS is 3,444,916,224/3,444,490,240 bytes
(3,285.33/3,284.92 MiB). It is retained as a memory guard, not used to excuse
semantic failure. Hosted requests, tokens, and cost are 0, 0, and $0.

The artifact binds 31 code/config/frontend/test/policy paths, four direct US05
source identities, nine current reviewed-order source identities, eight named
synthetic fixture identities, package manifests, Docling 2.114.0, Docling Core
2.88.0, pdfplumber 0.11.10, Pydantic 2.13.4, Python 3.13.5, and the exact
Tesseract 5.5.3 executable.

## Test gates

- Integrated US05 contract, story, adversarial, algorithm-hardening, and real
  corpus: **147 passed**, including enabled-US05 purchase 7/7 and full 41/41
  order.
- Cumulative Phase 01 and P03-US01–US04 compatibility: **566 passed**.
- Performance: **10 passed**.
- Retained artifact custody: **5 passed**.
- Frontend Node 22.18: lint, TypeScript, production build, **76/76 unit
  tests**, and **1/1 bundle test**.
- Targeted Python compilation and Ruff: **Pass**.
- Independent production/security and final custody audits: **Pass**.

The Python runs report existing Starlette/httpx and Docling deprecation
warnings. No new warning class was introduced. Automated frontend rendering,
normalization, copy/download, build, and bundle coverage passes; manual browser
click-through is not claimed.

## Retained artifact

Machine-readable final-code quality, exact input, semantic result, rollback,
performance, memory, dependency, environment, and zero-cost evidence is in
[P03-US05-text-run-metrics.json](P03-US05-text-run-metrics.json).

- Size: **82,934 bytes**
- Raw SHA-256:
  `0ba7e13f1fce12dc0f6c2d0a4e65aab850d2012025ca9996b9645d371aff7659`
- Semantic SHA-256:
  `e432ce80d6351d1d161010aec7f8b32a1622a54cf1b14e14bfccb3411c79c3c3`

The non-circular retained tests pin the raw artifact, recompute its semantic
digest, verify source/dependency/control/resource/rollback claims, and require
current-tree equality for US05-owned implementation, policy, harness, and test
inputs.

## Rollback and remaining scope

Set `PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED=false`. The extractor is skipped,
US05 fields/records/concerns are absent, and the exact P03-US04 predecessor is
restored.

Forms/key-values, outline hierarchy, and running-region/printed-page identity
remain owned by P03-US06–P03-US08. Table reconstruction, accepting/rejecting
changes, legal-intent inference, Office adapters, and Phase 04 remain out of
scope.
