# Video-game plugin

The video-game plugin is responsible for finding installed games and, eventually, understanding their files so Muteinous can work with their audio and text. It uses information from game launchers and the files themselves rather than a maintained list of supported game titles.

Today, this package implements installation discovery and a small, optional file-format check. Full game scanning, audio analysis, reconstruction and installation of modified files are not implemented here yet.

## Finding games

| Source | Windows | Linux | macOS |
| --- | --- | --- | --- |
| Steam | Implemented | Not yet | Not yet |
| Epic Games Launcher | Implemented | Not yet | Not yet |
| GOG | Implemented | Not yet | Not yet |
| Manually selected folder | Implemented | Implemented | Implemented |

The table describes implemented discovery methods, not verified game compatibility. Automatic discovery has been tested with simulated launcher installations; testing against actual Windows launcher installations is still outstanding.

Manual folder selection works without a launcher, so users can locate games that automatic discovery misses.

### How automatic discovery works

1. Ask each built-in store provider for installation locations using the current operating system's launcher information.
2. Check the reported directories and collect their names, locations and sources.
3. Combine duplicate results when their resolved directory paths match exactly.
4. Return the candidates along with any problems encountered.

A **candidate** is a possible game installation. An available candidate has an existing directory; it is not necessarily complete, playable or compatible with Muteinous. Missing and inaccessible directories are reported rather than silently discarded. An Epic installation marked incomplete by its launcher is also reported.

Discovery reads launcher information, not game content. It does not start the launcher or change any files. A separate, explicit user action will be needed for a comprehensive scan.

### Where installation information comes from

Launchers keep small records of installed games. Each provider understands its own launcher's record format and locations.

| Store | Information read on Windows |
| --- | --- |
| Steam | Installation directory from the Windows Registry and conventional Program Files locations; library lists (`libraryfolders.vdf`) and installed-game records (`appmanifest_*.acf`). |
| Epic | JSON manifest files (`.item`) in `%ProgramData%/Epic/EpicGamesLauncher/Data/Manifests`. |
| GOG | Game paths and display names from the Windows Registry under `Software\GOG.com\Games`. |

Steam checks the current-user `SteamPath` and machine-wide `InstallPath` values, and looks for its library list in `config/` before falling back to `steamapps/` if the first file is absent. Both modern and older library-list layouts are supported.

The Windows Registry is a database of system and application settings. Steam and GOG discovery check both 32-bit and 64-bit registry views, using the current-user and machine-wide sections where applicable. These are best-effort searches, not a guarantee that all launcher versions register installations this way.

## A lightweight look at game files

After finding a candidate, the caller can optionally run a **probe**: a quick look at a small sample of files. This is separate from discovery, and is not a full scan.

The current probe checks for the four-byte `STRM` signature, a possible indication of the AST audio format. Finding it is a reason to investigate further, not proof that Muteinous can read or modify the file. Not finding it does not prove that the game contains no AST files.

### Example

These Python functions are intended for developers integrating the plugin, not a finished user interface.

```python
from pathlib import Path

from muteinous.plugins.video_games.discovery import (
    discover_installations,
    probe_installation,
    select_folder,
)

result = discover_installations()
for candidate in result.candidates:
    print(candidate.name, candidate.path, candidate.availability)
for issue in result.issues:
    print(issue)

# Alternatively, choose a folder directly.
manual = select_folder(Path.home() / "My Game")
for candidate in manual.candidates:
    if candidate.availability == "available":
        probe = probe_installation(candidate)
        print(probe.ast_signature, probe.truncated)
```

A result's `issues` describes problems encountered. A true `truncated` flag indicates that limits or skipped work left the result incomplete; a false flag is not a guarantee of exhaustive coverage.

## Code organization

| File or package | Responsibility |
| --- | --- |
| [`discovery/service.py`](discovery/service.py) | Coordinates discovery and manual folder selection. |
| [`discovery/models.py`](discovery/models.py) | Defines candidates, results and cancellation types. |
| [`discovery/context.py`](discovery/context.py) | Keeps track of candidates, duplicate paths, errors, cancellation and shared resource limits for one discovery operation. |
| [`discovery/providers/`](discovery/providers/) | Contains the Steam, Epic and GOG implementations and their common interface. |
| [`discovery/probe.py`](discovery/probe.py) | Performs the optional, store-independent file check. |
| [`discovery/_registry.py`](discovery/_registry.py) | Tracks registry reads against the discovery operation's limits. |

Two reusable modules live outside the plugin: [`environment.py`](../../infrastructure/platform/environment.py) identifies the current OS, and [`windows_registry.py`](../../infrastructure/platform/windows_registry.py) reads bounded text values from the Windows Registry. The latter is imported only on Windows by the discovery adapter.

### Adding another store

Each store owns its metadata formats and platform-specific locations. The coordinator does not need to know how a store finds its games.

- Implement the small [`InstallationProvider`](discovery/providers/base.py) interface and its `discover(state)` method.
- Use the shared discovery context to report installations, errors and resource consumption. Keep Windows-specific behavior inside the provider's Windows path and report unsupported platforms without stopping other providers.
- Register the provider in [`providers/__init__.py`](discovery/providers/__init__.py) and add tests using small, artificial launcher records.

Providers can accept alternate metadata sources for testing. Split platform-specific code into additional modules only when the implementation becomes complex enough to benefit from it. There is no separate external store-plugin API.

## Safety and responsiveness

Finding games should be inexpensive and should leave the original installation untouched. Neither discovery nor the probe writes to games or launcher metadata, hashes or decodes game content, or runs speech recognition.

The following are provisional limits, chosen to keep browsing lightweight rather than to define game compatibility. They will be revisited using measurements from real installations.

| Operation | Current limit |
| --- | --- |
| Discovery entries and records | 4,096 across all providers |
| Individual metadata file | 1 MiB |
| Individual registry value | 64 KiB |
| Total metadata read | 16 MiB across all providers |
| Probe | 128 entries, in the root and up to two subdirectory levels |
| Probe file read | Four bytes per ordinary file |

File reads may request one additional byte to detect overflow, including one possible final byte beyond the aggregate budget. Directory enumeration may obtain one extra entry to detect truncation. Registry reads use a fixed-size buffer; oversized values are rejected rather than retried with a larger allocation, unsupported value types are rejected, and failures with an unknown transfer size count against the budget.

Metadata files and their immediate parent directories must be ordinary filesystem objects. Invalid paths, explicit parent traversal and Windows device or reserved names are refused. The probe skips symbolic links, Windows reparse points (such as junctions) and special files, including a linked probe root.

All three entry points and the probe accept a cancellation callback. Cancellation stops between bounded operations and raises `DiscoveryCancelled` instead of returning a partial result. A blocked operating-system call cannot be interrupted by this mechanism.

## Known limitations

- Nonstandard launcher locations may be missed, including Epic's relocated PCB-mode metadata.
- The file checks do not guarantee protection against every ancestor link or a file changing between inspection and opening. Operating-system read-ahead is outside the application's byte limits.
- Real launcher integration, probe coverage and responsiveness still need verification on Windows installations.
- Native Linux and macOS launcher discovery, comprehensive scanning and definitive game compatibility checks are future work. The browsing limits above do not apply to a separately requested comprehensive scan.

## Testing

The [discovery tests](../../../../tests/unit/plugins/video_games/test_discovery.py) create small synthetic launcher records and game directories instead of relying on actual games. They cover parsing, path checks, duplicate candidates, cancellation, read-only behavior, limits and probing.

Windows tests simulate registry views and the responses of the native Windows Registry API. The bounded reader is tested with in-memory data, including missing, oversized and malformed values. Tests must never create, modify or delete actual Windows Registry keys or values, even temporarily.

From the repository root, after following the [development setup](../../../../docs/development.md):

```powershell
task.cmd test -- tests/unit/plugins/video_games/test_discovery.py
```

On Linux or macOS, run only the portable tests:

```sh
task test -- -m portable tests/unit/plugins/video_games/test_discovery.py
```

See the [testing guide](../../../../docs/testing.md) for the full validation procedure. Revision-specific results and outstanding verification are recorded in [issue #51](https://github.com/heaje/muteinous/issues/51) and [PR #57](https://github.com/heaje/muteinous/pull/57).

## Further reading

- [Project architecture and decisions](../../../../docs/architecture/decisions.md) (especially D132, D133, D137 and D138): the rationale for generic discovery, provisional evidence and explicit scanning.
- [Steam client data format](https://reverseengineering.wiki/index.php/Format:Steam_client_data_files) and [SKIF library discovery implementation](https://github.com/SpecialKO/SKIF/blob/master/src/stores/Steam/steam_library.cpp): Steam manifest and library-list formats and locations.
- [Observed launcher metadata layouts](https://github.com/VantaCode420/SmartHdrManager/blob/main/Library.cs): examples of Steam and GOG registry information and Epic manifest fields.
- [Epic's launcher documentation](https://dev.epicgames.com/documentation/en-us/unreal-engine/multiple-launcher-unreal-engine-installs): normal and relocated metadata locations.
- [Microsoft's RegQueryValueExW documentation](https://learn.microsoft.com/windows/win32/api/winreg/nf-winreg-regqueryvalueexw): the native API used for fixed-buffer registry reads.
