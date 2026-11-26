# Source fingerprinting and scan validity

The source-validity foundation implements the content evidence and targeted
invalidation contracts in D10–D13 and D20. Plugin-owned `SourceAssetId`,
`SourceFingerprint`, `SegmentAssets`, and `AssetFingerprints` remain the only
metadata representation; no native asset structure is interpreted by shared
code.

## Hashing and resource policy

`fingerprint_file` streams a plugin-selected file boundary through one reused
256 KiB buffer (unbuffered `readinto`) using BLAKE3 1.0.11 with `max_threads=1`.
Memory per call is therefore fixed at the buffer size. The returned opaque string is prefixed
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
multiply across concurrent callers. This does **not** establish an
application-wide concurrency limit: when wired into jobs, the job owner must
declare/occupy the appropriate queue resources for the complete physical hash
work. Hashing is not a dispatch-time validator; validators remain quick and
read-only, and queue resource occupancy lasts until the worker's physical
operation stops. No future scan/job integration or speculative global
semaphore is introduced here.

### Read size and buffer reuse

The buffer size and reuse strategy were chosen from a read-size sweep
([`benchmarks/fingerprinting/chunk_size_sweep.py`](../benchmarks/fingerprinting/chunk_size_sweep.py)),
not from the algorithm benchmark, which fixed 1 MiB reads without comparing
other sizes. Measured on one Windows machine (CPython 3.14, warm page cache,
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

The manifest constraint and generated lock select BLAKE3 1.0.11. The locked
release provides CPython 3.14 wheels for Windows, Linux manylinux and macOS;
wheel availability alone is not proof of successful runtime behavior. This
implementation's Windows locked-environment tests and isolated-wheel probe
verify actual import and runtime use. Separate scratch research verified the
1.0.11 wheel install, API/vector behavior, single-thread option and bounded
64 MiB streaming on Windows and WSL2 Linux. A minimal Windows PyInstaller
one-file smoke build worked without hidden imports; this is a packaging
assessment, not an application installer or release test. macOS runtime
verification is pending the required `macos-26` CI portability job; no
application installer infrastructure is introduced.

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
Continue ordinary dependency update and security-alert review under the
repository's existing dependency maintenance policy; this is not a guarantee
against undisclosed or future vulnerabilities.

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

This is a foundation only. Automatic rescanning, cache persistence, scan/preview
workflow integration, native-format discovery/decoding, verified-original
resolution, installation-state management, and installation authorization are
out of scope.
