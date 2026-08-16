# LlamaParse Latency Reference v1

Status: **Canonical initial planning reference for unfinished Phases 04–08**  
Captured: 2026-08-08 (Asia/Kolkata)  
Authority: explicit sponsor direction to use LlamaParse latency as the sole
latency benchmark before further implementation

## Source-of-truth configuration

The authenticated LlamaCloud session was already signed in as
`vignesh.ph10@gmail.com`; no credential was entered or retained in the
workspace. The measurements came from project
`ec7edb70-8bec-4b1b-9a17-451533884780`, Parse history, **Metrics**, API **v2**.

Every canonical row used:

- LlamaCloud Parse v2;
- Agentic tier, displayed as 10 credits/page;
- cost optimizer off;
- **Disable cache** on;
- the provider's built-in public sample for the named case; and
- provider-UI **Total Latency** with a `COMPLETED` result.

LlamaCloud states that job results are retained for 48 hours. The job IDs and
displayed totals below are therefore the durable review keys after the live UI
result expires. The authenticated Metrics tab was retained as deliverable UI
evidence at the end of capture.

## Initial observations

These are one successful observation per case. They are planning/reference
ceilings, not p50 or p95 claims and not sufficient to complete a story or
phase.

| Case | LlamaParse job ID | Provider UI Total Latency |
|---|---|---:|
| `finance-10k` | `pjb-415ucx2flb2ild9e0nzdsqnxqr6f` | 29.4 s |
| `ny-timetable` | `pjb-7ljh3v6chmcbpp7qriuwvbbglpat` | 45.6 s |
| `uber-earnings` | `pjb-g8gebswwjtgtx77b2wmqpc48sjox` | 23.3 s |
| `insurance-acord` | `pjb-5vhh93gwvnlcl0wpudldf9qw7b8w` | 36.8 s |
| `clean-energy` | `pjb-14abieg7n30s9n097cvpc3w2uquv` | 24.7 s |
| `catastrophe-recap` | `pjb-soooy4n3oxl6ag18pldsw19g8xxj` | 16.5 s |
| `clinical-study` | `pjb-vnbjplhc4ylxnj78c8k21pfodlnw` | 24.1 s |
| `component-datasheet` | `pjb-d0n8nruy0xdoydlvcqrn3afdhwf3` | 31.0 s |
| `egov-survey` | `pjb-y0tdbxcc3gx5ttbux75jhob98b1n` | 15.8 s |
| `esg-metrics` | `pjb-ghgiqgq0c67l0zx26fsmh60xlpzp` | 30.7 s |
| `health-report` | `pjb-7od9q65l2z9dnr95okl6pfgg89eo` | 35.0 s |
| `manufacturing-report` | `pjb-x9i4sf12uky1o4elp0ntpdy5j56l` | 18.8 s |
| `postal-10k` | `pjb-0qtz3dizelo6pu7gv0f4ur8g1bij` | 25.3 s |
| `purchase-agreement` | `pjb-tejko7iocgaav1wtj7z5tm5lugju` | 48.8 s |
| `settlement-agreement` | `pjb-ha1zlpsbx1ebb4910oipib1dah3d` | 1.4 min |

For `settlement-agreement`, 84.0 seconds is the exact unit conversion of the
UI's rounded `1.4m` display. It does not imply precision below 0.1 minute.
Across the 15 displayed case observations, the descriptive median is 29.4
seconds and the range is 15.8 seconds to 1.4 minutes. Those cross-case
statistics describe this capture only; neither is an acceptance threshold.

The earlier `ny-timetable` job
`pjb-od0v3uheoxq450tvlsfp1yu70sag` displayed 54.9 seconds, but its cache
setting was not verified. It is excluded from the canonical reference and may
not be substituted for the cache-disabled row.

## Operative comparison contract

Before an applicable story can satisfy Definition of Done, and again before a
phase exit or release decision:

1. run the candidate and LlamaParse on the same source bytes and semantically
   comparable output request/configuration;
2. use LlamaCloud Parse v2 Agentic, cost optimizer off, cache disabled, and
   provider Total Latency;
3. collect at least five interleaved candidate/Llama observations per
   applicable case on final code, retaining every success, failure, timeout,
   configuration identity, and raw duration;
4. compute empirical inclusive nearest-rank p50 and p95 separately for the
   candidate and LlamaParse (`p95` is the maximum when `n=5`);
5. require candidate p50 ≤ paired Llama p50 **and** candidate p95 ≤ paired
   Llama p95 for every case independently; and
6. reject corpus-average masking, dropped failures, cache hits, input drift,
   quality reductions, and reliability reductions.

If exact-byte or documented semantic comparability cannot be established, the
latency result is **Unmeasured/Blocked**. An older local duration, flag-off
ratio, stage timing, component timing, corpus average, or unrelated format may
not substitute for LlamaParse.

The existing `baseline-20260728-current` run is our own isolated,
network-disabled parser. Its timing remains immutable diagnostic history and
is not LlamaParse service latency. The expert LlamaParse outputs remain a
quality comparison target only where source review classifies them as
source-grounded; faster latency never permits fabricated or lower-quality
output.

## Phase applicability

| Phase | Initial applicable reference | Required interpretation |
|---|---|---|
| 04 — Tables | `finance-10k`, `ny-timetable`, `postal-10k`; other table positives/controls as exercised | Direct per-case comparison; table quality and RSS gates remain independent |
| 05 — Charts & Diagrams | `ny-timetable`, `uber-earnings`, `manufacturing-report`, `health-report`; other visual cases as exercised | Direct per-case comparison with unchanged grounding and no-fabrication gates |
| 06 — Visual Models | `ny-timetable`, `postal-10k`, `uber-earnings`; every enabled model route as exercised | Compare complete candidate request latency; local stage/model timings are attribution only |
| 07 — Cross-format | Matching PDF cases initially; direct-image and Office semantic twins when available | DOCX/PPTX/XLSX and unmatched image paths remain Unmeasured/Blocked until a comparable LlamaParse run exists |
| 08 — Production Hardening | All 15 canonical rows plus every enabled semantic twin/profile | Paired per-case canary/release blocker; no aggregate masking |

Applicability follows the exact fixtures exercised by a story; this table is a
minimum planning map, not permission to omit an affected case.

## Gates not replaced

This source-of-truth change replaces only the candidate latency comparator.
Correctness, source fidelity, quality, security, privacy, hosted-use/custody,
API/schema/serializer/frontend compatibility, CPU/GPU/resource budgets,
RSS/memory, output-size, cost/egress, deterministic behavior, timeout and
fail-closed safety, default-off behavior, rollback, dependency integrity, and
manual/release approval remain independently blocking. Provider-side RSS is
unknown, not zero, and does not waive candidate RSS evidence.

Completed Phase 00–03 records remain immutable. In particular, this reference
does not amend the active P03-US08 administrative exception or turn Phase 03
into a strict current-artifact metrics pass.

Machine-readable companion:
[`latency-reference-v1.json`](latency-reference-v1.json). Controlling planning
decision:
[`2026-08-08-llamaparse-latency-source-of-truth.md`](../../decisions/2026-08-08-llamaparse-latency-source-of-truth.md).
