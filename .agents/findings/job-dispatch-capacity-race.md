# Capacity changes during dispatch-time plan validation

Status: active
Last verified: 2026-11-25
Related: [Issue #21](https://github.com/heaje/muteinous/issues/21), D88–D89/D91–D93, [queue implementation](../../src/muteinous/infrastructure/jobs/queue.py)
Retire/promote when: provider integration and scheduler review have incorporated this evidence, or the dispatch algorithm is replaced.

## Finding

A plan validator must run outside the queue lock so cancellation and physical
completion can proceed. If capacity is released while validating a younger
job, an older blocked job may become eligible. Restarting the scan at the
oldest pending job when the capacity revision changes preserves resource-aware
FIFO.

## Reproduction / evidence

The [controlled regression](../../tests/integration/jobs/test_job_queue_scheduling.py)
`test_capacity_release_during_validation_restarts_fifo` holds the younger
job's validator open, releases the occupying worker, then releases validation.
It asserts that the older job dispatches first.

## Recommendation

Preserve the capacity-revision restart. Keep validators quick and read-only;
workers must not return until physical provider work has stopped.
