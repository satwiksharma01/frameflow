# Working on Agent Video

This is an independently authored project. Read `REBUILD-BOUNDARY.md` and `FORMAT.md` before changing behavior. The adjacent reference checkout and research artifacts are outside the product boundary; do not import, copy, translate, vendor, or adapt their code, templates, agent instructions, assets, or internal schemas.

Use Node standard libraries unless the user has asked for a capability that requires more. Invoke external tools with argument arrays and no shell. Keep schema validation at input boundaries, and retain output-preservation and asset-confinement protections.

Run `npm test` for behavior changes. Tests include real FFmpeg/FFprobe execution and require those tools and a supported installed caption font. Inspect representative output frames after caption/layout changes. Do not weaken or skip checks to hide a failure.

Product instructions for producing videos are `skills/agent-video/SKILL.md`. Implementation instructions and production instructions serve different purposes.

Before a release, inspect `npm pack --dry-run --json`. Only allowlisted product files belong in a package. Job folders may contain local media and fonts; keep them and research evidence out of releases. Existing MP4s must never be overwritten implicitly.
