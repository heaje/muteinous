# Capacity changes during dispatch-time plan validation

Status: resolved
Last verified: 2026-11-26
Related: [Issue #21](https://github.com/heaje/muteinous/issues/21), D88–D89/D91–D93, [queue implementation](../../src/muteinous/infrastructure/jobs/queue.py)
Resolved by the capacity-revision restart already present in the queue implementation; the regression evidence is retained below. The queue scheduling invariant is now covered in its implementation/test and this finding is no longer active.

## Finding

A plan validator must run outside the queue lock so cancellation and physical
completion can proceed. If capacity is released while validating a younger
job, an older blocked job may become eligible. Restarting the scan at the
oldest pending job when the capacity revision changes preserves resource-aware
FIFO.

## Reproduction / evidence

The current [queue implementation](../../src/muteinous/infrastructure/jobs/queue.py)
restarts scheduling from the oldest pending job when its observed capacity
revision changes during out-of-lock validation. The
[controlled regression](../../tests/integration/jobs/test_job_queue_scheduling.py)
`test_capacity_release_during_validation_restarts_fifo` holds the younger
job's validator open, releases the occupying worker, then releases validation.
It asserts that the older job dispatches first.

## Recommendation

The capacity-revision restart and FIFO regression are present; no separate
workaround remains to recommend. Keep validators quick and read-only; workers
must not return until physical provider work has stopped. Future source hashing
must occupy queue resources for its complete physical duration and must not run
inside dispatch validators; this enduring constraint is recorded in
[`docs/source-validity.md`](../../docs/source-validity.md#hashing-and-resource-policy).
