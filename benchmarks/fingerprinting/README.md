# Source fingerprint benchmark — Issue #17, Stage 1

**No production algorithm has been selected.** This benchmark is evidence for a
maintainer recommendation only; explicit maintainer approval is required before
choosing a default or adding any production hashing dependency. See [Issue
#17](https://github.com/heaje/muteinous/issues/17), [source-validity amendment
and D10–D15/D20](../../docs/architecture/decisions.md#amendment-2026-11-25-source-validity).

## Scope and decision traceability

This isolated experiment compares SHA-256, BLAKE2b-256 and BLAKE3 over synthetic
source assets. It does not implement source validity, invalidation or any
production API; no benchmark-only package is imported by `src/`. D10–D13 and
D20 inform source identity/freshness and targeted invalidation only. D14–D15
verified-original/backup resolution remains separate implementation work.

D160–D165 support keeping this optional hardware benchmark outside routine
checks. The [job-capacity finding](../../.agents/findings/job-dispatch-capacity-race.md)
remains relevant to future shared resource accounting; this benchmark is not a
queue integration, inference workload, or scheduler validation.

## Windows execution (2026-11-25)

### Environment and setup

- Windows build reported by `Get-ComputerInfo`: Windows 10 Pro, version 2009,
  build 26300; Python `platform.platform()` reported
  `Windows-11-10.0.26300-SP0` (OS-identification APIs disagree).
- CPython 3.14.10 x64; uv 0.13.9; Go Task 3.54.0.
- AMD Ryzen 9 9900X, 12 cores / 24 logical CPUs; 32 GiB installed RAM.
- `Get-Volume D:`: NTFS, about 149.4 GB free at preflight. `Get-Partition D: |
  Get-Disk` identifies the device as Samsung MZVLB1T0HBLR-000L2 NVMe (1.024 TB).
  Verification was repeated with
  `Get-Partition -DriveLetter D | Get-Disk` and
  `Get-PhysicalDisk | Select FriendlyName,SerialNumber,UniqueId`: D: is disk 1,
  `SAMSUNG MZVLB1T0HBLR-000L2`, NVMe, serial `0025_388C_11C3_A5FF.`, unique ID
  `eui.0025388C11C3A5FF`. The separate `WD_BLACK SN770 1TB` is disk 0
  (`E823_8FA6_BF53_0001_001B_448B_4A9B_9C02.`), not D:. **The first three
  invocations were manually labelled WD_BLACK SN770 by mistake.** Their
  original JSONL provenance is deliberately unchanged; the CSV conversion adds
  `storage_label_recorded` and an explicit `storage_label_correction` on every
row from those runs (619 CSV records carry this correction). The fourth and
fifth invocations have the correct Samsung label. The benchmark
  accepts `--storage` as descriptive metadata; it does not discover or validate
  the physical device. This metadata error does not change trial measurements.
- Active power plan: Balanced. Defender preference query reported real-time
  monitoring enabled (`DisableRealtimeMonitoring=False`); it was not changed.
- At setup, available RAM was about 11.9 GB and total CPU utilization sampled
  once was 5.7%. OpenChamber, Chrome and HWiNFO64 were running; this is not a
  controlled or dedicated machine.
- Isolated benchmark environment was created outside the repository:

  ~~~powershell
  uv python install 3.14.10
  uv venv --python 3.14.10 "$env:LOCALAPPDATA/Temp/muteinous-fingerprint-env"
  $py = "$env:LOCALAPPDATA/Temp/muteinous-fingerprint-env/Scripts/python.exe"
  uv pip install --python $py --only-binary :all: -r benchmarks/fingerprinting/requirements.txt
  uv pip list --python $py
  ~~~

  Installed: `blake3==1.0.11`, `psutil==7.2.2`; the BLAKE3 `abc` vector
  matched `6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85`.
  `python -m pip list` was also attempted but this uv-created environment has
  no `pip` module; `uv pip list` succeeded. The project `.venv` and lock were
  not changed for benchmark dependency installation. The coordinator later
  ran `task setup` and `task check` successfully at `1c6d1e5`; the ignored
  project `.venv` is now present in this worktree.

Exact benchmark invocations (the raw JSONL captures the arguments and each
invocation's environment record):

~~~powershell
cmd /c "`"$py`" benchmarks/fingerprinting/benchmark.py --scratch D:/fingerprint-scratch --storage `"WD_BLACK SN770 1TB NVMe; NTFS`" --large-mb 100 1000 --small-profile 512x4096 --small-profile 2048x16384 --small-profile 8192x65536 --repeats 5 --algorithms sha256 blake2b-256 blake3 > benchmarks/fingerprinting/windows-2026-11-25.jsonl 2> benchmarks/fingerprinting/windows-2026-11-25.stderr.txt"
cmd /c "`"$py`" benchmarks/fingerprinting/benchmark.py --scratch D:/fingerprint-scratch --storage `"WD_BLACK SN770 1TB NVMe; NTFS`" --large-mb 10000 --repeats 3 --algorithms sha256 blake2b-256 blake3 >> benchmarks/fingerprinting/windows-2026-11-25.jsonl 2>> benchmarks/fingerprinting/windows-2026-11-25.stderr.txt"
cmd /c "`"$py`" benchmarks/fingerprinting/benchmark.py --scratch D:/fingerprint-scratch --storage `"WD_BLACK SN770 1TB NVMe; NTFS`" --large-mb --shared-50gb --repeats 2 --algorithms sha256 blake2b-256 blake3 >> benchmarks/fingerprinting/windows-2026-11-25.jsonl 2>> benchmarks/fingerprinting/windows-2026-11-25.stderr.txt"
cmd /c "`"$py`" benchmarks/fingerprinting/benchmark.py --scratch D:/fingerprint-scratch --storage `"Samsung MZVLB1T0HBLR-000L2 NVMe; NTFS`" --large-mb --small-profile 512x4096 --small-profile 2048x16384 --small-profile 8192x65536 --repeats 5 --algorithms sha256 blake2b-256 blake3 >> benchmarks/fingerprinting/windows-2026-11-25.jsonl 2>> benchmarks/fingerprinting/windows-2026-11-25.stderr.txt"
cmd /c "`"$py`" benchmarks/fingerprinting/benchmark.py --scratch D:/fingerprint-scratch --storage `"Samsung MZVLB1T0HBLR-000L2 NVMe; NTFS`" --large-mb --small-profile 512x4096 --small-profile 2048x16384 --small-profile 8192x65536 --repeats 5 --algorithms sha256 blake2b-256 blake3 >> benchmarks/fingerprinting/windows-2026-11-25.jsonl 2>> benchmarks/fingerprinting/windows-2026-11-25.stderr.txt"
& $py benchmarks/fingerprinting/jsonl_to_csv.py benchmarks/fingerprinting/windows-2026-11-25.jsonl benchmarks/fingerprinting/windows-2026-11-25.csv
~~~

The first three manually entered WD_BLACK strings above reproduce the original
commands and are incorrect device labels; they are not rewritten in the raw
JSONL. D: maps to the Samsung NVMe noted above. Later invocations also used the
harness's default small profiles. `run-04` used the pre-correction harness.
`run-05` repeats only the three small-asset profiles with the corrected timing
boundary and correct device label; use it for final small-file conclusions.
The CSV converter assigns run IDs in environment-record order.

### Method

The harness uses only stdlib, psutil and blake3. It writes exclusive-created,
deterministic synthetic fixtures using 1 MiB blocks, flushes them, checks
available scratch space with a margin, and removes per-workload files after
measurement (including interruption/error cleanup via temporary-directory
cleanup). A single shared 50 GB fixture is reused by each candidate in that
run. Each benchmark invocation checks SHA-256, BLAKE2b-256 and BLAKE3 known
`abc` vectors. The finalized harness compares per-algorithm ordered digest-list
checksums across configurations. Runs 1–4 were checked offline across
configurations and invocations; run 5 uses the finalized harness's in-run
digest check.

Fixtures larger than total RAM are labeled `cold` (working set larger than
RAM, not hardware cache eviction); the 10 GB fixture is `cold` only when
available RAM is below 10 GB. Other workloads are labeled `warm` after
pre-reading. The initial full run took its cache classification and initial
pre-read at workload start, then recorded available RAM in each trial row
after that trial. Its 10 GB workload was `warm` (12.91 GB available at
workload-baseline time); all <=1 GB and small workloads were also `warm`; the
50 GB file was `cold`. The finalized harness derives the label and pre-reads
immediately per trial; runs 4 and 5 use that behavior.
No reboot, admin action, cache flush or RAMMap was used. Read-only throughput
is measured for each workload. A fixed two-second standalone SHA-256
competitor baseline and concurrent competitor rate are recorded; CSV
conversion derives competitor and candidate slowdown. Candidate order rotates
between repetitions and the exact order is recorded.

Large files use serial file workers; many-small-asset sets compare serial and
at most two file workers (bounded to avoid unmeasured machine-wide fan-out).
BLAKE3 is run with one thread, two threads, and bounded automatic parallelism
(at most four threads). Thread count and process CPU time divided by elapsed
wall time are reported; process CPU utilization can exceed 100% when multiple
threads run. RSS is sampled about every 10 ms, so transient RSS peaks can be
missed. Windows `peak_wset` is a process-lifetime high-water mark and can carry
over between trials; it is not a per-trial memory peak. Neither metric counts
OS page-cache memory. Short fixtures are looped to at least 0.5 s for more
stable timing. The SHA-256 competitor is synthetic CPU work, not inference or
the shared job queue.

For the corrected harness, a two-worker executor is constructed before timing
and reused across all batches in a trial. Elapsed and process-CPU timers stop
immediately after the last batch, before sorting results, signaling stop, or
joining threads/shutting down the pool. **Runs 1–4 predate this correction:**
their two-worker small-file trial times include creating and shutting down a
pool on every batch pass, as well as sort/cleanup overhead. This primarily
limits comparisons for many-small-file, two-worker rows; use run 5 instead.
Large single-file serial trials never created a worker pool, but their old
timers still included sorting one result and sampler/competitor cleanup. That
overhead was not measured separately and is expected to be small relative to
the multi-second large-file hashes.

The old JSONL's `working_set_baseline_bytes` actually stored baseline RSS, not
working set. New trials emit `rss_baseline_bytes`; CSV conversion normalizes
both old and new names to that RSS-specific column without editing historical
JSONL. The separate process peak working-set metric remains a process-lifetime
high-water mark.

### Results

Raw Windows JSONL: [`windows-2026-11-25.jsonl`](windows-2026-11-25.jsonl).
CSV: [`windows-2026-11-25.csv`](windows-2026-11-25.csv). The CSV is produced by
[`jsonl_to_csv.py`](jsonl_to_csv.py) and adds candidate/competitor slowdown
ratios relative to standalone rates. It preserves each invocation's recorded
storage label and annotates the first three runs with the verified D:-device
correction; it does not modify the raw JSONL.
[`windows-2026-11-25.stderr.txt`](windows-2026-11-25.stderr.txt) is retained
with the capture; it is empty (zero bytes), so no benchmark stderr was emitted.

Trial counts below are per algorithm/configuration. Throughput is decimal
MB/s; entries are median `[min–max]` over serial, one-hash-thread,
no-competitor trials. All tabulated MB/s values use nearest-integer rounding
with half values rounded up, applied to the unrounded measurements. Read-only
baselines are measured separately. The
100 MB/1 GB runs used five repeats, 10 GB used three and the single shared
50 GB file used two. The 512×4 KiB, 2,048×16 KiB and 8,192×64 KiB asset sets
each have five repeats in the primary run, plus additional small-set runs
identified by `run_id` in the CSV.

| Workload | Cache | SHA-256, n | BLAKE3 (1 thread), n | BLAKE2b-256, n | Read-only baseline |
| --- | --- | ---: | ---: | ---: | ---: |
| 100 MB | warm | 1,310 [1,037–1,325], 5 | 2,523 [1,851–2,623], 5 | 500 [397–525], 5 | 4,282 MB/s |
| 1 GB | warm | 1,312 [1,216–1,343], 5 | 2,508 [2,379–2,547], 5 | 514 [481–522], 5 | 4,345 MB/s |
| 10 GB | warm | 1,375 [1,283–1,384], 3 | 2,689 [2,668–2,694], 3 | 529 [513–532], 3 | 3,755 MB/s |
| 50 GB shared file | cold* | 1,282 [1,270–1,294], 2 | 1,880 [1,866–1,894], 2 | 524 [521–528], 2 | 2,224 MB/s |

`*` Cold here means the 50 GB working set exceeds 32 GiB RAM; no OS cache
flush occurred. The 10 GB classification used the available-memory value at
workload start (12.91 GB), so it was warm under the approved threshold.

The corrected small-asset supplement is `run-05` in the CSV. Each cell below
is median serial / two-file-worker throughput in MB/s, five trials per mode;
fixtures were pre-read immediately before each trial:

| Asset profile | SHA-256 (1 / 2 workers) | BLAKE3, 1 hash thread (1 / 2 workers) | BLAKE2b-256 (1 / 2 workers) |
| --- | ---: | ---: | ---: |
| 512 × 4 KiB | 14 [12–14] / 13 [12–15] | 14 [12–14] / 14 [14–17] | 13 [12–14] / 15 [15–17] |
| 2,048 × 16 KiB | 48 [40–53] / 60 [46–69] | 49 [47–54] / 58 [52–69] | 46 [36–51] / 58 [47–68] |
| 8,192 × 64 KiB | 165 [159–193] / 216 [193–258] | 193 [182–205] / 222 [207–258] | 137 [110–160] / 200 [166–245] |

The standalone and contended two-worker measurements are also present in
`run-05`; see its row-level candidate and competitor slowdown columns in the
CSV. The earlier run-04 candidate slowdown ratios ranged 0.66×–1.41× and are
superseded for small-set conclusions. Across run-05's 120 matched contended
configurations (including both file-worker counts and all BLAKE3 thread modes),
candidate slowdown ranged 0.73×–2.05×. Median candidate slowdown by algorithm
was 1.05× for SHA-256, 1.05× for BLAKE3, and 1.03× for BLAKE2b-256. Median
competitor slowdown was 1.28×, 1.34×, and 1.26×, respectively. These short
trials are noisy; the ratios describe this synthetic setup, not application
contention.
In run-05, single-worker process-CPU medians were about 98–101%; two-worker
medians were about 165–185%.
These values are sensitive to OS scheduling and workload size and do not
establish an application worker-count policy.

The bounded BLAKE3 automatic mode (at most four threads) measured
2,470/3,127/3,241/2,228 MB/s at 100 MB/1 GB/10 GB/50 GB, respectively. The
two-thread mode measured 2,273/2,384/2,754/2,170 MB/s. At 50 GB, automatic
parallelism was only about 19% faster than one BLAKE3 thread and used median
114% process CPU; at 1 GB/10 GB it was about 25%/21% faster and used 180%/148%
CPU. One-thread BLAKE3 used approximately 92–101% CPU across these workloads.

| Workload | Candidate slowdown under competitor (SHA-256 / BLAKE3-1) | Competitor slowdown, median (SHA-256 candidate / BLAKE3-1 candidate) |
| --- | ---: | ---: |
| 100 MB | 1.2× / 1.2× | 1.5× / 1.4× |
| 1 GB | 1.2× / 1.1× | 1.4× / 1.3× |
| 10 GB | 1.2× / 1.1× | 1.4× / 1.2× |
| 50 GB | 1.2× / 1.0× | 1.4× / 1.2× |

Candidate slowdown is solo candidate throughput divided by contended candidate
throughput; competitor slowdown is standalone competitor rate divided by its
contended rate. Medians use matched repeat/configuration rows. The CPU competitor
is an artificial SHA-256 loop and the ratios are descriptive, not a prediction
of inference-job behavior.

Solo process CPU was near 100% for SHA-256 and BLAKE3 with one internal thread;
BLAKE2b-256 was also near one logical core but much slower. With BLAKE3
automatic threads, process CPU ranged from about 114% (50 GB) to 180% (1 GB).
Sampled RSS medians were roughly 33–46 MiB solo. Across all five captures,
maximum sampled RSS was 49.02 MiB (run-04, 8,192 × 64 KiB, contended BLAKE3,
two workers); maximum Windows peak working set was 49.05 MiB in the same
workload/run. Sampled thread counts varied with workload and Rust/OpenSSL
runtime threads; observed process maxima were 13 threads under the bounded
automatic mode/competitor. The small-set serial versus two-worker throughput
and contention comparison is reported above from the final five-repeat
supplement.

### Recommendation (not a selection)

For this machine and these synthetic workloads, **BLAKE3 is the performance
recommendation to take to maintainers**, not a production selection. With one
internal thread it delivered about 1.93×/1.91×/1.95× SHA-256 throughput on
100 MB/1 GB/10 GB, respectively, and about 1.47× on the 50 GB shared file, with
similar measured CPU utilization.
Bounded automatic parallelism improved 1 GB/10 GB rates further but consumed
more CPU; its 50 GB gain was modest. In run-05's synthetic many-small-file
sets, BLAKE3 was similar to SHA-256 on the smaller profiles and faster on the
largest profile; two-worker gains and contended ratios varied by profile.
SHA-256 remains a credible simpler
option: it is in `hashlib`, needs no extra dependency, and shows less packaging
and supply-chain burden. BLAKE2b-256 was much slower on the large sequential
files, while small-set results were closer. The recommendation is contingent on
maintainers accepting BLAKE3's native-wheel, transitive-license, frozen-app and
dependency-maintenance costs and choosing a production concurrency budget.
**Explicit maintainer approval is still required before any algorithm is
selected or any production dependency is added.**

### Dependency, packaging and portability assessment

- `blake3==1.0.11` installed from a binary wheel on pinned CPython 3.14.10
  Windows x64 using `--only-binary :all:`; import and known-vector verification
  passed. PyPI metadata declares `CC0-1.0 OR Apache-2.0` and includes `LICENSE`.
- PyPI 1.0.11 metadata and the
  [upstream release](https://github.com/oconnor663/blake3-py/releases/tag/1.0.11)
  show CPython 3.14 wheels for Windows x64/ARM64, Linux manylinux and macOS
  x86_64/arm64. This is wheel availability evidence, not Linux/macOS runtime
  testing. The release was published 2026-10-08; preceding 1.0.10 was 2026-09-29.
- Upstream describes the binding as wrapping the official Rust implementation
  via PyO3, with Rayon parallelism. Its `1.0.11` Cargo.lock includes `blake3`,
  `cpufeatures`, Rayon/crossbeam, PyO3 and other crates. The lock was retrieved;
  an exhaustive license audit of every transitive crate was not completed and
  remains a packaging follow-up. The project’s eventual frozen-app packaging
  has not been tested; native extension collection and license notices would
  need verification. The Rust implementation’s CPU-feature dispatch and
  upstream SIMD support are not independently verified on other machines by
  this experiment.
- SHA-256 and BLAKE2b-256 use `hashlib` and add no package dependency. BLAKE3
  adds a compiled extension and its supply-chain, update, license-notice and
  frozen-distribution obligations. Linux/macOS compatibility here is paper
  evidence only.

### Validation status

- `uvx ruff check benchmarks/fingerprinting/benchmark.py benchmarks/fingerprinting/jsonl_to_csv.py`
  — passed.
- `uvx ruff format --check benchmarks/fingerprinting/benchmark.py benchmarks/fingerprinting/jsonl_to_csv.py`
  — passed.
- Run-05 used only the three small-asset profiles, five repeats and all three
  algorithms. Its environment record is `run-05`; each profile contains 80
  trials (240 total). The original 586,203-byte raw JSONL prefix was verified
  byte-for-byte by SHA-256 before/after append; no earlier record was rewritten.
- Full capture parses as 1,137 JSONL records: 5 environment, 1,038 trial, 75
  order and 19 workload-baseline records. Digest-list equality passed across
  all 21 workload/algorithm pairs and configurations. The CSV has 1,137 rows
  and run IDs `run-01` through `run-05`; the first three runs retain 619
  storage-label correction annotations. Legacy
  `working_set_baseline_bytes` values and new `rss_baseline_bytes` values both
  convert to the canonical CSV `rss_baseline_bytes` column.
- `task setup` and `task check` passed at `1c6d1e5` (coordinator-run); setup
  created the ignored project `.venv`, and the worktree stayed clean. After the
  final correction commit, `task check` was rerun locally and passed (exit 0).
- `uvx ruff check benchmarks/fingerprinting/benchmark.py benchmarks/fingerprinting/jsonl_to_csv.py`
  — passed after the final correction.
- `uvx ruff format --check benchmarks/fingerprinting/benchmark.py benchmarks/fingerprinting/jsonl_to_csv.py`
  — passed after the final correction.
- `git diff --check` — passed.

## Historical preliminary Linux execution (2026-11-25)

The following section preserves the earlier limited Linux evidence; it is not
the Windows result and its values are unchanged. The actual code Git blob was
`3ec9a2e9ad9c48cf3994b7b0f17c303244802b8d`. No checkout was available:
GitHub connector source reads/push were unavailable and container Git network
DNS failed. CPython 3.13.5 (not pinned 3.14.10), Linux 6.18.57 x86_64 glibc
2.41, OpenSSL 3.5.5, Intel Xeon Platinum 8573C with SHA-NI, 5 logical CPUs
reported, cgroup CPU quota 4 CPUs, memory.max 4 GiB; psutil host RAM 6.24 GB,
overlay filesystem 30 GiB free and backing hardware unknown. No controlled
cache eviction, dedicated CPU or physical SSD evidence. Network prevented
obtaining BLAKE3 or managed Python; no 10 GB/50 GB tests and no Windows/macOS
execution. The script completed 42 trials (3 per configuration) for SHA-256
and BLAKE2b-256; BLAKE3 was not run.

Exact historical commands:

~~~sh
python -m venv /tmp/muteinous-bench-17
/tmp/muteinous-bench-17/bin/pip install --retries 0 --timeout 5 blake3 psutil
# failed: no matching distribution found for blake3
cp -a /opt/pyvenv/lib/python3.13/site-packages/psutil /opt/pyvenv/lib/python3.13/site-packages/psutil-7.2.2.dist-info /tmp/muteinous-bench-17/lib/python3.13/site-packages/
/tmp/muteinous-bench-17/bin/python /tmp/muteinous17/benchmark.py --scratch /tmp/muteinous17 --storage 'Linux container overlay; backing device unknown' --large-mb 100 1000 --algorithms sha256 blake2b-256 > /tmp/muteinous17/results.jsonl
~~~

Both `abc` vectors and repeated/parallel digest-list checks passed; BLAKE3
vector and code path were not executed. [Historical trial data](linux-preliminary.csv)
is retained unchanged. Actual sizes were 100,000,000 and 1,000,000,000 bytes;
small set was 2,048 × 16,384 bytes. Digest-list SHA-256 checksums (ASCII
concatenation of per-file hex digests):

| Workload | SHA-256 | BLAKE2b-256 |
| --- | --- | --- |
| 100 MB | 48be25eeabf742aee6126fd93480c5c5d030b60445306d0cc933b82802d13d21 | b1bea16d2cffc10dc60e0dc720830b272a0aadcd526aee9521849c31d1026a79 |
| 1 GB | 4e6667e143b01928d2ead96d033fa56c665e66f2954a1b8759410c23b316a321 | b267c5e2befc085898761016839837ff050cc732b3b00fe7557fc851d14807d5 |
| Small | 69ce7b6647837d45795a67066b545a29529fdd3c2eb0d0256276ed45541236a3 | 1d58cb39b936f52342f1977c69605fb28a5bd779e3119cdd70257ac80c5fcb91 |

Median serial no-contention (MB = 10^6 bytes, three trials, includes
first-after-generation for SHA-256):

| Workload | SHA-256 seconds / MB/s | BLAKE2b-256 seconds / MB/s | BLAKE3 |
| --- | ---: | ---: | --- |
| 100 MB | 0.097 / 1030 | 0.176 / 569 | Not run |
| 1 GB | 0.866 / 1154 | 1.755 / 570 | Not run |
| Small | 0.044 / 754 | 0.071 / 476 | Not run |

Sampled maximum RSS was about 21.8 MiB; thread count was 2 serial, 3 with
competitor and 4 with two file workers. At 1 GB, median CPU seconds were 0.874
/ 1.767; under contention they were 1.748 / 5.930 including competitor.
Contended median throughput was SHA-256 1150 MB/s and BLAKE2b-256 338 MB/s
(individual 334–579); this noisy result cannot causally attribute contention.
Small two-worker medians were 526 and 612 MB/s respectively; threading helped
BLAKE2b-256 but hurt SHA-256 in this run. No all-platform generalization.

## Recommendation and limits

The recommendation above is limited to the synthetic workloads and the
reported Windows machine. The small-asset two-worker comparison and its
competitor-contended supplement must be interpreted by `run_id`; do not merge
repeats across runs as if they were one controlled invocation. Do not begin
Stage 2, add production dependencies, select an algorithm, merge the PR or
close #17 as part of this benchmark.
