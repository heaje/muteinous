# Vorbis lossy round-trip evidence
Status: active for the synthetic stereo/44.1-kHz experiment only
Last verified: 2026-11-24
Related: [#20](https://github.com/heaje/muteinous/issues/20), [Ogg Vorbis experiment](../../experiments/native_ogg/README.md)
Retire/promote when: the isolated experiment is removed or replaced with a production native adapter and independent compatibility evidence.

## Finding and limitations

With the observed Windows FFmpeg/libvorbis build, a no-edit Ogg Vorbis identity re-encode is measurably lossy even though it retained the source's 128,000-bit/s nominal bitrate, user comments, stereo/44.1-kHz profile, and 66,150 decoded frames. The test measured 33.020 dB SNR and 0.01706610 maximum absolute sample error versus the original Ogg's decoded PCM. The Ogg final granule position matched FFmpeg's decoded frame count; Vorbis overlap and codec loss still require guarded, tolerant boundary checks. The synthetic edited outputs passed 24-dB minimum outside-region SNR and 0.08 maximum-error gates with 2,048-frame edge guards.

The parser is structural and does not decode setup/audio packets. FFmpeg is the only decoder in this evidence; no engine bank, game loader, independent decoder, or production compatibility is established. The vendor string was unchanged in this same-build run (`Lavf61.7.103`), but it is intentionally not a preservation invariant.

## Reproduction / evidence

From the repository root on the verified Windows environment:

~~~powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path
& .venv/Scripts/python.exe -m experiments.native_ogg.probe
& .venv/Scripts/python.exe -m experiments.native_ogg.shared_edit
~~~

The probe measured the identity control at 33.020 dB SNR, max error 0.01706610, and 27,390 → 26,507 bytes (−883). Shared edits measured minimum outside-region SNR 31.636 dB, maximum outside error 0.02047877, and edited-interior peaks 0.00000000. The scripts report the complete per-region measurements and exercise corrupt, unsupported, and real FFmpeg `-n` encode refusals with atomic snapshots.

## Recommendation

Keep the lossless AST and lossy Ogg specimens clearly separate in Issue #20 claims. Any future lossy adapter should calibrate decoded-domain thresholds and guard intervals on its actual codec/profile and independently verify loader compatibility before installation claims.
