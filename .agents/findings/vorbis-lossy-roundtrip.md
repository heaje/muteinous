# Vorbis lossy round-trip evidence
Status: active for the synthetic stereo/44.1-kHz experiment only
Last verified: 2026-11-24
Related: [#20](https://github.com/heaje/muteinous/issues/20), [Ogg Vorbis experiment](../../experiments/native_ogg/README.md)
Retire/promote when: the isolated experiment is removed or replaced with a production native adapter and independent compatibility evidence.

## Finding and limitations

With the observed Windows FFmpeg/libvorbis build, a no-edit Ogg Vorbis identity re-encode is measurably lossy even though it retained the source's 128,000-bit/s nominal bitrate, user comments, stereo/44.1-kHz profile, and 66,150 decoded frames. The test measured 33.020 dB SNR and 0.01706610 maximum absolute sample error versus the original Ogg's decoded PCM. The Ogg final granule position matched FFmpeg's decoded frame count. For the edited fixture, the minimum SNR across four unedited 2,048-frame boundary guards was 31.092 dB and maximum absolute error was 0.01743349; policy uses 18 dB / 0.05 for those guard bands and 24 dB / 0.08 farther away. These guards ensure an edit whose expanded region covers the whole clip still verifies its remaining unedited frames.

The parser is intentionally whole-file, not streaming: caller input is capped at 64 MiB, pages and total packets at 100,000 each, and an unfinished packet at 16 MiB. It retains only the three headers and validates/counts/discards completed audio packets. The 100,000-packet budget is about 35 minutes at this specimen's observed 70 packets per 1.5 seconds, while preventing million-scale one-byte-packet amplification. The previous all-packet retention caused substantial amplification from tiny packets; the total-packet cap now rejects before retaining any audio body.

Nominal bitrate preservation allows at most 10% relative header rounding. The measured real fixture was exactly 128,000 bit/s before and after; 32,000→48,000 bit/s is refused.

The parser is structural and does not decode setup/audio packets. CRC uses a once-built table and remains checked against the known vector, a slow reference and real pages. FFmpeg is the only decoder in this evidence; no engine bank, game loader, independent decoder, or production compatibility is established. The vendor string was unchanged in this same-build run (`Lavf61.7.103`), but it is intentionally not a preservation invariant.

## Reproduction / evidence

From the repository root on the verified Windows environment:

~~~powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path
& .venv/Scripts/python.exe -m experiments.native_ogg.probe
& .venv/Scripts/python.exe -m experiments.native_ogg.shared_edit
~~~

The probe measured the identity control at 33.020 dB SNR, max error 0.01706610, and 27,390 → 26,507 bytes (−883). Shared edits measured minimum outside-region SNR 31.636 dB, maximum outside error 0.02047877, minimum guard-region SNR 31.092 dB, maximum guard error 0.01743349, and edited-interior peaks 0.00000000. The scripts report the complete per-region measurements and exercise corrupt, unsupported, and real FFmpeg `-n` encode refusals with atomic snapshots.

## Recommendation

Keep the lossless AST and lossy Ogg specimens clearly separate in Issue #20 claims. Any future lossy adapter should calibrate decoded-domain thresholds and guard intervals on its actual codec/profile and independently verify loader compatibility before installation claims.
