# Licensing and contribution guidance

[Apache-2.0](../LICENSE) applies to Muteinous project software that its licensors have authority to license. See [D167](architecture/decisions.md#d167--license-muteinous-under-apache-20) for the approved policy and [brand usage](brand-usage.md) for the separate branding policy. Third-party materials retain their own terms; the project does not grant rights to proprietary game data or third-party models, tools or trademarks.

## Contributions

Contributions intentionally submitted for inclusion are governed by Apache-2.0 section 5 unless explicitly stated otherwise. Contributors retain their own copyright and must have authority to submit their contributions under the applicable terms. Identify imported material and its origin, preserve required notices, and disclose any different terms before inclusion. Do not include material whose rights are unknown or whose license prevents the intended distribution. No separate CLA, DCO or mandatory per-commit sign-off is required. This policy does not retroactively establish rights to older contributions or imported material.

## Dependency admission and changes

Prefer permissive licenses (including MIT, BSD and Apache-2.0). At introduction or material change, document the actual version, upstream license evidence, scope (runtime, development, build, optional, downloaded or bundled), relevant transitive and native dependencies, and obligations for the proposed use and distribution. Preserve required notices and license texts. Review alternative license choices and record the basis for any exception; obtain maintainer approval for exceptions before adoption.

LGPL, MPL, GPL, AGPL, proprietary or other nonpermissive terms are not automatic approvals or blanket prohibitions: determine the actual integration, build configuration and obligations. Reject unknown or unresolved licensing for the proposed use. Do not adopt a configuration that defeats the project's proprietary-derivative goal without a separately approved policy change. Review build-time tools in their actual scope rather than assuming their terms automatically apply to output; assess copied/generated material separately where relevant. Apply the same principles to models (including pinned manifests under D144), native decoders, bundled DLLs, optional executables and downloads. A declared top-level license is not proof of a binary's entire license graph. No PyAV, FFmpeg or vgmstream distribution configuration is approved by this policy.

Use the existing Issue/PR review process, not a new compliance framework. Record upstream links, affected artifacts, required actions and unresolved checks in the relevant Issue/PR or enduring evidence documentation.

## Release-time verification

Before distributing any artifact, identify its actual contents, dependencies and binary build options; confirm redistribution rights and satisfy applicable licenses, copyright notices, NOTICE material, source/source-offer and relinking obligations where applicable. Keep third-party attribution separate from project licensing; do not insert speculative or incomplete notices as evidence of compliance. Check wheel and sdist metadata and included project license files using the existing package build check. Review source archives, separately bundled dependencies, frozen applications, model downloads and platform-specific artifacts according to what is actually distributed. Record artifact identity and evidence in the release review; unresolved obligations for that artifact block redistribution. The human publication gate remains in force; no automated publication or installer framework is introduced.

See [current licensing inventory](licensing-inventory.md) and the [outstanding verification register](../.agents/current-state.md) for evidence limits. Prior research, lockfile metadata and passing functional tests alone do not establish legal clearance.
