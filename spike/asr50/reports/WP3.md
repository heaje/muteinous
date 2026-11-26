# WP3 — Windows ONNX Runtime / DirectML execution probe

**Run date:** 2026-11-26  
**Environment:** Windows 11 Pro build 26300; Ryzen 9 9900X; AMD Radeon RX 7900 XT (PCI `1002:744C`), driver `32.0.32029.2010`; uv 0.13.9; CPython 3.14.10 x64. No ASR model weights or external model files were fetched. Synthetic graphs were generated locally.

## Summary findings

- **DirectML (standalone ORT wheel): L1 + L2 + L3 + L4.** `onnxruntime-directml==1.24.4` installed on CPython 3.14.10. The DirectML EP accepted synthetic fp32 MatMul chains, fp16 MatMul chains, and Conv. ORT verbose placement logs and profile JSON both attribute nodes to `DmlExecutionProvider`; output matched CPU exactly in the probes. This is evidence of real GPU execution on the machine, not merely provider listing. Execution timings from this short synthetic microbenchmark should not be generalized to ASR.
- **Windows ML dynamic EP catalog: L1 only for Windows ML as a feature; no device/compute evidence (no L3/L4).** Microsoft’s current Python support matrix states CPython 3.10–3.13 x64/ARM64; 3.14 is not listed. Catalog-acquired EPs require Windows 11 24H2+; EPs can be downloaded on first use, requiring network when not already present, and Windows App SDK runtime / initialization. Microsoft’s Python sample calls `ensure_ready_async()` and registers catalog DLLs into Python ORT; its acquisition documentation explicitly says the alternative “ensure and register” API does not register into the Python ORT environment. We did **not** attempt catalog acquisition: that can download/install shared system EP packages and can require Windows App SDK runtime installation, outside the permitted system-change scope. The installed `onnxruntime-windowsml==1.30.1.202610302006` wheel imported, but logged `Init provider bridge failed`; the bundled ORT listed CPU and DML only. This does not establish that the Windows ML Python integration or its dynamic EP catalog works on this host / Python 3.14.
- **CPU ORT: L2.** `onnxruntime==1.32.0` installed and synthetic CPU runs succeeded. No hardware-acceleration conclusion.
- **No iGPU surfaced** by `Win32_VideoController`; only RX 7900 XT appeared. Windows perf-counter enumeration did expose two GPU LUIDs/adapter-memory instances, one consistent with an additional logical/virtual adapter. Mapping the second LUID to a physical iGPU was not established, so no per-adapter iGPU inference claim.
- No ASR inference was attempted (L5 not tested, and weights were prohibited).

## Documentation research (accessed 2026-11-26)

- [Windows ML Python deployment and install guidance](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/distributing-your-app): Python packages include `wasdk-Microsoft.Windows.AI.MachineLearning[all]`, the DynamicDependency Bootstrap package, and `onnxruntime-windowsml`; docs list Python 3.10–3.13 x64/ARM64 and an unpackaged Python install. Requires matching Windows App SDK runtime.
- [Windows ML ExecutionProviderCatalog](https://learn.microsoft.com/en-us/windows/windows-app-sdk/api/winrt/microsoft.windows.ai.machinelearning.executionprovidercatalog?view=windows-app-sdk-2.0): discover/acquire/register compatible EPs; Python registration is into Python ORT through `ort.register_execution_provider_library(...)`.
- [Install Windows ML EPs](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/initialize-execution-providers): `EnsureReadyAsync()` downloads/install EPs on demand; first-run can take seconds to minutes; Python should not use catalog's native register API for Python ORT.
- [Windows ML supported EPs](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/supported-execution-providers): CPU and legacy DirectML are included; vendor EPs are dynamic/catalog acquired where device/driver compatible.
- [Windows ML EPs vs bring-your-own](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/windows-ml-eps-vs-bring-your-own): catalog acquisition supports Windows 11 24H2+ and network is required if EP is not already installed; DirectML and CPU are included.
- [ONNX Runtime DirectML EP](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html): DirectML is sustained engineering; use WinML for new Windows deployments. DirectML requires a DirectX 12 device; docs warn memory pattern / parallel execution limitations.
- [ONNX Runtime Windows overview](https://onnxruntime.ai/docs/get-started/with-windows.html): WinML recommended, standalone DirectML remains a legacy/sustained-engineering path.

The official guidance therefore does **not** support claiming Windows ML catalog use from CPython 3.14; current documented Python support stops at 3.13. The standalone DirectML package itself did install and run on CPython 3.14 here.

## Installation and dependency checks

Created independent disposable environments under `C:\scratch\asr50\WP3\venvs\`, all with `uv venv --python 3.14.10`; installed binary wheels only:

| Environment | Requested package | Installed ORT | Install result | `uv pip check` |
|---|---|---:|---|---|
| `directml` | `onnxruntime-directml onnx` | 1.24.4 | Success | `Checked 10 packages... All installed packages are compatible` |
| `windowsml` | `onnxruntime-windowsml onnx` | 1.30.1.202610302006 | Success | `Checked 8 packages... All installed packages are compatible` |
| `cpu` | `onnxruntime onnx` | 1.32.0 | Success | `Checked 8 packages... All installed packages are compatible` |

No cp314 wheel gap was encountered for these requested packages on Windows x64. Dependency checks reported no conflicts; no constraints were overridden.

## Synthetic execution results

Script: `C:\scratch\asr50\WP3\scripts\probe.py`. It produces local ONNX graphs for fp32 1024×1024 three-MatMul chain, fp16 512×512 chain, and Conv `[1,16,128,128]` to `[1,32,126,126]`. Inputs and weights are deterministic constant synthetic values.

| Graph / EP session | Run count | elapsed (s) | CPU reference delta max / mean |
|---|---:|---:|---:|
| fp32 MatMul, CPU | 30 | 0.19955 | 0 / 0 |
| fp32 MatMul, DirectML | 30 | 0.06942 | 0 / 0 |
| fp16 MatMul, CPU | 20 | 0.01277 | 0 / 0 |
| fp16 MatMul, DirectML | 20 | 0.00623 | 0 / 0 |
| Conv, CPU | 20 | 0.00744 | 0 / 0 |
| Conv, DirectML | 20 | 0.01485 | 0 / 0 |

The numbers are wall times from one very short, small synthetic run and not controlled benchmarks. The timing ratios are not performance claims for real models. DML CPU-vs-GPU correctness was exact for the tested values.

For successful DML sessions, `session.get_providers()` returned `['DmlExecutionProvider', 'CPUExecutionProvider']`. The DML Conv profile contained events named `DmlFusedNode_0_0_kernel_time` with `args.provider == "DmlExecutionProvider"`; verbose logs stated `All nodes placed on [DmlExecutionProvider]`. This satisfies L4 for those graph instances. The standalone package's EP device object API differed from the current docs: probing `hardware_device` raised `AttributeError`; available properties on this ORT version are `device`, `ep_metadata`, `ep_name`, `ep_options`, `ep_vendor`, `memory_info`.

## Failure/fallback verification

- **Invalid DirectML adapter id:** adding DML with `device_id=9999` raised:
  `887A0002 The object was not found. If calling IDXGIFactory::EnumAdaptes, there is no adapter with the specified ordinal.`
  Captured verbatim in `logs\directml-run.txt` (UTF-16 PowerShell redirection). No silent fallback occurred: session construction raised.
- **CPU fallback disable attempt:** combining explicit `CPUExecutionProvider` with `session.disable_cpu_ep_fallback=1` failed before execution with:
  `Conflicting session configuration: explicitly added the CPU EP to the session, but also disabled fallback to the CPU EP via session configuration options.`
  The first attempt therefore did not isolate whether an unsupported DML op would fall back silently. A subsequent DML-only provider request constructed a session for `MatMulInteger`, and `get_providers()` listed DML + CPU; this alone does not prove node placement, and no numerical output was run for that op. **Fallback behavior for an unsupported-op case remains unverified**, rather than presumed silent/non-silent.
- In the CPU-only environment, requesting DML warned/fell back to CPU; verbose logs for that session reported all graph nodes on CPU. This is not GPU computation.

## GPU utilization and resident footprint

- Queried `\GPU Engine(*)\Utilization Percentage` and `\GPU Adapter Memory(*)\Dedicated Usage` with `Get-Counter`; counters were available. However, this one-sample inventory was not collected during a sustained run filtered to a specific Python PID. Per instructions, I do not infer GPU utilization from successful dispatch or counters being present. This is a limitation: utilization sampling remains outstanding.
- Whole-v env directory sizes (post-install, approximate; includes venv scaffolding and package contents): CPU 121,507,852 bytes; DirectML 170,074,007 bytes; Windows ML wheel 142,340,453 bytes. These are measured total sizes, not clean before/after deltas.
- Representative packaged native libraries: CPU ORT `onnxruntime.dll` 22,668,600 B; DirectML `onnxruntime.dll` 21,111,840 B and `DirectML.dll` 18,527,776 B; Windows ML ORT `onnxruntime.dll` 24,045,880 B and a bundled `DirectML.dll` 18,527,544 B. Exact inventory and size output is in `logs\footprint.json`.

## Raw evidence and limitations

Raw logs/profiles are under `C:\scratch\asr50\WP3\logs\`: `directml-run.txt`, `cpu-run.txt`, `windowsml-enum.txt`, `directml-api.txt`, `fallback-test.txt`, `adapters.txt`, `footprint.json`, and per-session ORT profiling JSON in the `directml` / `cpu` directories. `summary.txt` extracts the run metrics and outcomes.

The run script attempted verbose logs and ORT profiling, but because profile prefixes overlap between repeated probes, some sessions overwrite earlier same-tag profiles. DML profile verification used the surviving DML Conv JSON. There was no Python-PID-filtered counter capture or Windows ML catalog acquisition. No system modification was made, and no model weights were downloaded.

## Follow-up

Completed 2026-11-26. Follow-up scripts are in `C:\scratch\asr50\WP3\scripts\` (`sustain.py`, `sample_gpu.ps1`, `fallback_probe.py`, `windowsml_fp16.py`); raw output remains under `C:\scratch\asr50\WP3\logs\`.

### Sustained GPU utilization and memory

Ran locally generated 4096×4096 dense MatMul chains (two MatMul nodes) for 22 seconds per case. The script printed its actual Python PID and provider list. DML cases requested `DmlExecutionProvider`; CPU controls requested `CPUExecutionProvider` only.

RX 7900 XT counter LUID was `0x00000000_0x000164ac`: `Win32_VideoController` showed the only physical adapter as AMD Radeon RX 7900 XT (PCI `1002:744C`), and DML Python PIDs' `GPU Process Memory` dedicated usage was recorded on that LUID. The other observed LUID `0x00000000_0x00018e95` had no DML process dedicated-memory sample.

| dtype / EP | Runs / elapsed | RX LUID engine samples (mean / peak) |
|---|---:|---|
| fp16 DML | 2,047 / 22.006 s | 3D: 6 (52.65% / 52.91%); Compute_0: 6 (0% / 0%); Copy (2 engines): 12 (0% / 0%) |
| fp32 DML | 781 / 22.017 s | 3D: 6 (64.35% / 65.41%); Compute_0: 6 (0% / 0%); Copy (2 engines): 12 (0% / 0%) |
| fp16 CPU | 220 / 22.029 s | No GPU Engine counter instance matched the Python PID in six completed sampler cycles |
| fp32 CPU | 217 / 22.079 s | No GPU Engine counter instance matched the Python PID in six completed sampler cycles |

Python PID-filtered dedicated memory peaked at 183,353,344 B (fp16 DML) and 351,133,696 B (fp32 DML). Adapter-wide RX LUID dedicated usage peaked at 2,100,015,104 B and 2,267,795,456 B, respectively; those adapter-wide figures are not attributable to Python.

**Sampling limitation:** the sampler loops through the three `Get-Counter` paths serially, with a one-second sleep; each call adds latency. Complete sample sets landed several seconds apart, not at a strict one-second cadence. There were six valid utilization samples per DML run over 22 seconds. Initial wildcard/batched sampling errors and retries are preserved in logs. The measurements provide PID/LUID-correlated evidence of sustained GPU activity, but do not claim the requested 1 Hz cadence. Windows labels active DML work under `engtype_3d`; sampled `engtype_compute 0` remained zero.

### Unsupported-op / CPU fallback

`fallback_probe.py` used unique profile prefixes and requested only `providers=["DmlExecutionProvider"]` for every case:

| Graph | `session.disable_cpu_ep_fallback` | Outcome | ORT profile node provider |
|---|---|---|---|
| String `Identity` | absent | session and run succeed | `CPUExecutionProvider` |
| String `Identity` | `1` | session creation fails: `This session contains graph nodes that are assigned to the default CPU EP, but fallback to CPU EP has been explicitly disabled by the user.` | No session/profile; failed at initialization |
| Dynamic-input `MatMulInteger` | absent | session and run succeed | `DmlExecutionProvider` (`DmlFusedNode_0_0_kernel_time`) |
| Dynamic-input `MatMulInteger` | `1` | session and run succeed | `DmlExecutionProvider` (`DmlFusedNode_0_0_kernel_time`) |

The baseline profile verifies that string `Identity` is assigned to CPU. Thus CPU execution is not visible to the application as a run failure, but placement is visible in ORT profiling; disabling CPU fallback causes an explicit initialization error. MatMulInteger was transformed/fused onto DML on this ORT build, so it was not an unsupported-op test and did not exercise fallback. Full verbose output and the four unique profile JSONs are in `logs\fallback-followup\`.

### Windows ML wheel import and DML

A fresh standard `python -I -c "import onnxruntime"` in the Windows ML venv (without SessionOptions overrides) emitted:

```text
2026-11-26 15:42:01.0183347 [W:onnxruntime:Default, onnxruntime_pybind_module.cc:45 onnxruntime::python::CreateOrtEnv] Init provider bridge failed.
```

The same warning appeared in the verbose test process. The raw standard-import capture is `logs\windowsml-import-fresh.txt` (UTF-16LE from PowerShell redirection); a readable decoded copy and the full verbose run are also kept under `logs\`.

The `onnxruntime-windowsml==1.30.1` environment ran the same synthetic fp16 512×512 MatMul chain with explicit DML. `session.get_providers()` returned DML and CPU; the profile contained `DmlFusedNode_0_0_kernel_time` with provider `DmlExecutionProvider`. CPU-reference maximum and mean absolute deltas were both zero: **L4 for DML execution through the Windows ML wheel's ORT distribution**. This does not establish execution through catalog-acquired Windows ML vendor EPs. Profile: `logs\windowsml-followup\winml_fp16_2026-11-26_15-42-20_480.json`.

### New concise summary

DirectML sustained synthetic fp16/fp32 MatMul for 22 seconds on the RX 7900 XT: 2,047/781 runs; 3D engine mean/peak 52.65/52.91% and 64.35/65.41%, with PID/LUID-filtered dedicated memory peaks of ~183/351 MB. CPU controls had no PID-specific GPU Engine instances. Counter samples were several seconds apart rather than 1 Hz; this limitation and raw timestamps are included. String Identity's baseline profile showed CPU assignment; disabling CPU fallback failed session creation with the exact assignment error. MatMulInteger fused onto DML, so it did not exercise fallback. Fresh Windows ML wheel import reproduced the complete provider-bridge warning; its DML EP nevertheless executed fp16 MatMul with exact CPU-reference agreement (L4). No catalog acquisition, system changes, model weights, or ASR inference. Extra effort: approximately 20 minutes. Sampling cadence is the remaining limitation; no other blocker remains for these follow-up checks.
