# AST PCM round-trip and loop metadata
Status: resolved for the narrow synthetic AST profile; arbitrary AST variants remain unsupported
Last verified: 2026-11-24
Related: [#20](https://github.com/heaje/muteinous/issues/20), D05–D08, [native AST experiment](../../experiments/native_ast/README.md)
Retire/promote when: the experiment is removed or replaced by a production native adapter with independent evidence.

The canonical 32 kHz stereo PCM16 fixture now round-trips through the actual shared PCM/WaveStorage/Scratch APIs and FFmpeg on Windows 11, CPython 3.14.10, with exact PCM frames and original bytes preserved. Before reconstruction, `prepare()` independently verifies the edited PCM against the verified original and merged integer edit ranges: required frames are zero, unaffected frames are byte-identical, and frame count is unchanged. The strict validator rejects AST encodings whose header padding, BLCK padding, packet partition, metadata, or decoded samples would be normalized by rebuilding. The pure-Python writer is cross-checked byte-for-byte against FFmpeg output; required pytest coverage uses fake codec callables and does not require FFmpeg.

The tested binary is FFmpeg `n7.1.5-12-g1fdbca85aa-20260731`, BtbN GPL static, installed through WinGet package `BtbN.FFmpeg.GPL.7.1`; it is configured with `--enable-gpl --enable-version3`. An already-open PowerShell process may need its PATH refreshed after WinGet installation. The exact commands and current script output are in the linked README.

FFmpeg AST loop options use integer milliseconds, while native fields store frames. The tested loop points (1,024–6,144 at 32 kHz) are exact; arbitrary native loop positions are not presumed representable. The earlier Linux identity-only result (CPython 3.13.5 / Debian FFmpeg `7.1.5-0+deb13u1`) is historical and does not establish Linux/macOS shared editing. Remote CI, independent decoder agreement, arbitrary AST variants, and game-loader acceptance/playback remain unverified.
