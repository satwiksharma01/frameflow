# Preparing a reference workflow for Frameflow

Agent Video 1.1 adds a standalone preparation boundary for Frameflow's reference-video workflow. It does not install into, invoke, modify or depend on Frameflow. Its deliverable is a storyboard and evidence bundle for the Frameflow developer to connect to the existing production workflow. A flattened MP4 is not the native-project handoff.

This is an independently implemented interface adapter. It contains no Hypit code, packages, schemas, templates or instructions, and no vendored Frameflow source or schemas. Generation remains excluded: voice selection and scene narration that would request speech generation are rejected. Supplied recordings, clips, images and music are supported.

## Workflow

Start with a local reference, a Frameflow-style supplied-media inventory, and a brief. Relative inventory paths resolve from the directory containing `inputs.json` and become absolute references. Keep those media files available; the handoff does not copy them or the reference into a replacement video.

```powershell
node bin/agent-video.mjs reference-prepare reference.mp4 --inputs inputs.json --brief brief.json --timings source-timings.json --out-dir output/reference-session --json
```

`--timings` is optional for scenes that use complete source spans or only non-recording assets. Interior cuts in recordings require measured pauses. Reference inspection and the standalone renderer retain their ten-minute limit. The JSON-only Frameflow handoff supports target recordings and storyboard durations up to 24 hours, with at most 100 scenes; it does not force long Frameflow projects through the local renderer.

The command creates an opening-focused inspection, original pacing/shot evidence, `session.json`, and `analysis-request.md`. It does not invent a hook, caption style or creative concepts. The host coding agent reads the request and inspects actual frames and audio, then writes `analysis.json` and `concepts.json` in the session directory.

Each analysis observation carries a reference interval. Unknown observations remain unknown. Exactly two or three concepts each contain an adapted storyboard using the registered inventory. The agent supplies creative interpretation; the CLI checks evidence ranges, structure, files, durations and the storyboard contract.

```powershell
node bin/agent-video.mjs reference-check output/reference-session --json
node bin/agent-video.mjs reference-sample output/reference-session --concept product-demo --seconds 10 --out-dir output/sample-handoff --json
node bin/agent-video.mjs frameflow-export output/reference-session --concept product-demo --out-dir output/full-handoff --json
```

A sample is a short **storyboard bundle**, ready for a future Frameflow caller to build. It keeps whole initial scenes and refuses a first scene longer than the maximum; it does not invent a new cut halfway through speech. Author a shorter safe opening scene when that happens. Approval of the concept and storyboard and the actual Frameflow build remain pending in the manifest. Selecting a concept on this CLI does not manufacture user approval.

The standalone renderer remains available for ordinary Agent Video projects, but its captions/overlays are not substituted for Frameflow's separate editable tracks. A custom HTML composition is handed to Frameflow, never executed by this adapter.

## Input contracts

An inventory registers supplied media. Source windows in a storyboard always use **recording seconds**, not a rendered video's word IDs or output time.

```json
{
  "prompt": "Show the result, then the demonstration",
  "script": null,
  "footage": [
    {"name":"demo.mp4","source":"media/demo.mp4","duration":8}
  ],
  "assets": [
    {"path":"media/product.png","kind":"image"}
  ],
  "music": []
}
```

Existing Frameflow inventories may also carry a recording's prepared `folder`, an asset's `size`, or a music duration. Media identities must be unambiguous; a basename that matches multiple registered files is an error. Network URLs are not accepted as local media. File probing verifies declared usable media and selected intervals before a handoff succeeds.

The brief follows the existing Frameflow interface:

```json
{
  "title":"Product demonstration",
  "format":"reel",
  "aspect":"9:16",
  "fps":30,
  "target_seconds":8,
  "audience":"new customers",
  "tone":"clear",
  "summary":"Show the result and a short demonstration."
}
```

The adapter makes the default frame rate explicit as 30. Footage retains source seconds, including fractional values. Cut safety is checked at the actual quantized output boundaries; changing a source rate into an arbitrary integer is not used as a source-time conversion.

Supplied measured pauses use a map keyed by recording name:

```json
{
  "demo.mp4": {
    "pauses":[{"start":0.8,"end":1.4}],
    "words":[]
  }
}
```

These numbers must come from measurement, not evenly distributed transcript text. An interior footage boundary must fall at least one output frame inside a measured pause, and pauses shorter than three frames are rejected for that cut. Source start and source end are allowed. The adapter never moves a proposed cut silently. Frameflow retains its own timing preparation and final check by ear; this compatibility check does not replace them.

## Analysis and concepts

`analysis.json` has version 1 and four facets: `hook`, `captionStyle`, `visualStyle`, `audioStyle`. Each facet is either an observation with interval evidence or an explicit unknown:

```json
{"status":"observed","summary":"A close view opens on the result.","evidence":[{"start":0,"end":1,"note":"Opening frame sequence"}]}
```

```json
{"status":"unknown","summary":"unknown","evidence":[]}
```

The full document also contains `structure` (`start`, `end`, `purpose` intervals), `uncertainties` and `reviewNotes` string arrays. Put uncertainty explanations and visual intentions not expressible by the storyboard in these notes. Do not describe a measured cut candidate as proven semantic scene understanding, or unrecognized words as a verified script.

`concepts.json` has version 1 and a `concepts` array of two or three entries. Each entry has `id`, `title`, `summary`, `adaptation`, and `storyboard`. The ID uses letters, digits, underscores or hyphens and starts with a letter. Each storyboard contains `script` and ordered `scenes`; each scene has `visual` and `reason`. Supported visual types are footage, supplied asset, title and a declared HTML composition. A scene may have fixed caption text and a duration; images, titles and compositions need a duration. Word captions and supported cards are delegated to Frameflow. Footage scenes may also carry `broll` entries (`path`, optional `when`, `duration`, and clip `start`) referencing supplied assets. Phrase anchors and overlap/clamp decisions remain Frameflow's responsibility. Optional `music.cut_to_beat` is preserved; when true, timing is explicitly provisional until Frameflow rebuilds it against measured beats. Generated `voice` and `narration` are forbidden.

```json
{
  "script":"Here is the finished result.",
  "spoken_captions":false,
  "scenes":[
    {"visual":{"type":"footage","source":"demo.mp4","start":0,"end":1.1},"reason":"Open on the result"},
    {"visual":{"type":"asset","path":"media/product.png"},"duration":2,"caption":"The finished product","reason":"Show the product clearly"}
  ]
}
```

Validate an already authored storyboard independently of the reference workflow:

```powershell
node bin/agent-video.mjs frameflow-check storyboard.json --inputs inputs.json --brief brief.json --timings source-timings.json --json
```

## Handoff and programmatic use

An export includes the selected `storyboard.json`, `brief.json`, normalized `inputs.json`, measured `source-timings.json`, reference analysis, and a version-1 manifest. The manifest records concept identity, source hashes, supporting inspection-file hashes, document hashes, proposed scene source-to-output mapping, warnings, delegated capabilities, and pending approvals/build. Native timing remains Frameflow's authority, including any delegated phrase or beat resolution. Source changes between preparation and export are refused. An output directory must be new, and existing files are never overwritten.

```javascript
import {
  integrationVersion, prepareReference, checkReference,
  exportFrameflow, sampleReference, validateStoryboard,
} from 'agent-video-local';

const bundle = await exportFrameflow(sessionDirectory, {
  concept: 'product-demo', outDir: newHandoffDirectory, signal,
});
```

The public module performs no work at import time. Filesystem and media operations are asynchronous and accept cancellation where applicable. A direct `checkFrameflowFiles(inputs, storyboard, {brief, signal})` call requires the brief when checking a storyboard so it can verify source windows on the actual project frame grid. The CLI emits one JSON result on stdout with `--json`; failures have `ok:false`, an error code and a nonzero exit status. No shell is used to invoke media tools. API functions reject with an error carrying `code`.

## Capability ownership

| Necessary capability | Agent Video preparation | Frameflow development/integration |
| --- | --- | --- |
| Reference facts, detected shots and pacing | Implemented inspection and evidence contracts | Display or pass the evidence to the host agent |
| Hook, caption/look/audio analysis | Validated agent-authored observations and uncertainties | Host agent interprets actual media; no automatic recognition claim |
| Adapted concepts and variants | Two or three validated concept storyboards | Creator selection and production orchestration |
| Short sample | Safe initial-scene storyboard bundle | Build and inspect through the native editor engine |
| Supplied footage/images/music and source timing | Inventory, interval/file validation, measured-pause checks, source/output map | Existing source normalization, timing and join verification |
| Captions, titles, cards and motion graphics | Preserve supported declarations and report delegated requirements | Existing captions, brand kit and HyperFrames components |
| Word-linked picture/B-roll | Existing local standalone primitives; validate and preserve current storyboard B-roll declarations | Existing native B-roll placement, phrase resolution and overlap/clamp checks |
| Editable project and later changes | Never flatten these into the handoff | Existing IR, editor compiler, sidecar, history and human-edit reconciliation |
| Media generation | Excluded | No generation requested by this adapter |

This does not claim all Hypit features, automatic recreation of hidden source layers, or a replacement for Frameflow's native project/edit pipeline. The future developer should check the manifest version, validate against Frameflow's then-current schemas, obtain the normal approvals, prepare its own transcripts/timing, and build using the existing project workflow. Do not overwrite a hand-edited project with a fresh storyboard build; route subsequent changes through Frameflow's edit/reconciliation path.

For verification, run `npm test` and `node scripts/frameflow-smoke.mjs <new-output-directory>`. The smoke uses labeled synthetic video and measured silent intervals, not a semantic-cloning benchmark. An optional second argument points to Frameflow for read-only validation against its actual schemas using Python/jsonschema. No Frameflow source or schema is packaged. Agent Video now lives in Frameflow's repository, under Frameflow's GPL-3.0 license, and is still not published to npm.
