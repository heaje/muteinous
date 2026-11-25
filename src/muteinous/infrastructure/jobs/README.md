# In-process job execution

This component implements the shared queue foundation from [Issue #21](https://github.com/heaje/muteinous/issues/21).
The [canonical decisions](../../../../docs/architecture/decisions.md) remain authoritative.

- Construct a queue with named resource capacities and a dispatch-time plan
  validator. Every job declares at least one distinct resource, and occupies
  one slot of each until its physical invocation returns. Zero or unknown
  capacity is unavailable, not ordinary contention. Reducing a positive
  capacity never revokes occupied slots.
- Submit an immutable resolved `JobPlan` containing provider/backend identity,
  resource names and JSON-object input containing the appropriate source and
  configuration context. Supply the worker separately. A submission has a new
  stable ID, one execution attempt and no generic retry or expiration.
- Validation must be quick, read-only, check the original source and resolved
  plan (including provider safety), and return a useful reason if unusable.
  Ordinary preference changes must not invalidate otherwise valid plans.
  Eligible plans are always revalidated immediately before dispatch. Busy plans
  are revalidated for staleness only after `revalidate_interval` (default 1.0
  second), measured by the injectable monotonic `clock`; this can be configured
  as a positive finite constructor argument. The injected clock is trusted,
  must be monotonic and must not raise; clock failures on worker/completion
  paths are not contained. Domain-specific freshness checks remain necessary at
  result acceptance and any irreversible effect.
- The worker receives a `JobContext` with cooperative cancellation and optional
  progress reporting. Adapters must ensure all physical work has stopped before
  returning or raising, including asynchronous provider operations. Queue
  cancellation rejects late returned results and reports but cannot undo
  provider side effects; providers must not publish cancelled work. Successful
  results are stored and exposed by reference: providers must return immutable
  or unshared values and not mutate them after returning; the queue does not copy
  or re-version results.
- Failure details are truncated to 4,096 characters with the suffix
  `... [truncated]`.
- Workers may omit progress. Report full latest stage/activity/count snapshots;
  mark meaningful forward progress explicitly and use heartbeat for liveness.
  Only set `WorkCount.reliable` when the denominator is established. Overall
  counts are optional and must be independently defensible. The timestamps
  use a monotonic clock for in-process elapsed-time comparisons.
- Presentation can call `snapshot(id)` for the unthrottled latest state or
  `poll(job_id, after_revision=0)` for coalesced updates. Material changes are
  available immediately on the next poll; routine updates are coalesced
  to a configurable interval (default 250 ms). Display logical cancellation
  separately from `physical_running`; Needs attention requires explicit
  replanning/resubmission. No event history is retained.
- The presentation owns retention: call `discard(job_id)` to remove a terminal
  job only after physical work has stopped. It returns `False` for queued,
  running, or still-physical work; after removal, `snapshot`, `poll`, and
  `cancel` raise `KeyError`, and late context reports are ignored. There is no
  automatic pruning policy.
- The queue owner may use `drain()` to await pending and physical work;
  an optional caller wait timeout does not expire jobs. `close()` stops
  submissions, requests cancellation, and joins workers. It can wait
  indefinitely for a noncooperative provider. Call it from the owning thread,
  not from a worker or validator. The dispatcher and workers are non-daemon
  threads, so the owner MUST call `close()` or they will keep the interpreter
  alive. This is not application shutdown policy.
- Deterministic regressions live in the
  [queue-scheduling tests](../../../../tests/integration/jobs/test_job_queue_scheduling.py)
  and [queue-failure tests](../../../../tests/integration/jobs/test_job_queue_failures.py).

## Remaining integration

Real provider adapters and configuration/source validation, provider/model
safety limits and hardware-derived defaults (D90), alignment-specific budgets,
retry and stale-result coordination (D77–D86/D102), stall warnings (D94), UI
polling and user-facing status/actions, and application shutdown policy
(D103–D104) remain separate work. Persistence, restart recovery, distributed
execution and priorities are outside this foundation. The queue does not
authorize installation or domain-specific effects.
