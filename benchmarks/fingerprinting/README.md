# Source fingerprint benchmark — Issue #17, Stage 1 (incomplete)

**Checkpoint only. No production algorithm selected; no approval requested yet.** See [Issue #17](https://github.com/heaje/muteinous/issues/17), [PR #32](https://github.com/heaje/muteinous/pull/32) and the [source-validity amendment](../../docs/architecture/decisions.md#amendment-2026-11-25-source-validity).

## Discovery and scope

Verified main at 364b400ae4c4b0e00fcbe8b6f91013f9d755d995 (merged #32). Read AGENTS, implement-issue workflow, coordination snapshot, release scope, code organization, testing/development policies and applicable D10–D15, D20, D160–D165. #16 closed, merged [source model](../../src/muteinous/models/source.py) is metadata only. Enumerated findings: audio codec/native round trips are out of scope; [job capacity race](../../.agents/findings/job-dispatch-capacity-race.md) is relevant to eventual physical resource accounting and confirmed the queue still uses capacity revision and physical worker retention. This experiment is not job-queue integration. No shared architecture/coordination changes.

## Reproduction plan (Windows first)

From the checkout root, on pinned CPython 3.14.10, use an external scratch drive/directory and an isolated venv; never install these in the project's locked .venv. Example PowerShell (substitute the actual scratch path and storage description):

~~~powershell
uv python install 3.14.10
uv venv --python 3.14.10 "$env:TEMP/muteinous-fingerprint-env"
$py = "$env:TEMP/muteinous-fingerprint-env/Scripts/python.exe"
uv pip install --python $py --only-binary :all: -r benchmarks/fingerprinting/requirements.txt
& $py -m pip list # if pip is present; otherwise use uv pip list --python $py
$root = "D:/fingerprint-scratch"
New-Item -ItemType Directory -Force $root
Get-ComputerInfo | Select-Object WindowsProductName,WindowsVersion,OsBuildNumber,CsTotalPhysicalMemory
Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors
Get-Volume -DriveLetter D
Get-PhysicalDisk | Select-Object MediaType,BusType,Size
& $py benchmarks/fingerprinting/benchmark.py --scratch $root --storage "REPLACE: drive/device/filesystem" --large-mb 100 1000 10000 50000 > fingerprint-windows.jsonl
~~~

Run 10 GB and 50 GB only when capacity/time permits; choose smaller arguments rather than fill a drive. Use dedicated disposable scratch, not a game directory. Default 100 and 1000 decimal MB and 2,048 x 16,384-byte files (33,554,432 bytes). One fixture set at a time, exclusive creation in a newly created temporary directory, automatically removed on normal completion/error. Space preflight with margin, bounded block reads of 1 MiB, at most two file workers or two BLAKE3 internal threads (not nested); one CPU competitor and one sampling thread. Seeded SHAKE256 stream per asset/block is deterministic, actually written and flushed, no sparse zero-file shortcut. Synthetic data is not committed.

The harness times open/read/update/finalize, file-worker setup/join and result ordering (not fixture creation, digest-list verification, or post-timing sampler/competitor cleanup). Digest vector abc and identical ordered digest-list checksum across repetitions/configurations detect basic mistakes. The BLAKE2b digest size is set to 32 at construction, not truncation. BLAKE3 uses default 32-byte output with explicit max_threads. CPU time is whole-process, including sampling and competitor cleanup; RSS and threads sampled every 10 ms are approximate lower bounds on true peaks, not exact high-water marks or isolated per-hash memory. File enumeration is prepared before timing. CPU competitor hashes memory in a separate thread, not actual inference or the shared job queue; competitor rate lacks a solo baseline, so does not quantify slowdown. A last block may finish after timing. Two file workers on small files, one or two internal threads for large BLAKE3, serial baseline for all. Rotate configuration order across repetitions, three by default; report individual runs as well as median and range. No hidden machine-wide cache flushing or privileged writes. First run follows fixture writing and is NOT cold; remaining runs are uncontrolled repeated reads, likely cache-influenced. No proven warm/cold contrast yet. Short small-file runs and shared process allocator state limit measurements.

Before accepting Windows evidence: run all three with pinned Python and wheel versions, use a dedicated SSD/NTFS (or record actual filesystem), record drive and machine properties and load, repeat small assets with varied sizes/counts and enough duration, separately measure genuinely controlled cold reads (e.g. reboot before each candidate on a dedicated machine if authorized) and explicit warm pre-read when fixture fits RAM; balance first-run order. Include standalone competitor baseline and two-worker contention, record actual CPU affinity/resource limits. Compare read-only throughput to distinguish disk saturation from hash compute; note when 10/50 GB exceeds cache capacity. Do not call the current harness cold/warm controlled or claim genuine job scheduling evidence. Independent reviewer should validate this methodology, code, digest correctness, output and recommendation before approval.

## Preliminary Linux execution (2026-11-25)

Actual code Git blob 3ec9a2e9ad9c48cf3994b7b0f17c303244802b8d. No checkout available: GitHub connector for source reads and branch push, container Git network DNS failed. CPython 3.13.5 (not pinned 3.14.10), Linux 6.18.57 x86_64 glibc 2.41, OpenSSL 3.5.5, Intel Xeon Platinum 8573C with SHA-NI, 5 logical CPUs reported, cgroup cpu.max 400000/100000 (4 CPU quota), memory.max 4,294,967,296 bytes; psutil host RAM 6,236,844,032 bytes, overlay filesystem 30 GiB free at preflight, backing hardware unknown. No controlled cache eviction, no dedicated CPU or physical SSD evidence. Network prevents obtaining BLAKE3 or managed Python; no 10 GB/50 GB tests in this time/resource-limited session (50 GB exceeds scratch capacity). No Windows/macOS execution. Used existing psutil 7.2.2 copied into a disposable venv only; not an independently verified wheel install.

Exact local commands (temporary locations only):
~~~sh
python -m venv /tmp/muteinous-bench-17
/tmp/muteinous-bench-17/bin/pip install --retries 0 --timeout 5 blake3 psutil
# failed: no matching distribution found for blake3
cp -a /opt/pyvenv/lib/python3.13/site-packages/psutil /opt/pyvenv/lib/python3.13/site-packages/psutil-7.2.2.dist-info /tmp/muteinous-bench-17/lib/python3.13/site-packages/
/tmp/muteinous-bench-17/bin/python /tmp/muteinous17/benchmark.py --scratch /tmp/muteinous17 --storage 'Linux container overlay; backing device unknown' --large-mb 100 1000 --algorithms sha256 blake2b-256 > /tmp/muteinous17/results.jsonl
~~~

A direct download of the published BLAKE3 wheel also failed. The executed script completed 42 trials (3 per configuration), exit 0. Both abc vectors and repeated/parallel digest-list equality checks passed; BLAKE3 vector and code path not executed. [Individual trial metrics](linux-preliminary.csv) are rounded to 6 decimal places from JSONL; no omitted trials. Actual sizes 100,000,000 and 1,000,000,000 bytes, small 33,554,432 bytes. Digest-list SHA-256 checksums (checksum of ASCII concatenated per-file hex digests):

| Workload | SHA-256 | BLAKE2b-256 |
| --- | --- | --- |
| 100 MB | 48be25eeabf742aee6126fd93480c5c5d030b60445306d0cc933b82802d13d21 | b1bea16d2cffc10dc60e0dc720830b272a0aadcd526aee9521849c31d1026a79 |
| 1 GB | 4e6667e143b01928d2ead96d033fa56c665e66f2954a1b8759410c23b316a321 | b267c5e2befc085898761016839837ff050cc732b3b00fe7557fc851d14807d5 |
| Small | 69ce7b6647837d45795a67066b545a29529fdd3c2eb0d0256276ed45541236a3 | 1d58cb39b936f52342f1977c69605fb28a5bd779e3119cdd70257ac80c5fcb91 |

Median serial no-contention (MB = 10^6 bytes, three trials, includes first-after-generation for SHA-256):

| Workload | SHA-256 seconds / MB/s | BLAKE2b-256 seconds / MB/s | BLAKE3 |
| --- | ---: | ---: | --- |
| 100 MB | 0.097 / 1030 | 0.176 / 569 | Not run |
| 1 GB | 0.866 / 1154 | 1.755 / 570 | Not run |
| Small | 0.044 / 754 | 0.071 / 476 | Not run |

Sampled maximum RSS ~21.8 MiB, 2 threads serial including sampler, 3 with competitor, 4 with two file workers; not total memory including OS page cache. At 1 GB, median CPU seconds 0.874 / 1.767 respectively, under contention 1.748 / 5.930 including competitor. Contended median throughput SHA-256 1150 MB/s, BLAKE2b-256 338 MB/s (individual 334–579); high variance, no causal attribution to a resource without isolation. Small two-worker medians 526 and 612 MB/s respectively; threading helped BLAKE2b-256 but hurt SHA-256 in this run. No all-platform generalization. The CSV has CPU, RSS and competitor throughput for every trial.

## Dependency, packaging and portability assessment

- SHA-256 and BLAKE2b-256 use Python hashlib; no extra production dependency or wheel. Both are in [CPython 3.14 hashlib](https://docs.python.org/3.14/library/hashlib.html); GIL release for >2047 bytes per update allows concurrency, actual acceleration/provider varies. SHA-256 can use OpenSSL hardware acceleration or fallback; BLAKE2b implementation and performance may differ. CPython PSF license and bundled native/OpenSSL notices still apply (not a separate algorithm package); verify eventual frozen runtime license inventory and crypto/provider constraints.
- [BLAKE3 Python binding 1.0.11](https://pypi.org/project/blake3/1.0.11/) published Oct 8 2026, metadata CC0-1.0 OR Apache-2.0, native Rust binding with explicit parallelism. [Upstream releases](https://github.com/oconnor663/blake3-py/releases) and recent wheels are evidence of maintenance, not a guarantee. CPython 3.14 regular ABI wheels listed for Windows x64 (219 kB), ARM64/x86, manylinux x64/ARM64, macOS Intel/ARM64. Check actual binary-only installation/import on pinned runtime, license/notice inventory including Rust transitive components, CPU feature dispatch, frozen app support, and lock/Dependabot/security updates before any production adoption. Source builds add Rust/toolchain burden. Wheel listings are not successful installs or portable execution. No packaging choice or runtime dependency change proposed.
- psutil is benchmark instrumentation only (BSD-3-Clause; 7.2.2 pinned). Do not add to production or change the existing project lock.

## Provisional interpretation and handoff

SHA-256 is the preliminary low-dependency front-runner among the **two measured algorithms only**; no recommendation for final selection without BLAKE3 and representative Windows evidence. A BLAKE3 gain in warm compute-limited workloads may disappear under actual I/O or cost other jobs CPU; compare end-to-end behavior under representative concurrency. This checkpoint cannot satisfy Stage 1, and should not be merged as complete. Obtain independent review of exact revision, address confirmed defects, rerun validation and present full recommendation to maintainer, then await explicit algorithm approval. Do not start Stage 2, add production dependency, or close #17.

D10–D13/D20: candidate fingerprint benchmark only; no source validity implementation. D14–D15: verified original/backup resolution remains M4; synthetic originals only. D160–D165: isolated optional experiment, no routine heavy benchmark test, no evidence of pinned local Task or remote checks. Go Task unavailable, checkout unavailable and Python pin unavailable; task check not run; current-main remote CI budget reported exhausted in coordination snapshot (not a pass). No independent reviewer session available here; request a separate reviewer from maintainer/coordinator via PR. No shared documents edited. Branch bench/issue-17-fingerprinting; this README is the task-local reproduction and handoff pointer.
