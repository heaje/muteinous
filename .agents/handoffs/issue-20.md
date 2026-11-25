# Issue #20 / draft PR #25 handoff — AST and Ogg specimens

Related: [Issue #20](https://github.com/heaje/muteinous/issues/20), [draft PR #25](https://github.com/heaje/muteinous/pull/25), [PR #27](https://github.com/heaje/muteinous/pull/27).

## Branch and ownership

Branch: `m1/issue-20-native-format-poc`, based on `b2ee60a731e506fc2b34083eedf2edd59b947a67`. At the start of fix round 3, HEAD `ebff61ba7d46e730316f6e328eba951447e9da77` matched `origin/m1/issue-20-native-format-poc`; the AST and Ogg specimens were already committed and pushed. The round-3 corrections below are currently **uncommitted worktree changes**. The supervisor owns commit/push; this implementer did not rebase, commit, or push. Remove this temporary handoff after the PR/task is complete.

No upstream-owned source, scripts, upstream tests, `docs/audio-storage.md`, architecture/coverage docs, or `uv.lock` were changed.

## Round-3 corrections

- Ogg lossy verification now checks unedited boundary guard bands against the source using separate 18 dB SNR / 0.05 maximum-error limits. Measured real-libvorbis guard bands had minimum 31.092 dB SNR and maximum error 0.01743349. A request with no verified unedited frames refuses unless it genuinely edits the full clip; the full-clip case still checks edited silence.
- Ogg parsing uses a once-built table-driven CRC, retains only the three headers, validates/counts/discards audio packet bodies, and enforces a 100,000 total-packet limit. The README documents the whole-file buffer and caps.
- Nominal bitrate drift is limited to 10% relative; ASCII Vorbis field-name validation/case comparison is Unicode-safe.
- Added negative tests for rebuilt native AST/Ogg validation, an isolated Ogg SNR rejection, path-safe AST suffixes, and both-asset-order refusal coverage across both specimens.
- `MANIFEST.in` excludes the four experiment-only native tests from the sdist; sdist extraction no longer contains them.

## Local verification

Windows 11, CPython 3.14.10, FFmpeg `n7.1.5-12-g1fdbca85aa-20260731`.

- Native AST/Ogg tests: **114 passed in 3.20s**, no skips.
- `cmd /v:on /c "task.cmd check & echo exit=!errorlevel!"`: **exit 0**; lint, format check (38 files), mypy (36 source files), decision IDs, **285 passed in 45.86s**, package build/import, and version preview passed.
- Extracted sdist inventory: no `test_native_*.py`; the remaining sdist suite: **171 passed in 73.17s**, no skips.
- Manual scripts, each exit 0: `experiments.native_ast.probe`, `experiments.native_ast.shared_edit`, `experiments.native_ogg.probe`, `experiments.native_ogg.shared_edit`. See the experiment READMEs for outputs. Ogg identity: 66,150 frames, 128,000→128,000 bit/s, 33.020 dB SNR, max error 0.01706610, 27,390→26,507 bytes. Edited guard minimum: 31.092 dB / 0.01743349; outside minimum: 31.636 dB / 0.02047877; edited cores were silent.
- Negative controls, deliberately failing and restored: removing rebuilt-native validation made all four AST/Ogg order cases fail their expected-refusal assertion (**4 failed, 51 deselected**); disabling the Ogg outside-SNR condition made the dedicated SNR test fail its expected-refusal assertion (**1 failed, 22 deselected**).
- No remote CI result was checked or claimed.

## Limits

The specimens remain synthetic feasibility experiments for a loose AST PCM file and loose Ogg Vorbis file, not production adapters or engine banks. No game-loader acceptance, independent decoder, Linux/macOS shared-edit, other FFmpeg build, or licensing conclusion is established. The tested FFmpeg binary is GPL-configured; do not redistribute it with Muteinous.
