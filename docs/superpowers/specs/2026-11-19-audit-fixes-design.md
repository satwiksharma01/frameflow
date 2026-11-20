# Fixes from the plan 4 audit: design

**For:** the items of the outside audit of plans 1–4 (`frameflow_plan_4_code_security_audit.md`, 2026-11-19, written from the plan 4 wrap-up and the vault's status note, not from the code).
**Decided with Satwik:** 2026-11-19. What he decided is marked as his; everything else is my call, checked against the code and the agents' own documentation.
**Related:** the vault's `pending decision - what the app's agent may read`; `docs/superpowers/specs/2026-11-14-prompt-step-and-thinking-design.md` (plan 4).

---

## What the audit got right, and what it did not

| Audit item | Verdict | Built here |
|---|---|---|
| 1.1 The agent may read the whole PC | Real | Yes (R1) |
| 1.2 Write and shell protection is prompt-only | Wrong: Claude Code runs with `--tools Read,Glob,Grep` (web tools only on a plan step), and OpenCode's agent resolves to `bash`, `edit` and `write` off (`opencode debug agent frameflow`) | No |
| 1.2 `.env` coverage | Partly real: Claude Code applies `Read` deny rules to Grep and Glob only "best-effort" (its permissions page), and `.envrc` is not denied | Yes (R2, R3) |
| 1.3 The `.env` and hooks flags are not checked live | Real | Yes (R3) |
| 1.4 Files a commit would make public | Checked: everything is ignored but `.impeccable/` and `PRODUCT.md`; no keys found in the changed files | Yes (R4) |
| 2.1 A missing file wastes agent runs | Real at Approve and in a change in words; a plan fails first, but on a raw OS line | Yes (R5) |
| 2.2 An unsent edit is lost when Approve lands | Not needed: the change field is read-only while any job runs, and the lost draft belongs to a storyboard being replaced, which the engine would refuse | No (Satwik: skip, record why) |
| 2.3 Refresh button for agents | Not needed: Settings looks for the agents afresh when it opens, and a missing agent's line points there | No (Satwik: skip, record why) |
| 2.4 Key mode never run | Real; no local model server is installed on this PC | Yes (R6) |
| 3.1–3.4 Engine backlog | Real, but four independent features from the status note's open items | No: one spec and plan each, after this (Satwik) |
| 4.1 Split the commit | Agreed | Yes (R8) |
| 4.2 CI on Ubuntu and Windows | `ci.yml` already runs both suites on both systems; it lacks the typecheck | Yes (R7) |
| 4.3 Three open decisions | The read scope is decided here; chapters and the typeface stay open | Vault (R9) |

## Requirements

- **R1. Read scope (Satwik's):** the agent "should be able to read all the things that are necessary for its working and the folder that the user selects, the same way that works in Claude."
  - It may read the repository, which holds the skills, the schemas and every video's folder under `output/`, and the folders of the files this video's build reads (the recording's own copy and the pictures, clips, music and looks).
  - Everything else is refused.
  - **Claude Code:** the repository is its working directory. Each picked folder is passed with `--add-dir`. `permissions.blockReadsOutsideWorkingDirectories` is set to `true`, and Read, Glob and Grep leave `--allowedTools`. A bare `Read` there pre-approves reads anywhere, which is today's leak.
  - **OpenCode:** `external_directory` is denied, except each picked folder.
  - A network path (`\\server\share`) cannot be a Claude Code working directory, so it is left out. Its file is still described in Frameflow's own request.
- **R2. `.env` files:** `.env`, `.env.*`, `*.env` and `.envrc` are refused to Read, for both agents.
- **R3. Live check:** an opt-in test against the real Claude Code shows four things.
  - A `.env` value cannot be read or grepped.
  - A folder outside the repository is refused unless it holds picked material.
  - A picked folder can be read, as the positive control.
  - The creator's plugin hooks do not run.

  If Grep reaches the value, Grep is taken away from both agents.
- **R4.** `.impeccable/` and `PRODUCT.md` stay on this PC, ignored by git (Satwik's).
- **R5.** Before any thinking (a plan, an answer, Approve, a change in words), a file the video uses that is no longer where it was stops the job with one line. The line is: `<file name> was moved or deleted. Put it back where it was, or make a new video with it.`
- **R6.** Key mode runs once through the real OpenAI SDK against a local OpenAI-compatible server, in the tests and in Settings' Test in the window. A real key runs only if Satwik enters one.
- **R7.** CI runs `npm run typecheck` before the app's tests. Once it is pushed, both systems are green before the `main` branch is deleted.
- **R8.** At Satwik's word, the work is committed in layers: the engine, then the app with CI and the ignore list, then the docs. There are no co-author lines (the notes' `AGENTS.md`). Files staged before this work, such as the `.agents/` deletions, are his to place.
- **R9.** The vault records the read scope as decided, the live check's result, and the two skipped items with their reasons.
