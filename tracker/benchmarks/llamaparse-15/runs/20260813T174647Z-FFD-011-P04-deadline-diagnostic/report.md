# P04 document-deadline diagnostic

**Classification:** diagnostic only; not release or FFD-011 closure evidence.

Production remained unchanged at 5.0 seconds/document and 0.5 seconds/page. Each row ran in a fresh process; only the test harness temporarily widened the cumulative document clock.

| Case | Document budget (s) | Terminal outcome | Table sidecars | Custody | Reviewed content |
| --- | ---: | --- | ---: | --- | --- |
| clinical-study | 5 | rolled_back_integrity_or_resource | 0/2 | no | pass |
| ny-timetable | 5 | rolled_back_timeout | 0/3 | no | pass |
| clinical-study | 10 | rolled_back_integrity_or_resource | 0/2 | no | pass |
| ny-timetable | 10 | committed_with_custody | 2/3 | yes | pass |
| clinical-study | 15 | rolled_back_integrity_or_resource | 0/2 | no | pass |
| ny-timetable | 15 | committed_with_custody | 2/3 | yes | pass |
| clinical-study | 30 | rolled_back_integrity_or_resource | 0/2 | no | pass |
| ny-timetable | 30 | completed_without_custody_or_state | 0/3 | no | pass |

## Findings

- Clinical: Increasing the document clock does not commit Clinical custody. Every lane reaches the same terminal visual-overlay canonical-splice integrity rejection and restores exact table content.
- NY timetable: The 5-second lane times out in terminal custody. Longer document lanes can commit custody, but the unchanged 500 ms page clock can still withhold one or all table sidecars near its boundary.
- Closure: No elevated-budget artifact is release or FFD-011 closure evidence. The experiment identifies separate P04 integrity and performance/page-budget work; production remains at 5.0 seconds per document and 0.5 seconds per page.
