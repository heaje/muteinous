# Vorbis lossy round-trip evidence
Status: active for the synthetic stereo/44.1-kHz experiment only
Last verified: 2026-11-24
Related: [#20](https://github.com/heaje/muteinous/issues/20), [Ogg Vorbis experiment](../../experiments/native_ogg/README.md)
Retire/promote when: the isolated experiment is removed or replaced with a production native adapter and independent compatibility evidence.

## Finding and limitations

With the observed Windows FFmpeg/libvorbis build, a no-edit Ogg Vorbis identity re-encode is measurably lossy even though it retained the source's 128,000-bit/s nominal bitrate, user comments, stereo/44.1-kHz profile, and 66,150 decoded frames. The manual probe measured 33.020 dB SNR and 0.01706610 maximum absolute sample error versus the original Ogg's decoded PCM. `expected_frames` checks the container's final granule only, not independently decoded length; preparation catches mismatches because extracted PCM must equal the verified original. Edited outputs pad requested frame ranges by up to 224 frames, clamped independently to each segment before per-asset merging, require every decoded requested frame to be <=0.0005 peak, and measure fidelity outside/near the padded spans. A lossy specimen whose segment-clamped pad cannot silence a requested edge refuses rather than widening into neighboring audio. The current four-asset real run measured minimum guard SNR 25.690 dB and maximum guard error 0.02692842; policy uses 18 dB / 0.05 for guards and 24 dB / 0.08 farther away. These are synthetic/build-specific thresholds, not codec guarantees.

**Author-reported historical evidence, not reproducible from artifacts in this branch:** unpadded real rebuilds leaked codec ringing into requested spans, with peaks of 0.02020272 (interior), 0.01467311 (clip start), and 0.00938927 (clip end), all above the 0.0005 limit. On an 8-frame-step padding sweep from 192 through 224, the first candidate meeting a tenfold margin target (peak <=0.00005) was 224 frames; its maximum measured peak was 0.00001828, about 27x below the limit. At 216 frames the maximum was 0.00005452. Padding is fixture-specific: broadband noise with a one-frame interior edit reportedly left a requested-range peak of 0.1055 and was refused. A separate 2,048-frame calibration reportedly yielded zero peaks on three synthetic spans. The manual shared-edit run with the selected 224-frame pad measured full-request peaks of 0.00000000 (asset a), 0.00000000 (b), 0.00001420 (start-clamped edit), and 0.00000000 (end-clamped edit). The historical clip-endpoint measurements do not establish that a neighboring segment may be edited: current preparation clamps to each segment, and a segment-edge lossy leak causes refusal if the requested-range gate fails. The gates also tolerate a global +5% gain (about 26 dB SNR) by policy; their thresholds are not perceptual-transparency guarantees. Production must size padding from its codec window, upstream margin/fade policy, and segment limits.

## Required test scope after trim

Required tests cover only safety-critical shared-editor integration behavior: exact frame mapping and AST scratch edits, grouped per-asset rebuilding, segment-bounded Ogg padding, representative edit-completeness refusals, requested-range silence/edge-leakage outcomes, and stage-typed all-or-nothing refusal/cleanup in both asset orders. Ogg parser/validator/wrapper matrices and lossy outside/guard SNR or maximum-error refusal matrices are not routine required tests. Their parser/native-validation/wrapper/tolerance behavior is evidenced by the manual real-FFmpeg scripts and author-reported historical negative-control runs, not by required tests; the prior runs are not reproducible from artifacts in this branch. Manual scripts exercise real capability preflight, actual FFmpeg/libvorbis round trips, corrupt and unsupported source refusal, `-n` encode refusal, and measured lossy fidelity; the AST probe also checks wrapper bounded tail reads/diagnostics and best-effort Windows timeout termination using Python-backed negative controls.

The parser is intentionally whole-file, not streaming: caller input is capped at 64 MiB, pages and total packets at 100,000 each, and an unfinished packet at 16 MiB. It retains only the three headers, the setup-header end page, and the first audio packet's start location; completed audio packets are validated/count-discarded without per-packet location tuples or retained bodies. It also enforces Vorbis I page placement: the identification packet alone on BOS, ordered headers, first audio on a fresh page, zero granules on completed header-only pages, and EOS on the final page. The 100,000-packet budget is about 35 minutes at this specimen's observed 70 packets per 1.5 seconds, while preventing million-scale one-byte-packet amplification. The previous all-packet retention caused substantial amplification from tiny packets; the total-packet cap now rejects before retaining any audio body.

Nominal bitrate preservation allows at most 10% relative header rounding. The measured real fixture was exactly 128,000 bit/s before and after; 32,000→48,000 bit/s is refused.

The parser is structural and does not decode setup/audio packets. Earlier focused unit tests checked the CRC implementation against a known vector and slow reference; that evidence is historical and is not reproducible from this branch's required tests. The manual scripts still validate CRCs on real FFmpeg pages and reject one corrupted page. FFmpeg is the only decoder in this evidence; no engine bank, game loader, independent decoder, or production compatibility is established. The vendor string was unchanged in this same-build run (`Lavf61.7.103`), but it is intentionally not a preservation invariant.

## Reproduction / evidence

From the repository root on the verified Windows environment:

~~~powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path
& .venv/Scripts/python.exe -m experiments.native_ogg.probe
& .venv/Scripts/python.exe -m experiments.native_ogg.shared_edit
~~~

The probe measured the identity control at 33.020 dB SNR, max error 0.01706610, and 27,390 → 26,507 bytes (−883). Shared edits measured minimum outside-region SNR 30.949 dB, maximum outside error 0.03549913, minimum guard-region SNR 25.690 dB, maximum guard error 0.02692842, and requested-range peaks up to 0.00001420. The scripts report per-region measurements, include clip-start/end edits, and exercise corrupt, unsupported, and real FFmpeg `-n` encode refusals with atomic snapshots.

## Recommendation

Keep the lossless AST and lossy Ogg specimens clearly separate in Issue #20 claims. Any future lossy adapter should calibrate decoded-domain thresholds and guard intervals on its actual codec/profile and independently verify loader compatibility before installation claims.
