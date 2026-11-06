# Agent video tool: capability map

The desired experience is an agent that turns a brief and supplied media into an editable project, checks it, renders a video, and makes requested variants. All implementation and agent instructions will be written independently.

| Module id | Responsibility | Depends on |
| --- | --- | --- |
| project-format | An original declarative project format for assets, clips, text, audio, and timing; validation with useful diagnostics | — |
| render-engine | Turn a validated project into a local video using independently selected rendering tools | project-format |
| job-runner | Plan and execute renders; retain progress, outputs, and errors without silently overwriting files | render-engine |
| agent-workflow | Original agent instructions and a CLI for creating, checking, rendering, and revising projects | project-format, job-runner |
| reference-inspection | Probe local reference media, measure cuts, save representative frames and reconstruct an editable starting project | project-format, render-engine |
| local-transcription | Decode local audio and obtain actual word timestamps from configured whisper.cpp | reference-inspection |
| composition | Supplied-media overlays, clip effects, audio fades, and speech-linked picture timing | project-format, render-engine |
| execution-resume | Retain snapshots and verified segments; resume unfinished jobs/batches with output and state protection | job-runner |
| reference-preparation | Original measured reference/pacing evidence plus validated host-agent observations and concept storyboards | reference-inspection |
| frameflow-handoff | Validate supplied-media storyboard/source-time contracts, export source mappings and provenance, and prepare whole-scene sample bundles | reference-preparation |

Implemented dependency direction: project-format → render-engine → job-runner → agent-workflow; reference-inspection/local-transcription and composition connect through these boundaries; execution-resume builds on job-runner. Generation services were explicitly excluded by the user.

First runnable milestone: an agent can author a project using local media, validate it, render an MP4, change captions or media, and render a second variant. Include a small example requiring no paid services. Preserve supplied audio where requested and report missing media or unavailable render tools clearly.

The later supplied-media work adds actual local speech recognition, picture/caption anchors, reference inspection/reconstruction, compositing, efficient batches and explicit resume. Generated footage, images and voices are outside the requested tool.

The operator supplies media and, for transcription, a local recognizer/model. The coding agent supplies creative decisions through the original skill. No generation account or API credentials are required.

The 1.1 Frameflow preparation scope leaves its main integration, native rendering, captions/graphics, source normalization and human-edit reconciliation with Frameflow. Read FRAMEFLOW.md for the capability ownership matrix. This is not a claim of all Hypit features or a replacement editor backend.

The user approved the initial map and later requested the complete tool with generation excluded. The current implementation covers the supplied-media workflow above. Full-goal verification is recorded in COMPLETION.md and VERIFICATION.md; this is an independent implementation, not a compatible Hypit distribution or a claim of recovering its private project data.
