# Python compatibility evidence — D164

Investigation for [Issue #6](https://github.com/heaje/muteinous/issues/6), 2026-11-23 (UTC 2026-11-24). The older [Hushpatch manifest at 62c55c4](https://github.com/heaje/hushpatch/blob/62c55c4d91fcef3f14a592698acd07e5666fb890/pyproject.toml) is a candidate inventory, not a new runtime dependency contract.

## Windows x64 candidate probe

[Run 45298464859](https://github.com/heaje/muteinous/actions/runs/45298464859), Windows 2025, uv 0.13.9. The [exact temporary probe](https://github.com/heaje/muteinous/blob/7ab7d3f516ea1ff17f3e99883acf55ccc3e33507/.github/workflows/compatibility-probe.yml) created separate clean CPython 3.14.10 and 3.15.2 environments, dry-ran each candidate requirement with binary-only resolution, and installed/imported the complete candidate set on 3.14. No source builds or model downloads. Hushpatch's ONNX Runtime substitution was preserved for this experiment: an override of `onnxruntime>=1.14; sys_platform != 'win32'` avoids installing both runtime builds on Windows. This does not establish that the override is appropriate for the eventual v2 implementation.

| Candidate constraint | Installed on 3.14.10 | 3.15.2 binary-only dry run |
| --- | --- | --- |
| faster-whisper>=1.2.1 | 1.2.1 (CTranslate2 4.9.1, av 19.0.2, tokenizers 0.23.3) | resolved |
| cryptography==50.0.2 | 50.0.2 | resolved |
| lz4==4.4.5 | 4.4.5 | no usable wheels |
| numpy>=2.5.4 | 2.5.5 | resolved |
| onnxruntime-windowsml>=1.30 | 1.30.1.202610302006 | no matching cp315 ABI wheel |
| onnxruntime-genai-winml>=0.17.1 | 0.20.0 | no matching cp315 ABI wheel |
| platformdirs>=4.3 | 4.14.8 | resolved |
| psutil>=7 | 7.2.2 | resolved |
| tomli-w>=1.2 | 1.2.0 | resolved |
| pyside6-essentials>=6.12.0 | 6.12.0 | resolved |
| pyside6-addons>=6.12.0 | 6.12.0 | resolved |
| pyyaml>=6.0.3 | 6.0.4 | resolved |
| zstandard==0.25.0 | 0.25.0 | no usable wheels |

The [3.14 job](https://github.com/heaje/muteinous/actions/runs/45298464859/job/138124719433) succeeded, including imports of all listed candidates and PySide6 QtCore, QtWidgets and QtMultimedia. ONNX Runtime emitted **Init provider bridge failed** during import; no execution provider, model inference, GPU functionality, Qt rendering or native-format round trips were exercised. The [3.15 job](https://github.com/heaje/muteinous/actions/runs/45298464859/job/138124719682) failed at the four listed resolution requirements. Other 3.15 results are only independent dry runs, not a verified combined environment. No attempt was made to build the blocked packages from source or to relax Hushpatch's constraints. These results justify selecting 3.14 for the development foundation; 3.15 needs a new compatibility probe before adoption.

Linux/macOS are tooling-only targets at this stage. Hushpatch's non-Windows ONNX variants and optional PyInstaller packaging were not probed, nor are they required by the current empty application bootstrap. Future feature Issues must select and verify actual dependencies, test relevant functionality on supported platforms, and add the dependencies to the project lock. Successful import alone does not establish application or hardware support.
