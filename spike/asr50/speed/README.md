# WP22 speed benchmark

`whisper_cli_batch.ps1` runs one whisper.cpp configuration serially over the
fixed short/medium/long clip selection in `C:\scratch\asr50\WP22\clips.json`.
Each timed configuration:

- acquires `C:\scratch\asr50\timing.lock.d` and waits for three idle samples
  (CPU <5%, RX 7900 XT 3D/Compute <0.1%), retrying for at most 60 seconds;
- runs five separate CLI invocations per clip through `run_cli_timed.py`.
  `time.perf_counter` measures wall time; no GPU-counter sampling occurs in
  the latency window. Process CPU time and peak working set are queried once
  after the child exits through its retained Windows process handle;
- checkpoints every observation to `C:\scratch\asr50\WP22\<config>.jsonl`.

After each GPU latency configuration, `gpu_telemetry_pass.ps1` may run a
separate untimed long-clip transcription while `sample_gpu_pid.ps1` collects
PID-filtered GPU Engine and Dedicated Usage counters at 1 Hz. The sampler is
BelowNormal priority and has a 20-second no-progress watchdog that kills only
the sampler; the untimed candidate has its own 600-second timeout. This
separate pass never contributes to latency/RTF.

`library_batch.ps1` runs the CPU/DML library candidates with one model load per
class process, an untimed warm-up per clip, and five `time.perf_counter`
inference observations. `gpu_telemetry_library.ps1` collects DML counters in a
separate untimed pass. Each class process has a 600-second hard timeout and
checkpoints each repeat.

Use one timed configuration at a time. Do not run this script alongside another
timed benchmark. The `-Drift` switch is reserved for repeating the first config
at the end. CLI runs include model load by definition; they are not comparable
to in-process steady-state library latency without reporting that distinction.
