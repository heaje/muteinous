# Streaming reads: `read(n)` at 1 MiB is slow; reuse a buffer
Status: active
Last verified: 2026-11-25
Related: [Issue #17](https://github.com/heaje/muteinous/issues/17), [PR #38](https://github.com/heaje/muteinous/pull/38); `src/muteinous/infrastructure/sources/fingerprints.py`; [`docs/source-validity.md`](../../docs/source-validity.md)
Retire/promote when: PR #38 merges and the source-validity doc carries the evidence, or a cross-platform/cold-cache run contradicts it.

## Finding and limitations
On the Windows development machine (CPython 3.14, warm cache, synthetic data), a `file.read(1 MiB)` loop hashing with BLAKE3 ran at about 3,460 MB/s on a 1 GiB file, versus about 5,650–5,840 MB/s at 256–512 KiB, and about 225 MB/s on 64 KiB files, versus about 1,360 MB/s at 64 KiB. Each `read(n)` allocates an `n`-byte object per call; the cost looks allocation-related but the mechanism was not isolated. A reused `bytearray` with unbuffered `readinto` avoids it. Even then, a 1 MiB buffer is costly for many tiny files because it is allocated and zeroed per call, so 256 KiB was chosen as the compromise. Other streaming loops (audio scratch, installers) may share this cost; this was not checked.

Not measured: cold cache, Linux/macOS, other allocators. Do not treat as a general constant.

## Reproduction / evidence
`python -I benchmarks/fingerprinting/chunk_size_sweep.py 1024` from the project venv. Numbers and caveats are recorded in `docs/source-validity.md` under "Read size and buffer reuse".

## Recommendation
For new bounded streaming code over local files, prefer a reused buffer with `readinto` at 64–256 KiB over `read(n)` with a large `n`, and verify with a quick sweep on representative data.
