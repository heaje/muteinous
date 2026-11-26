# Issue #20: supplemental native-format evidence and coordinator handoff

Status: checkpoint, not accepted or closed. Reconciliation commit de5b45338a7f59ec720e934a7ac90b11098c185f retains both original PoC baseline 9ee5d772ac97d0e80f5c3802604f2d77de240ec8 and main 364b400ae4c4b0e00fcbe8b6f91013f9d755d995. Main's two coordinator-reconciled findings files were retained; prior versions remain in history. Production PCM/scratch/WAVE/locking blobs already matched both parents. No main changes, game writes, new format, proprietary fixture, production adapter or loader experiment.

## Reproduction

In a clean checkout of the retained branch, set up the locked Python 3.14.10 project environment according to repository instructions. FFmpeg needs AST and native Vorbis decoding/libvorbis encoding; SoX with Xiph Vorbis plugin is needed only for the independent probe. From the root, using project virtual environment Python:

```sh
PYTHONPATH=src:. python -m experiments.native_ast.shared_edit
PYTHONPATH=src:. python -m experiments.native_ogg.shared_edit
PYTHONPATH=src:. python -m experiments.native_ast.encoded_fidelity
PYTHONPATH=src:. python -m experiments.native_ogg.independent_decode
```

On PowerShell set $env:PYTHONPATH="src;." instead. Run full repository checks separately. Synthetic assets in temporary directories only.

## Actual environment and limitations

Debian 13.3 x86_64, CPython 3.13.5, FFmpeg 7.1.5-0+deb13u1 (package 7:7.1.5-0+deb13u1, configured --enable-gpl), SoX 14.4.2 (14.4.2+git20190427-5+b3), libvorbis0a/libvorbisfile3 1.3.7-3, libogg0 1.3.5-3+b2. Git clone failed: Could not resolve host: github.com. No Go Task, Ruff, mypy, pinned Python runtime or independent reviewer available. Source transferred into isolated partial source directory via GitHub connector and checked against Git blob hashes. Five production modules (pcm.py, scratch.py, storage.py, wav.py, file_lock.py) and the existing experiment modules used for these probes matched merged blobs. Only local compatibility adjustments after hash verification: add future annotations to both FFmpeg wrappers, parenthesize AST wrapper Python 3.14 multi-exception clause (except OSError, subprocess.TimeoutExpired) for Python 3.13. Not committed. Thus supplemental results, not locked checkout or full suite verification. Both shared-edit scripts and both new probes exited 0. Identity probes and automated pytest suites not run. No independent review approval claimed.

## AST

Existing shared_edit passed actual PCMFormat/WaveStorage/Scratch.edit, stereo mask 3, exact samples and loops, one rebuild per affected asset, untouched asset exclusion, malformed/unsupported AST and encoder -n refusal, first/later asset atomicity and scratch cleanup. New encoded_fidelity compares the entire reconstructed native byte array against the original with only the two sample bytes per channel at edited positions set to zero. 8192 stereo PCM16 frames at 32000 Hz, four 2048-frame blocks, 32960 bytes per asset, loop frames 1024..6144.

| Asset | Merged ranges | Edited frames | Bytes outside edited positions identical |
|---|---|---:|---:|
| a | [1001,1257), [4000,4050) | 306 | 31736 |
| b | [2048,2176) | 128 | 32448 |

Pure Python AST parser/writer independent of FFmpeg for this canonical profile. External candidate vgmstream (https://github.com/vgmstream/vgmstream/blob/master/src/meta/ast.c), own parser, blocked layout src/layout/blocked_ast.c, PCM16BE src/coding/pcm_decoder.c; upstream ISC license with third-party dependency review needed. vgmstream-cli unavailable; no external AST decoding verified. Direct PCM edit/selective preservation preferable wherever compatibility permits.

## Ogg

Existing shared_edit passed exact intermediate PCM, structure/comments/bitrate/frame count, grouping, untouched bytes, invalid CRC and unsupported six-channel refusal (first and second), real FFmpeg -n encoder refusal (first and second), atomicity and cleanup. 66150 frames, stereo 44100 Hz, nominal bitrate 128000. Native FFmpeg outside min SNR 30.949 dB, outside max error 0.03549913; guard min SNR 25.690 dB, max error 0.02692842; max requested peak 0.00001420 (start). Source→rebuilt bytes a 27384→20760, b 27432→21108, start 27309→22784, end 27376→22809 (Ogg serial/encoding may vary).

Independent decode: ldd /usr/lib/x86_64-linux-gnu/sox/libsox_fmt_vorbis.so shows libvorbisfile.so.3, libvorbis.so.0, libogg.so.0, not libavcodec. SoX --help-format vorbis reports read support and 16-bit precision. FFmpeg explicitly selects native decoder (-c:a vorbis before -i); explicit source decode matched existing wrapper. FFmpeg native implementation https://github.com/FFmpeg/FFmpeg/blob/n7.1.5/libavcodec/vorbisdec.c ; Xiph also used by encoder but independent of native FFmpeg decoder. SoX commands inspect rate/channels/frames via --i -r/-c/-s and decode with sox -D INPUT -t raw -e floating-point -b 32 -L -; no resample, remix or dither. Quantized decode is not full float fidelity; zeros do not imply exact silence. Native FFmpeg float-PCM passes peak criterion. Outside SNR >=24 dB/max error <=0.08, guard SNR >=18 dB/max error <=0.05, requested peak <=0.0005.

| Asset | SoX peak | Outside min SNR dB | Outside max error | Guard min SNR dB | Guard max error | Cross-decoder max source | Cross-decoder max rebuilt |
|---|---:|---:|---:|---:|---:|---:|---:|
| a | 0 | 31.781227 | 0.0152893066 | 31.433477 | 0.0269165039 | 1.53034925e-5 | 1.53109431e-5 |
| b | 0 | 32.513146 | 0.0204772949 | 30.486739 | 0.0258178711 | 1.53183937e-5 | 1.53034925e-5 |
| start | 0 | 31.181727 | 0.0268249512 | 33.461612 | 0.0226135254 | 1.53183937e-5 | 1.53072178e-5 |
| end | 0 | 30.948767 | 0.0354919434 | 25.690349 | 0.0233154297 | 1.53183937e-5 | 1.53034925e-5 |

All four passed independent decoder fidelity, 66150 frames, stereo, original rate, request and guard fidelity, source/scratch snapshots unchanged. Verify decoder linkage elsewhere. FFmpeg build GPL-enabled; Debian SoX copyright states GPL-2+ or LGPL-2.1+ across files, Xiph libvorbis BSD-3-Clause (installed /usr/share/doc/{ffmpeg,sox,libvorbis0a}/copyright). External executables opt-in only, no Python/production dependency or redistribution recommendation.

## Coordinator review

Reproduce in clean pinned checkout, run full repository checks including tests and identity probes; independent review/fix/validation cycle remains open. Verify probe code style/type checking in locked environment and decoder independence/precision. Reconcile main findings only after acceptance; preserve distinction between exact AST byte preservation and bounded lossy Ogg feasibility; no external AST decoder run. Approved priority is highest-fidelity compatible reconstruction preserving unaffected encoded bytes and avoiding additional loss wherever possible. No production recommendation for lossy re-encoding, no game compatibility or loader claim. Issue remains open.

## Resumed verification checkpoint (2026-11-25)

Fresh evidence below supersedes earlier handoff statements that vgmstream had not been executed and that locked Windows checks were unavailable. The earlier Debian 13/Python 3.13 report above remains historical and is not merged into these measurements. This checkpoint was executed on the requested worktree at starting SHA `8de700a3ee7234a03e0b3bfbb1fcfe6e2e72f7ea`; no push, main merge, game write, proprietary asset or loader test occurred.

### Environment and tools

- Windows 11 Pro build `10.0.26300`; `task setup` succeeded. CPython `3.14.10` in `.venv`; Task `3.54.0`; uv `0.13.9`; Ruff `0.17.6`; mypy `2.4.1`; pytest `9.2.0`; pytest-xdist `3.8.0`.
- FFmpeg `n7.1.5-12-g1fdbca85aa-20260731`, WinGet `BtbN.FFmpeg.GPL.7.1`, GPL static build (`--enable-gpl --enable-version3`). FFmpeg project license is LGPL by default with GPL-licensed components/build options; this tested build is GPL-configured and is not recommended for redistribution with the application.
- Windows SoX `14.4.2`, WinGet `ChrisBagwell.SoX`; the Xiph Vorbis read path was exercised by the SoX probe.
- Official vgmstream GitHub numbered release `r2168` (CLI reports `Oct 25 2026`), downloaded `vgmstream-win64.zip` into a unique empty directory. Official release API exposes the archive SHA-256 `692d45070852a35c1fa42726aa3c9de528e44eec925d37d99b1074256b99a229`, matching the downloaded file. The upstream `COPYING` (both the `r2168` source and archive copy) grants use/copy/modify/distribution for any purpose with or without fee subject to retaining the copyright and permission notices, and includes third-party copyright attributions; this is the ISC license text. The README has no licensing section. The Windows CLI zip contains `avcodec-vgmstream-63.dll`, `avformat-vgmstream-63.dll`, `avutil-vgmstream-61.dll`, `swresample-vgmstream-7.dll` (FFmpeg), `libcelt-0061.dll`, `libcelt-0110.dll` (CELT), `libmpg123-0.dll` (mpg123), `libspeex-1.dll` (Speex), and `libvorbis.dll` (Vorbis), plus the CLI. It has no separate third-party license files/notices beyond `COPYING`; notably the upstream source tree has `ext_libs/licenses` notices, but these are not in this zip. Those source-tree texts identify FFmpeg LGPLv2.1/LGPLv3 license texts, mpg123 LGPLv2.1 and GPLv2 sections, and Xiph-style BSD terms for CELT, Speex, Vorbis and Ogg. This is a notice-level inventory, not a per-binary license determination; separate review is still needed before redistribution. No third-party binary is in the repository.
- The two old compatibility patches for CPython 3.13 were not needed: all six probes, the independent AST experiment, tests, Ruff and mypy ran under locked CPython 3.14.10. The Windows timeout-control `except` syntax also executed directly without modification.
- WSL Ubuntu `26.04.1 LTS`; `ffmpeg 7:8.0.1-3ubuntu2`; `sox 14.7.0.9+ds1-1` (SoX_ng), `libsox-fmt-all 14.7.0.9+ds1-1`, `libvorbis0a/libvorbisfile3 1.3.7-3build2`, `libogg0 1.3.6-2`. This Ubuntu variant names the dynamic plugin `libsox_ng_fmt_vorbis.so`; `ldd` showed `libvorbisfile.so.3`, `libvorbis.so.0`, `libogg.so.0`, and **no `libavcodec`**. FFmpeg decoder listing showed separate `vorbis` (native) and `libvorbis` decoder entries; the Ogg wrapper explicitly invokes `-c:a vorbis`. Linux tools are evidence for decoder linkage only, not a Linux shared-edit run.
- Licensing recorded for tooling: FFmpeg tested GPL build; SoX is GPL-2+ or LGPL-2.1+ depending on files/build; Xiph Vorbis BSD-3-Clause; vgmstream ISC plus third-party components. Debian/Ubuntu package copyright files apply to those WSL packages. No redistribution or production dependency recommendation.

### Fresh commands and results

From repository root, Windows PowerShell:

```powershell
task setup
winget install --id BtbN.FFmpeg.GPL.7.1 --exact --accept-source-agreements --accept-package-agreements
winget install --id ChrisBagwell.SoX --exact --accept-source-agreements --accept-package-agreements
task check
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path
$env:PYTHONPATH = "src;."
& .venv/Scripts/python.exe -m experiments.native_ast.probe
& .venv/Scripts/python.exe -m experiments.native_ast.shared_edit
& .venv/Scripts/python.exe -m experiments.native_ast.encoded_fidelity
& .venv/Scripts/python.exe -m experiments.native_ogg.probe
& .venv/Scripts/python.exe -m experiments.native_ogg.shared_edit
& .venv/Scripts/python.exe -m experiments.native_ogg.independent_decode
& .venv/Scripts/python.exe -m experiments.native_ast.independent_decode --vgmstream-cli C:/path/to/private-vgmstream-dir/vgmstream-cli.exe
& .venv/Scripts/python.exe -m pytest tests/integration/test_native_ast_prepare.py tests/integration/test_native_ogg_prepare.py tests/unit/test_native_ast.py -q
& .venv/Scripts/python.exe -m ruff check experiments
& .venv/Scripts/python.exe -m ruff format --check experiments
& .venv/Scripts/python.exe -m mypy experiments
```

The vgmstream archive was fetched from `https://github.com/vgmstream/vgmstream/releases/download/r2168/vgmstream-win64.zip` into a new empty temporary directory. WSL installation and linkage commands:

```powershell
wsl.exe -d Ubuntu -u root -- apt-get update
wsl.exe -d Ubuntu -u root -- apt-get install -y ffmpeg sox libsox-fmt-all
wsl.exe -d Ubuntu -- ldd /usr/lib/x86_64-linux-gnu/sox_ng/libsox_ng_fmt_vorbis.so
wsl.exe -d Ubuntu -- ffmpeg -hide_banner -decoders
```

The new `experiments/native_ast/independent_decode.py` takes the downloaded CLI path as an argument; it does not import or parse the downloaded executable. It verifies vgmstream JSON metadata and decoded PCM16 WAVs for original and edited `a`/`b` AST outputs. Original and edited files were independently reported as 32 kHz stereo, 8,192 samples, loop frames 1,024–6,144, and vgmstream's WAV samples matched the expected PCM byte-for-byte. Grouped/touching edits were checked; unaffected frames were exact; source files and disposable staging were unchanged/cleaned. This is an independent AST decode and native metadata validation success for the canonical fixture; vgmstream uses its own AST parser/PCM decoder rather than FFmpeg or this repository's parser.

All six requested probes exited 0 on the pinned Windows environment. AST source extraction/rebuild, refusal paths and all-or-nothing behavior passed. Fresh encoded-fidelity measurements: asset `a`, 306 edited frames, 31,736 bytes outside edited sample positions identical; `b`, 128 edited frames, 32,448 bytes outside edited positions identical (both assets 32,960 bytes). Ogg shared editing passed structure/comments/bitrate/frame count, grouping, requested silence, untouched source, corruption/unsupported-profile refusal and first/later asset encoder failure/cleanup. Fresh FFmpeg metrics remain consistent with earlier Windows figures: identity no-edit SNR `33.020 dB`, max error `0.01706610`; edited outside-region minimum SNR `30.949 dB`, maximum error `0.03549913`; guard minimum SNR `25.690 dB`, maximum error `0.02692842`; largest requested-range peak `0.00001420`. This remains lossy feasibility only; do not prefer Ogg re-encoding over preserving encoded bytes/direct PCM when compatible.

Fresh SoX/Xiph Ogg results all met the existing limits. SoX reported 16-bit precision. Max SoX-vs-FFmpeg-native-float sample difference observed was `1.53183937e-5`, near but slightly above a nominal PCM16 half-step `1/65536 ≈ 1.52587891e-5` (the cross-decoder difference includes implementation differences). SoX produced zero for source samples where FFmpeg native float output was nonzero: `a=10`, `b=8`, `start=6`, `end=6`. Thus SoX zero is not proof of exact float silence. SoX outside SNR minimum `30.948910 dB`, outside max error `0.0354919434`; guard SNR minimum `25.690633 dB`, guard max error `0.0233154297`; requested-region peaks were all zero at SoX precision. These measurements remain well within the existing 24 dB/0.08, 18 dB/0.05 and 0.0005 gates, not a universal transparency claim.

The required tests passed explicitly: `30 passed in 1.74s`. Experiment lint/type checks passed: Ruff check clean; Ruff format clean (18 experiment files); mypy `Success: no issues found in 16 source files`. The final `task check` passed: Ruff, format, mypy on 79 configured sources, decision-ID check, **551 tests passed** (31.506 sec pytest session), package sdist/wheel build and isolated wheel import, version preview. This Windows run used 24 xdist workers and is not evidence of the D161 two-vCPU target. The build emitted existing manifest warnings that `experiments/` and three native tests are intentionally excluded from source distribution; it completed successfully. An earlier full pass in the same session reported 27.369 sec.

Initially, separate experiment linting found `experiments/native_ogg/independent_decode.py` needed Ruff formatting and one `float` return annotation path failed mypy (`no-any-return`). Both were minimally corrected; final experiment lint/type checks and all six probes passed. No compatibility-only Python patches were made.

### D-number/acceptance evidence and remaining limits

- **D05–D08 (including approved 2026-11-25 fidelity amendment):** canonical PCM16 AST remains sample-exact and preserves every unaffected native byte; Ogg's extra lossy generation is measured, documented and not recommended as a production default. No production technique/codec choice is made.
- **D16/D24:** shared `PCMFormat`/`WaveStorage`/`Scratch.edit`, grouped required edits, affected-only rebuilding, exact unaffected AST audio, and corrupt/unsupported/reconstruction refusal with source/scratch cleanup were exercised. Ogg fidelity is thresholded and requested intervals are checked.
- **D132–D135:** generated fixtures only; no title-specific assumptions, installation writes, loader experiment or game-compatibility claim.
- **D160/D161:** full local required check and targeted tests passed; no remote CI or two-vCPU performance claim. CI timeout negative-control remains unrun.
- Issue #20 criteria 1–2 now have actual shared-editor native reconstruction and independent lossless AST decode evidence. Criteria 3–4 remain constrained as written: no game writes/proprietary fixtures/compatibility claims; tooling, platform, license, limitations and next steps are documented. External independent review/acceptance is still pending.

Independent review (fresh-context reviewer subagents, read-only, against implementation commit `8b3b3baa2ab9ca0312abc314f1b69b56c6fb6d3d`): reviewer 1 (AST decoder check, tests, AST code) and reviewer 2 (Ogg code, decoder independence, measurements/claims, Issue #20 criteria, reproduction) each reported no actionable findings. Reviewers re-ran the 30 targeted native tests, Ruff and mypy on `experiments/`, `task check` (551 tests), the Ogg probes (numbers matched), WSL `ldd` (libvorbisfile/libogg, no libavcodec) and the vgmstream r2168 independent AST decode (sample-exact, both assets, rate/channels/frames/loops matched). The licensing follow-up above directly checked the upstream `r2168` and archive `COPYING`, the README, archive entries, and source-tree third-party license texts. It records the upstream ISC grant and a notice-level inventory; a separate review is still needed before any redistribution. Xiph libvorbis BSD-3-Clause was confirmed from the Debian copyright file in WSL.

Not run: remote GitHub CI, macOS checks, Linux native shared-edit probes, game/loader compatibility or real installations. SoX Linux linkage was checked under Ubuntu 26.04, not the earlier historical Debian 13.3. Arbitrary AST profiles, other vgmstream/FFmpeg builds and broader native compatibility remain unsupported/unverified. No second independent Ogg decoder was added beyond the SoX/Xiph cross-decoder evidence already present.

### Findings-update draft for coordinator review (not yet applied to shared findings)

> On the retained `poc/native-formats-issue-20` branch, locked Windows 11/Python 3.14.10 checks now pass at the recorded local SHA. Both canonical synthetic AST source and edited outputs decode sample-exactly with official vgmstream `r2168`, including 32 kHz stereo, 8,192 frames, loop frames 1,024–6,144. AST edits preserve all native bytes outside edited PCM positions. Ogg remains a separate lossy-only feasibility result; SoX/Xiph independently decodes the four outputs, with bounded synthetic fidelity measurements and a demonstrated 16-bit precision caveat. No production codec strategy, game compatibility or loader acceptance is implied. Keep this evidence branch-local pending independent review; reconcile main findings only after coordinator acceptance.

Independent review and any confirmed-finding correction cycle remain open. Do not push this checkpoint until the coordinator's requested review gate.
