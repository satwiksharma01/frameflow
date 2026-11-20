# Fixes from the plan 4 audit: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Narrow what the app's agents may read to the repository and the folders the creator picked files from. Prove the agents' limits with a live check, stop a job early on a missing file, run key mode through the real SDK, and get the repository ready to commit.

**Architecture:**
- The engine tells a thinker which of the creator's files the job uses (`material`).
- An agent turns those files into the folders it may read: `--add-dir` for Claude Code, `external_directory` allows for OpenCode. Every other folder is refused.
- `app_think` checks that the files are still where they were before it calls any thinker.

**Tech Stack:** Python 3.13 (unittest and pytest, stdlib `http.server`), the OpenAI Python SDK, Claude Code 2.1.316 and OpenCode 1.19.6 command lines, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-19-audit-fixes-design.md`

## Global Constraints

- **Commits wait for Satwik's word:** nothing is committed until he says "commit". This replaces the per-task commit steps; Task 7 commits.
- **Live runs are the controller's:** only the controller runs a real agent, model or key, in Tasks 4 and 6, and only after Satwik's OK. Implementers use `StandInThinker`, fakes and local servers.
- **Line endings:** keep each file's own (the tree mixes CRLF and LF), checked by bytes.
- **Copy, verbatim:** `<file name> was moved or deleted. Put it back where it was, or make a new video with it.`
- **CI on Ubuntu and Windows:** tests needing Claude Code, OpenCode, OpenShot, Piper or Pillow skip when those are missing.
- **Commit messages:** plain sentences in the repository's style (for example "Run Agent Video's tests in CI from a temp folder with a long path"), with no co-author lines.

## Review Focus

1. **A picked file in a folder whose name has spaces or non-ASCII letters** (`C:\Users\x\My Videos\Ränge\a.png`). Its folder must still be readable to both agents (Task 2 test).
2. **Material on a network path** (`\\server\share\a.mp4`). The job must still run; that folder is simply not opened (Task 2 test).
3. **A recording whose original was deleted after Frameflow made its own frame-rate copy** (`source` in `output/`). The job still runs, since the build reads only `source` (Task 1 test).
4. **A deleted music file or look, not only a recording.** The job stops on it by name (Task 1 test).
5. **Thirty pictures from the same two folders.** Exactly two folders are opened, so the command line stays short (Task 2 test).

---

### Task 1: Stop before thinking when a file the video uses is gone

**Skills:** superpowers:test-driven-development

**Files:**
- Modify: `project/app_think.py` (`start`, `_think`, `approve`, `change_in_words`)
- Test: `tests/test_app_think.py`

**Interfaces:**
- Produces: `_material(inputs: dict) -> list[Path]`, every file the build reads.
  - Each footage entry gives its `source`. The original picked file (`stamp["path"]`) is not included: once Frameflow has its own copy, the original may go.
  - Each `assets`, `music` and `looks` entry gives its `path`.
  - The list is deduplicated and keeps its order.
- Produces: `_check_material(paths: Iterable[Path]) -> None`, which raises `ThinkError(MISSING.format(name=path.name))` for the first path that does not exist.
- Produces: `MISSING = "{name} was moved or deleted. Put it back where it was, or make a new video with it."`

- [ ] **Step 1: Write the failing tests**
  - `test_a_recording_gone_since_it_was_prepared_stops_approve_before_any_thinking`: prepare a folder, delete its footage `source`, then call `approve` with a `StandInThinker([])`. It raises `ThinkError`, its text equals `MISSING.format(name=<source file name>)`, and `thinker.asked == []`.
  - `test_a_deleted_music_file_or_look_stops_a_change_in_words`: delete the music file, then call `change_in_words`. It raises with the music file's name, and nothing is asked. Repeat with a look in a subtest.
  - `test_a_start_given_a_file_that_is_not_there_says_so_in_words`: call `start` with `footage=[Path("gone.mp4")]`. It raises `ThinkError(MISSING.format(name="gone.mp4"))`, not an `OSError`, and `produce.prepare` is not called.
  - `test_a_recordings_original_may_go_once_frameflow_has_its_copy`: prepare a folder, delete the footage's `stamp["path"]` but keep its `source`, then call `approve` with a `StandInThinker` holding a valid storyboard answer. It does not raise `MISSING`, and `_material(inputs)` equals `[Path(source)]`.
- [ ] **Step 2: Run** `python -m pytest tests/test_app_think.py -q -k "gone or deleted or not_there or original_may_go"`. Expected: 4 FAIL (`_material` undefined, or no ThinkError).
- [ ] **Step 3: Implement** `_material`, `_check_material` and `MISSING`.
  - Call `_check_material` on the given files in `start`, before `prepare`.
  - Call `_check_material(_material(inputs))` at the top of `_think`, `approve` and `change_in_words`, before their thinker call.
- [ ] **Step 4: Run** `python -m pytest tests/test_app_think.py -q`. Expected: all pass.

### Task 2: The agents read the repository and the picked folders, nothing else

**Skills:** superpowers:test-driven-development, security-and-hardening, source-driven-development (Claude Code's permissions page: working directories, `--add-dir`, `blockReadsOutsideWorkingDirectories`; OpenCode's permissions page: `external_directory`, last match wins)

**Files:**
- Modify: `project/thinkers.py` (`Thinker`, `Agent`, `_claude_args`, `_opencode_env`, `AgentThinker`, `KeyThinker`, `StandInThinker`)
- Modify: `project/app_think.py` (the four `thinker.answer` calls)
- Test: `tests/test_thinkers.py`, `tests/test_app_think.py`

**Interfaces:**
- Consumes: `_material` (Task 1).
- Produces: every thinker's `answer(system, request, schema, check, *, search: bool = False, material: Sequence[Path] = ()) -> dict`.
  - `KeyThinker` ignores `material`.
  - `StandInThinker` appends each call's `material` to `self.material: list[list[Path]]`.
- Produces: `Agent.args` and `Agent.env` take `(search: bool, folders: Sequence[Path])`.
- Produces: `_folders(material: Sequence[Path]) -> list[Path]`: the resolved parents that lie outside `REPO_ROOT`.
  - Network paths (a resolved path starting `\\`) are dropped.
  - The list is deduplicated and keeps its order.

- [ ] **Step 1: Write the failing tests** in `tests/test_thinkers.py`.
  - `test_claude_code_reads_the_repository_and_the_picked_folders_only`. With folders `[D:/clips, C:/Users/x/My Videos/Ränge]`, `_claude_args`:
    - holds `--add-dir` followed by both folders and then an argument starting with `--`, since `--add-dir` takes a list; with no folders, it holds no `--add-dir`;
    - has `--settings` whose JSON holds `"permissions": {"blockReadsOutsideWorkingDirectories": true}` and `"disableAllHooks": true`;
    - has an `--allowedTools` value without Read, Glob or Grep: `WebSearch,WebFetch` with search, and no `--allowedTools` at all without.
  - `test_opencode_reads_the_repository_and_the_picked_folders_only`. The agent JSON's `external_directory` is the ordered map `{"*": "deny", "D:\\clips\\*": "allow", ...}`, with each folder written `str(folder) + os.sep + "*"`.
  - `test_env_files_are_refused_to_both_agents`. Claude Code's `--disallowedTools` holds `Read(//**/.env)`, `Read(//**/.env.*)`, `Read(//**/*.env)` and `Read(//**/.envrc)`. OpenCode's `read` map denies `*.env`, `*.env.*` and `*.envrc`.
  - `test_the_folders_an_agent_may_read`. Three subtests:
    - thirty files from two folders give two folders;
    - a file inside `REPO_ROOT` gives none;
    - `\\server\share\a.mp4` gives none.
- [ ] **Step 2: Write the failing test** `test_each_step_tells_the_thinker_the_videos_material` in `tests/test_app_think.py`. A plan, an approve and a change in words each pass `_material(inputs)` as `material`, which `StandInThinker.material` shows.
- [ ] **Step 3: Run** `python -m pytest tests/test_thinkers.py tests/test_app_think.py -q`. Expected: the new tests FAIL.
- [ ] **Step 4: Implement:**
  - thread `material` from the four `answer` calls in `app_think.py` through `AgentThinker.answer` to `_run`;
  - `_run` computes `_folders(material)` and passes `(search, folders)` to `args` and `env`;
  - keep `cwd=REPO_ROOT`;
  - give `KeyThinker` and `StandInThinker` the new keyword.
- [ ] **Step 5: Run** `python -m pytest tests/test_thinkers.py tests/test_app_think.py -q`, then `python -m unittest discover -s tests` (715 before). Expected: all pass.
- [ ] **Step 6: Check OpenCode's own reading of the rules** (no model call). Run `opencode debug agent frameflow` with `OPENCODE_CONFIG_CONTENT` from `_opencode_env(False, [Path("D:/clips")])`. Expected: the last `external_directory` rules are `* deny` and then `D:\clips\* allow`, and `bash`, `edit` and `write` are false.

### Task 3: Key mode through the real OpenAI SDK

**Skills:** superpowers:test-driven-development

**Files:**
- Test: `tests/test_thinkers.py` (no production code is expected; if the test exposes a defect, fix it in `project/providers/openai_provider.py` or `KeyThinker`)

**Interfaces:**
- Consumes: `KeyThinker(service="custom", key=..., model=..., base_url=...)` and `main(["test"], env)` from `project/app_think.py`.

- [ ] **Step 1: Write the test** `test_a_key_reaches_an_openai_compatible_address_through_the_real_sdk`.
  - Start an `http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)` on a thread. It answers every POST with the chat-completion response that `OpenAICompatibleProvider` expects; read that file for the shape (plain content, or a tool call). The answer is `{"ready": true}`.
  - Run `main(["test"], {"FRAMEFLOW_THINKER": "key", "FRAMEFLOW_SERVICE": "custom", "FRAMEFLOW_BASE_URL": f"http://127.0.0.1:{port}/v1", "FRAMEFLOW_MODEL": "test-model", "FRAMEFLOW_KEY": "made-up-key"})`.
  - Assert:
    - it returns 0, and stdout starts with `Ready: `;
    - the server saw a path ending `/chat/completions`;
    - the server saw the header `Authorization: Bearer made-up-key`;
    - the JSON body had `"model": "test-model"`.
- [ ] **Step 2: Run** `python -m pytest tests/test_thinkers.py -q -k real_sdk`. Expected: PASS, or a FAIL that names a real defect. Fix that defect test-first, and say so in the report.

### Task 4: The live check against the real Claude Code (opt-in)

**Skills:** superpowers:test-driven-development, security-and-hardening

**Files:**
- Create: `tests/test_live_agents.py`, skipped unless `FRAMEFLOW_LIVE_AGENT=claude` is set (so skipped in CI)

**Interfaces:**
- Consumes: `AgentThinker` for Claude Code, and `answer(..., material=...)` from Task 2.

- [ ] **Step 1 (implementer): Write the tests.**
  - Each creates its own canary values with `secrets.token_hex(4)`.
  - Each names files to the agent, never the canary values.
  - Each answers to the schema `{"found": string}`.
  - The tests:
    - `test_an_env_file_can_be_neither_read_nor_grepped`: `output/live-agent-check/.env` holds `CANARY_SECRET=<v>`. The request asks the agent to Read that file and to Grep `output/live-agent-check` for `CANARY_SECRET`. Assert `<v>` is not in the answer.
    - `test_outside_the_repository_only_a_picked_folder_can_be_read`. Two temp folders outside the repository: A holds `picked.txt` with `MATERIAL_<a>`, B holds `other.txt` with `OUTSIDE_<b>`. Pass `material=[A/picked.txt]` and ask for both files. Assert `<a>` is in the answer (the positive control) and `<b>` is not.
    - `test_the_creators_plugin_hooks_do_not_run`. Ask, with Frameflow's flags, whether the context holds the words `PONYTAIL MODE ACTIVE`, injected by the ponytail plugin's SessionStart hook on this PC. Expect "no".
      - The positive control: the same question through `claude -p` with the same tools but no `--settings` must say "yes".
      - If the control says "no", call `skipTest("no hook on this PC to observe")`.
- [ ] **Step 2 (controller, with Satwik's OK; about six small Claude Code requests):** run `FRAMEFLOW_LIVE_AGENT=claude python -m pytest tests/test_live_agents.py -v`. Expected: 3 passed.
- [ ] **Step 3 (only if the Grep part fails):**
  - Take Grep away from both agents: drop `Grep` from Claude Code's `--tools`, and set OpenCode's `"grep": "deny"`.
  - Update Task 2's tests to match, test-first.
  - Re-run Step 2. Expected: 3 passed.

### Task 5: Repository hygiene

**Skills:** ci-cd-and-automation

**Files:**
- Modify: `.gitignore`, `.github/workflows/ci.yml:36`

- [ ] **Step 1:** Add `.impeccable/` and `PRODUCT.md` to `.gitignore`, each under a one-line comment saying why: the design brief and product facts stay on this PC (Satwik, 2026-11-19).
- [ ] **Step 2: Run** `git check-ignore -v .impeccable/surfaces/app.md PRODUCT.md`. Expected: both are named as ignored.
- [ ] **Step 3:** Change the app step's `run:` to `npm ci && npm run typecheck && npm test`.
- [ ] **Step 4: Run** `npm run typecheck` in `app/`. Expected: exit 0.

### Task 6: The window and live checks (controller)

**Skills:** superpowers:verification-before-completion

- [ ] **Step 1: Restart the dev app**, since main and the engine changed.
  - Run a 20-line scratch OpenAI-compatible server on `127.0.0.1` that answers `{"ready": true}`.
  - In Settings, choose Another address with it, a made-up key and `test-model`, then press Test. Expected: `Ready: http://127.0.0.1:<port>/v1, test-model`.
  - Forget the key, and restore Settings to Automatic.
- [ ] **Step 2 (Satwik's OK):**
  - Make a new video whose picture is in a temp folder outside the repository, and write its plan with Claude Code. Expected: the plan is written, and the steps show no refusal.
  - Delete the picture, then press Approve. Expected: `<name> was moved or deleted. Put it back where it was, or make a new video with it.`, and no "Writing the storyboard" step.

### Task 7: Record, then commit at Satwik's word

**Skills:** git-workflow-and-versioning, ci-cd-and-automation

- [ ] **Step 1: Update the vault** (the project's notes, per their `AGENTS.md`):
  - `pending decision - what the app's agent may read` is marked decided, with Satwik's words, and a decision note is written for it;
  - the live check's results go in `5 findings/minor findings.md`;
  - the skipped items 2.2 and 2.3, with their reasons, go in milestone 10;
  - the status note gets the new test counts;
  - the engine backlog 3.1 to 3.4 is named as the next plans.
- [ ] **Step 2 (Satwik says "commit"):** make three commits, each staged by path first and then committed by path, never with `git add -A`. Use `git add -- <paths>` then `git commit -m "…" -- <paths>`: `git commit -- <paths>` alone skips files git does not track yet, and most of this work is new files.
  1. **The engine:** `project/`, `tests/`;
  2. **The app:** `app/`, `.github/workflows/ci.yml`, `.gitignore`;
  3. **The docs:** `docs/superpowers/`.

  Ask Satwik about the files staged before this work (the `.agents/skills/*` deletions) and about `.claude/agents/`, `.claude/launch.json` and `.claude/skills/impeccable/`. Leave them out unless he names them.
- [ ] **Step 3 (Satwik says "push"):**
  - `git fetch`, then push `master`.
  - Watch CI on both systems. Any failure becomes a fix with a test that fails first, in its own commit.
- [ ] **Step 4 (CI green, and Satwik says so):** delete the `main` branch on GitHub (`gh api -X DELETE repos/satwiksharma01/frameflow/git/refs/heads/main`), and log the push in `frameflow github log`.

## Not built, on purpose

- **2.2** and **2.3**: the spec's table gives the reasons, and Satwik said to skip them and record why.
- **1.2's "prompt-only" claim:** it was wrong. Task 2's tests pin the tool limits it doubted.
- **3.1 to 3.4:** one spec and plan each, after this plan, in an order Satwik picks.
- **4.3:** the app's chapters and its typeface stay his open decisions.
