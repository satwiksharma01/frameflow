# Independent implementation boundary

User requirements recorded on 2026-10-31:

- Build an independently implemented video tool inspired by Hypit's capabilities.
- Keep an agent-driven, local command-line workflow; no new web interface is requested.
- Use REA to investigate the reference.
- Do not copy Hypit code into the product or depend on Hypit at runtime.
- The user subsequently requested the complete tool and explicitly excluded media generation. Supplied-media inspection, transcription, composition, variants and resumable execution are the implemented scope; no generation providers or paid calls are included.

## Product boundary

This directory is the intended product root. The adjacent `../hypit` checkout is reference material only. The adjacent `../analysis` directory contains research artifacts. `../.tools` contains research tooling. None belongs in the product's source tree, dependency graph, release archive, container image, or distributed documentation.

Write the implementation, tests, example projects, schemas, and agent instructions independently. Do not import or vendor Hypit packages, adapt its functions, translate its source into another language, copy its templates or skill text, or reuse its visual assets or branding. Use a separately designed project format and architecture rather than reproducing its internal contracts.

Research notes may describe externally useful behavior in original language. They must distinguish observations, interpretations, and unverified behavior. Keep REA evidence outside product releases because it can retain reference source text.

Before release, inspect both source and the actual packaged artifact for copied material, reference files, and Hypit dependencies. Record the origin and license of independently chosen third-party dependencies and assets. Do not infer redistribution rights from a dependency being publicly available.

## Current status

An independently written Node CLI, JSON project format, FFmpeg renderer, media inspection/reconstruction, local transcription adapter, word-linked captions/cuts/overlays, effects, job records, batch runner and resumable execution, original agent instructions, examples, and behavioral tests now live in this directory. There are no third-party JavaScript dependencies. Hypit was cloned and its dependencies installed for reference investigation before the independent-rebuild constraint was clarified. Those files remain outside this product directory and are not used by the implementation.

The investigating agent has read portions of Hypit's source and documentation. This is an independent rewrite requirement, not a claim of a formally segregated clean-room process or a legal clearance. Avoiding copied code does not by itself establish every right needed for commercialization.
