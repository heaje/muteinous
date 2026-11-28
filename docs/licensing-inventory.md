# Licensing inventory and outstanding evidence

Initial repository inspection for [#62](https://github.com/heaje/muteinous/issues/62), based on main `794bcbec448ecb1d9b9e97a536273fcd38f4a560` (2026-11-28). This is an inventory and limited technical review, not legal clearance.

## Source provenance

The GitHub main commit listing returned 38 commits, all attributed to `heaje`, with no Co-authored-by trailers in that listing. This establishes recorded authorship only, not copyright ownership, permission to relicense, or provenance of copied/generated material. The repository previously had no root LICENSE or declared package license. Before merging the licensing grant, the maintainer must confirm authority to license all included source, documentation, tests and fixtures, identify any imported material or prior contributions requiring separate terms/consent, and preserve applicable notices. No legal name or copyright claimant has been inferred from the account; the project NOTICE is deliberately limited to factual attribution pending confirmation of any required copyright notices. Brand clearance is outstanding, and trademark registration is deferred.

## Runtime dependency

`blake3` 1.0.11 is the only declared direct runtime dependency, with no Python transitive dependencies in its lock entry. The [existing dependency audit](source-validity.md#dependency-license-and-packaging-evidence) reports the wrapper as CC0-1.0 OR Apache-2.0 and the Rust dependency graph as permissively declared (30 crates). Reuse that evidence without treating it as a complete native-binary review. The audit did not parse the SBOM, inspect every crate license/NOTICE or determine actual per-wheel linked features. The frozen-application review remains open. For distributions that bundle the extension, inspect the exact wheel/binary and determine required notices before redistribution; a Muteinous wheel's dependency declaration is not by itself a bundled copy of BLAKE3.

## Locked development/build environment

The following version inventory is derived from the committed [uv.lock](../uv.lock) at the inspection revision; apart from BLAKE3 these are development/build dependencies, including transitives (some platform-conditioned). Their individual license texts, embedded native dependencies and notices have **not** been verified at these exact versions in this review. They are not approved for bundling by this inventory. Check actual terms for their use and any redistributed tool or copied material; no claim that the whole toolchain is permissive.

- argcomplete 3.7.2
- ast-serialize 0.13.1
- blake3 1.0.11
- charset-normalizer 3.5.3
- colorama 0.4.6
- commitizen 4.20.1
- decli 0.6.3
- deprecated 3.0.1
- execnet 2.1.2
- iniconfig 2.3.1
- jinja2 3.1.6
- librt 0.17.0
- markupsafe 3.0.4
- mypy 2.4.1
- mypy-extensions 1.2.0
- packaging 26.4
- pathspec 1.1.1
- pluggy 1.7.0
- prompt-toolkit 3.0.53
- psutil 7.2.2
- pygments 2.21.0
- pytest 9.2.0
- pytest-xdist 3.8.0
- pyyaml 6.0.4
- questionary 2.1.1
- ruff 0.17.6
- setuptools 84.2.1
- setuptools-scm 10.3.4
- termcolor 3.3.0
- tomlkit 0.15.3
- typing-extensions 4.16.0
- vcs-versioning 2.6.0
- wcwidth 0.9.5
- wheel 0.48.0
- wrapt 2.5.2

## Native-format tools, models and release artifacts

The retained [AST experiment](../.agents/findings/ast-pcm-roundtrip.md) used a GPL-enabled FFmpeg build and vgmstream with third-party components; the [Vorbis experiment](../.agents/findings/vorbis-lossy-roundtrip.md) also documents SoX/Vorbis tools. These were experiments, not production dependencies. Preserve #20's remaining per-binary/third-party review and all other deferred checks. PyAV/FFmpeg selection for #53 is independent and must evaluate the exact proposed distribution configuration.

No model license or redistribution rights are inferred from the selected ASR architecture. Review the actual pinned model/runtime artifacts before admission and redistribution. Proprietary game content is not licensed by this project.

Outstanding: source-rights confirmation and applicable notices before merge; exact development/build license review; release-time verification of actual wheel/sdist and any future bundled components; existing frozen-app and #20 obligations; trademark availability. See the [verification register](../.agents/current-state.md). Keep [#62](https://github.com/heaje/muteinous/issues/62) open until the in-scope ownership, licensing and review requirements are met or explicitly resolved under the repository's work-unit policy; no unperformed check is a pass.
