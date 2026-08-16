# LAT-US02 production and security review

Date: 2026-08-10  
Review scope: production exposure, lifecycle failure isolation, campaign
controller security/custody, rollback, hosted use, and process cleanup  
Disposition: **NO-GO — one unresolved CPU/native-lineage Major; no Blocker and
no remaining non-CPU Major**

## Frozen evidence reviewed

- contract SHA-256
  `02bd331f5bb29dc2a2a5938b14afb239e54beaf7694c484fc75bc3fe2ad01cfe`
- production-worker SHA-256
  `484629d86b137f03b64e4b1099210aabb50d2c18d962799813998462c064dd21`
- production-runner SHA-256
  `ec2a075bbb06d410d93476b62734c956352e50ffa7f89c82da9956322e43700c`
- external prewarm-watchdog SHA-256
  `fb28b7edb1f78bcd6f73a763e00e1b14dcf8b81cd0810a6492f878042dd61991`
- production-adapter test SHA-256
  `b25bef9f43934ab62bfabe207070bab79f2d0bb52cda2dff5ccf8cdc76c8f8b4`
- synthetic evidence test SHA-256
  `5f9d181153e30981832e01d9622863e97314123d432dd627fb87214770f72e67`

Independent verification passed **12/12** focused adversarial checks and the
five-suite matrix **165/165**, with one existing Starlette deprecation warning.
Six frozen sources compiled in memory. No raw `communicate()` or post-hoc
truncation path remains.

## Fixed findings

- Full normal/cross-input `SIGTERM`/`SIGHUP` custody now constructs launch
  custody before the durable intent commit, retains terminal failure and
  post-artifact observations, then re-raises.
- Normal worker exit freezes one timestamp after kernel-empty proof and rejects
  equality or lateness against both phase and absolute deadlines; the terminal
  schema independently enforces the same rule.
- Only kernel `ESRCH` proves process-group disappearance. Empty, raced, or
  errored enumeration remains active/unknown, and zombies remain residue until
  reaped.
- Cleanup signals only a frozen PID/create-time/PGID/SID identity and refuses
  PID/PGID reuse or drift.
- Failure of the watchdog `Popen` closes the terminal descriptor, terminates
  and reaps the worker, and restores the controller's exact thread/FD baseline.
- Bounded incremental stdout/stderr capture, external parent/deadline watchdog,
  immutable launch/terminal records, and phase ACK grammar remain fail-closed.

## Remaining Major

`LAT-US02-METRIC-CPU-001` is independently confirmed in
[the CPU-lineage blocker record](LAT-US02-cpu-lineage-blocker.md). The campaign
cannot prove that request CPU includes every owned native descendant. This is a
resource/custody Major, not a numerical RSS issue, and prevents launch and Done.

## Conditional Minor hardening

- Caller-supplied endpoints are resolved before some symlink checks. The exact
  reviewed invocation mitigates this with direct, no-symlink, byte-bound paths;
  future hardening should use pre-resolution `lstat`/`openat(O_NOFOLLOW)`.
- The planned bundle does not hash-index every standalone launch/watchdog/
  artifact observation. Any future campaign needs a fresh private `0700`
  directory and a terminal O_EXCL/fsynced all-record manifest.
- Before/after artifact identity cannot prove that no write-and-restore occurred;
  the reviewed private tree, exact content/metadata equality, and no-write
  observation are conditional mitigations, not syscall-level read-only proof.

## Review conclusion

Production application/config/API review found no separate Blocker or Major.
The feature remains default-off and production is not enabled. The single-flag
rollback remains `PARSER_LATENCY_PREWARM_ENABLED=false`. No hosted/provider
call or production campaign occurred. Security review does not approve launch
until CPU/native lineage is made non-bypassably complete and independently
re-reviewed.
