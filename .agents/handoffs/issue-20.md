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
