# Capacity changes during dispatch-time plan validation

Status: active
Last verified: 2026-11-24
Related: [Issue #21](https://github.com/heaje/muteinous/issues/21), D88–D89/D91–D93, [queue implementation](../../src/muteinous/infrastructure/jobs/queue.py)
Retire/promote when: provider integration and scheduler review have incorporated this evidence, or the dispatch algorithm is replaced.

## Finding and limitations

A plan validator must not run under the queue lock: otherwise cancellation and
physical completion cannot proceed while the validator is checking external
state. But a resource release while validating a younger job can make an
older previously blocked job eligible. Continuing the old scan would violate
resource-aware FIFO. The implementation tracks a capacity revision, restarting
at the oldest pending job on changes before dispatch.

## Reproduction / evidence

The [controlled regression](../../tests/integration/test_job_queue.py)
`test_capacity_release_during_validation_restarts_fifo` holds the younger
job's validator open, releases the occupying worker, then releases validation.
The older job must dispatch first. The test passed in the isolated Python
3.13.5 focused run; pinned Task and three-platform CI remain unverified.

## Recommendation

Preserve the capacity-revision check when integrating provider validators.
Keep validators quick and read-only; they must not wait for queue capacity.
Worker adapters must not return until physical provider work has stopped,
even if the job is already logically cancelled.
