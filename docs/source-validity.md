# Source fingerprinting and scan validity

The source-validity foundation implements the content evidence and targeted
invalidation contracts in D10–D13 and D20. Plugin-owned `SourceAssetId`,
`SourceFingerprint`, `SegmentAssets`, and `AssetFingerprints` remain the only
metadata representation; no native asset structure is interpreted by shared
code.

## Hashing and resource policy

`fingerprint_file` streams a plugin-selected file boundary through one reused
256 KiB buffer (unbuffered `readinto`) using BLAKE3 1.0.11 with `max_threads=1`.
The file-content read buffer is therefore fixed in size. The returned opaque string is prefixed
`blake3:` so it cannot compare equal to evidence from a different algorithm.
`fingerprint_assets` visits supplied assets synchronously and sequentially.
The implementation creates no worker pool, does not retain file contents,
does not modify files, and lets open/read failures propagate so callers cannot
mistake unavailable evidence for a valid fingerprint.

The approved Windows benchmark evidence in
[`benchmarks/fingerprinting/README.md`](../benchmarks/fingerprinting/README.md)
found BLAKE3 one-thread hashing faster than SHA-256 for large assets on its
test machine; corrected small-asset runs showed broadly similar results for
small files and a modest advantage for the largest tested small-file profile.
Results are hardware/storage-specific and the benchmark's CPU competitor was
synthetic, not a real application job. One hashing operation therefore has a
clear bounded memory and thread budget, with no implicit fan-out that could
multiply across concurrent callers. The narrow scheduled verification adapter in
`infrastructure/sources/scheduled.py` submits sequential jobs with explicit
`cpu` and `source-io` resources. The shared queue owns their capacities and
holds both slots until physical work stops. Queue owners route dispatch
validation through `validate_source_plan` with the caller's original-context
check; validation checks location and resolved context, not asset metadata or
content. The worker rechecks that context before hashing and before returning results. The check must
attest the selected assets as originals; paths and matching digests cannot
establish provenance. Missing individual assets are isolated during hashing.
The submitted asset selection and dependency maps are copied, not persisted.
When constructing the shared queue, use `source_verification_capacities`
to supply a default `source-io` capacity of two. Each job still hashes its
assets sequentially and consumes one shared CPU slot and one source-I/O slot;
two independent jobs can run concurrently when both resources permit it.
The helper preserves explicitly configured capacities (including zero), and
does not invent a CPU capacity or change unrelated resources. Queue owners can
also use the existing `set_capacity` override; persistence and settings UI
remain later integration work. No independent worker pool is created.
The two-worker default is an approved conservative starting point, not a
hardware-specific optimum. Development benchmark measurements remain outstanding;
user-requested calibration and automatic tuning are not part of this slice.

Hashing compares path metadata with the opened file's metadata before reading,
then compares size, modification time, available identity and byte count after
reading and checks the path again after closing. Detectable changes reject the
fingerprint. Check/open and check/return races and undetectable same-metadata
changes remain possible; these checks are rejection evidence, not a snapshot.
Cancellation is checked between reads and assets; blocked reads may delay
physical termination. Byte progress is reported without a percentage; the
asset count is the number attempted out of the supplied selection. Byte updates
are throttled within a file. The existing queue rejects cancelled and late
results. No retries or separate scheduler are introduced.

### Read size and buffer reuse

The buffer is a bounded-memory choice: one 256 KiB buffer is reused across
all assets of each sequential scheduled worker (and synchronous asset batch).
Standalone fingerprint calls allocate their own buffer; callers supplying a
buffer must use it exclusively and sequentially. Each file gets new hash state. The storage integrity helper in
`infrastructure/storage/_filesystem.py` uses a 1 MiB read block as a precedent
for bounded streaming, but the source fingerprinter uses a different size based
on its separate read-size sweep
([`benchmarks/fingerprinting/chunk_size_sweep.py`](../benchmarks/fingerprinting/chunk_size_sweep.py)),
not from the algorithm-selection benchmark. Measured on one Windows machine
(CPython 3.14, warm page cache,
synthetic random data, median of 7 interleaved runs): a `read(n)` loop with
`n` = 1 MiB hashed a 1 GiB file at about 3,460 MB/s versus about 5,650–5,840
MB/s at 256–512 KiB, and hashed 2,000 × 64 KiB files at about 225 MB/s versus
about 1,360 MB/s at 64 KiB. Each `read(n)` allocates a new `n`-byte object;
the cost appears allocation-related, though the mechanism was not isolated.
Reusing one buffer with `readinto` removed the penalty (about 6,000 MB/s on the
large file at 1 MiB) but still pays to allocate and zero the buffer per call,
so a 1 MiB buffer reached only about 324 MB/s on the small files. A 256 KiB
reused buffer measured about 5,755 MB/s (large) and about 1,341 MB/s (small),
within about 5% of the best large-file result without the small-file cliff.

The production function was then compared with the previous 1 MiB `read(n)`
implementation on the same data: about 6,010 versus 3,400 MB/s (1 GiB file) and
about 1,190 versus 220 MB/s (2,000 × 64 KiB files). Digests were identical.

Limits: warm cache only (no cold-storage run), one machine, synthetic data, no
Linux/macOS measurement; the allocator-related cliff may sit elsewhere on other
platforms or Python builds. Throughput is not a tested contract; tests assert
only bounded reads and unchanged digests. Revisit if real asset mixes are
dominated by very large or very small files, or if cold-storage runs disagree.

## Dependency, license and packaging evidence

The project manifest declares `blake3` without a version constraint, following
repository convention; `uv.lock` selects BLAKE3 1.0.11. The locked
release provides CPython 3.14 wheels for Windows, Linux manylinux and macOS;
wheel availability alone is not proof of successful runtime behavior. This
implementation's Windows locked-environment tests and isolated-wheel probe
verify actual import and runtime use. Separate scratch research verified the
1.0.11 wheel install, API/vector behavior, single-thread option and bounded
64 MiB streaming on Windows and WSL2 Linux. A minimal Windows PyInstaller
one-file smoke build worked without hidden imports; this is a packaging
assessment, not an application installer or release test. The Linux
portability and macOS portability jobs each passed 530 portable tests on
[PR #43 run 45863237303](https://github.com/heaje/muteinous/actions/runs/45863237303)
and [PR #46 run 45871392966](https://github.com/heaje/muteinous/actions/runs/45871392966).
The portable set includes
`test_fingerprint_is_deterministic_and_algorithm_distinguishable`, exercising
the locked BLAKE3 import and fingerprint runtime, and
`test_changed_dependency_identity_invalidates_only_dependent_result`, covering
portable validity comparison. This is selected Linux/macOS runtime evidence,
not throughput benchmark evidence: macOS and native-Linux fingerprint
benchmarks remain not done. No application installer infrastructure is
introduced.

The upstream 1.0.11 source distribution's locked Rust graph contains 30 crates
with permissive declared license expressions (MIT/Apache, CC0/MIT-0, or the
stated Unicode-3.0 combination); the audit found no copyleft license. The
Python wrapper declares CC0-1.0 OR Apache-2.0 and Rust BLAKE3 is CC0-1.0 OR
Apache-2.0 OR Apache-2.0 WITH LLVM-exception. MIT/Apache redistribution
obligations still apply when those alternatives are relied on: preserve
required copyright/permission notices and applicable Apache license/NOTICE
material. This is a technical inventory, not legal advice.

The wrapper's build manifest enables Rust BLAKE3 `mmap` and `rayon` features
and has Rayon as a dependency. Production hashing calls only `blake3()` with
`max_threads=1`, performs explicit bounded reads, and never calls mmap APIs,
`AUTO`, or other implicit parallel modes; therefore Rayon is compiled into the
upstream extension but not used by this hashing policy. The lock's target-
conditioned crates are conservatively inventoried, not all asserted to be
linked into each wheel. The audit did not run `cargo-license`, parse the
CycloneDX SBOM, verify every crate's source `NOTICE`/license file, or inspect
binary symbols/features. No checked-in third-party notice policy exists.
Before redistributing a frozen application, maintainers should confirm the
actual redistribution graph's notice obligations and provide required license
texts/notices; this PR does not invent notice or installer infrastructure.

The audit found no GitHub-published security advisories as of 2026-11-25.
Repository vulnerability alerts and automated security fixes were enabled and
verified on 2026-11-26; the follow-up advisory recheck is recorded below. This
is not a guarantee against undisclosed or future vulnerabilities.

Plugins choose logical asset identities and exact content boundaries, and
provide each scan's complete segment-to-asset mapping. They may fingerprint a
reliably bounded logical asset or use its enclosing physical file / a broader
reliable scope when extraction boundaries are uncertain. Shared dependencies
and segments depending on multiple assets are represented by the existing
many-to-many `SegmentAssets` mapping. Hashing accepts paths, allowing a plugin
to hash an extracted asset while it is available; it does not cache or
permanently duplicate extracted bytes.

## Validity and provenance

`compare_source_evidence` retains only results whose prior and current
dependency sets match and whose every dependency has an equal prior/current
content fingerprint. Missing fingerprints, changed fingerprints, empty
dependency sets, or changed associations invalidate the affected segment.
When any result lacks a dependency record in either scan, the relationship
between source changes and results cannot be isolated, so all results supplied
to that comparison are invalidated. Missing, unreadable, or otherwise
unhashable current files do not produce current evidence: fingerprinting raises
and the caller must refuse reuse (and may broaden invalidation if the affected
scope cannot be established). `require_source_validity` rejects any invalidated
result set before source-bound edits are used. Matching content-item/segment
IDs and unchanged filesystem metadata are never substitutes for recomputing
the content fingerprint.

**Caller precondition:** before invoking these operations, the caller must
already have established that the paths identify the applicable unmodified
original sources. The code does not detect provenance, resolve installed
replacements, or locate/verify backups. Missing or ambiguous original sources
must be rejected by the caller. D14–D15 verified-original and backup access
remain later M4 work. A source fingerprint is evidence of content validity
only; it does not authorize installation or any write to user-owned content.

This is a narrow scheduled foundation only. Automatic rescanning, cache persistence,
comprehensive scan/preview workflow integration, native-format discovery/decoding, verified-original
resolution, installation-state management, and installation authorization are
out of scope.

## Follow-up benchmark and advisory recheck (2026-11-26)

The existing `chunk_size_sweep.py` was rerun unchanged at the recorded main
baseline `a46bada876461bd60446ff5599159fbf017c57a4`, with its default 1,024 MiB
file size and seven interleaved repeats. Both runs are **warm-cache**, not cold:
the script hashes the large file once to establish its reference digest before
timing and pre-reads all 2,000 small files. The 1 GiB working set is also below
available RAM on both machines. On Windows no cache-flush method was used; in
WSL2, unprivileged `echo 3 > /proc/sys/vm/drop_caches` failed with permission
denied. Neither run justifies a cold-cache label.

Windows reported an AMD Ryzen 9 9900X (12 cores/24 logical CPUs), 32 GiB RAM,
Windows 11 Pro build 26300, CPython 3.14.10 and `blake3` 1.0.11. `Get-ComputerInfo`
identified the product as Windows 10 Pro, version 2009, while the OS API and
Python platform report Windows 11; the build number agrees at 26300. The
script's temporary data was on C: (NTFS, WD_BLACK SN770 1 TB NVMe). The read-only
measurement command was
`.\.venv\Scripts\python.exe -I benchmarks/fingerprinting/chunk_size_sweep.py 1024`.
The script has no cold-mode option: its reference-digest pass warms the fixture
before timing. A fixture larger than RAM would leave uncontrolled partial
residency and repeated mixed-cache reads, not a defensible cold measurement, so
no such run was labeled or reported as cold.
In WSL2 Ubuntu 26.04.1, the same host CPU exposed 24 logical CPUs and about
15.4 GiB guest RAM; the kernel was
`6.6.87.2-microsoft-standard-WSL2`. The temporary data was on the distro's
ext4 virtual disk (`/dev/sdd`), not `/mnt/c`; hardware storage beneath that
virtual disk was not established. CPython 3.14.10, `blake3` 1.0.11 and
`psutil` 7.2.2 were installed in a throwaway home-directory venv. Because the
distro lacked `python3-venv`/ensurepip, a user-local uv bootstrap was used; no
system package or setting was changed (uv 0.13.10). The benchmark command was
`$HOME/muteinous-bench-17-venv/bin/python -I $HOME/muteinous-bench-17/benchmarks/fingerprinting/chunk_size_sweep.py 1024`
with `TMPDIR` set to a directory under the distro home.

The captured console output and complete 28-row median/min/max tables are
retained as [Windows raw output](../benchmarks/fingerprinting/windows-2026-11-26-chunk-sweep.txt),
[Windows CSV](../benchmarks/fingerprinting/windows-2026-11-26-chunk-sweep.csv),
[WSL raw output](../benchmarks/fingerprinting/wsl-ubuntu-2026-11-26-chunk-sweep.txt)
and [WSL CSV](../benchmarks/fingerprinting/wsl-ubuntu-2026-11-26-chunk-sweep.csv).
For the 1 GiB file, 256 KiB `readinto` measured 5,870 MB/s (5,780–5,904) on
Windows and 10,059 MB/s (10,019–10,094) in WSL2; current 1 MiB `read` measured
3,434 (3,365–3,486) and 10,092 (10,026–10,164) MB/s, respectively. For
2,000 × 64 KiB files, 64 KiB `readinto` measured 1,603 (1,456–1,627) MB/s on
Windows and 6,850 (6,505–6,869) MB/s in WSL2; current 1 MiB `read` measured
224 (222–226) and 6,631 (6,424–6,658) MB/s. All values are warm-cache
medians with seven repeats; the WSL2 result is virtualized and is not a native
Linux comparison. These single-machine synthetic results do not overturn the
existing Windows-only read-size conclusion.

On 2026-11-26 the public GitHub Global Advisory Database queries
`gh api '/advisories?ecosystem=pip&affects=blake3'` and
`gh api '/advisories?ecosystem=rust&affects=blake3'` each returned an empty
list. The PyPI JSON metadata at `https://pypi.org/pypi/blake3/json` reported
1.0.11 as latest (same as the lock), released 2026-10-08, not yanked; its
top-level vulnerabilities list was empty. No advisory was found for the locked
version in these sources. At the time of this advisory query, Dependabot alerts
were disabled and were not used as evidence; repository alerts and automated
security fixes were enabled and verified on 2026-11-26. This check cannot
establish absence of undisclosed or future vulnerabilities.

**Not done:** macOS was not measured; completing it requires a maintainer-
authorized throwaway `macos-26` runner job, which was not created. Native Linux
was not measured; WSL2 is not a substitute. A genuinely cold-cache rerun also
remains outstanding because this script warms its own fixtures and this
environment did not permit an unprivileged cache drop. The results do not
change production code or algorithm selection.
