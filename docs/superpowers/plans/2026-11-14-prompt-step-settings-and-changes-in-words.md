# The prompt step, the settings page, and changes in words: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the creator start a video in the app, from an idea and their own material. They get a plan to approve, then a storyboard, and can ask for changes in words. All of the thinking is done by an agent on their PC (Claude Code or OpenCode) or by their own API key, which they choose on a settings page.

**Architecture:**
- **Frameflow drives every step** (approach A in the spec). The engine writes the request it already writes. A *thinker*, whether an agent run without a window or an API model, sends back only the answer. The engine checks the answer, sends any problems back for at most 3 fix rounds, and writes the files itself.
- **Long steps run as jobs**, like a build. That is a new engine command line that prints `==> ` steps, which the app's existing job runner already shows.
- **The key stays out of the renderer.** It lives in the main process, encrypted by Windows, and reaches the engine only as an environment variable of one run.

**Tech Stack:** Python 3 (engine, `unittest`), Electron + React + TypeScript + shadcn/ui + Tailwind (app, Vitest), Claude Code and OpenCode command lines, the Anthropic and OpenAI Python SDKs (already in `project/providers/`).

**Spec:** `docs/superpowers/specs/2026-11-14-prompt-step-and-thinking-design.md` (approved by Satwik, 2026-11-14). Also read the confirmed brief `.impeccable/surfaces/app.md` and `PRODUCT.md`.

## Global Constraints

### The repo
- No commits. Satwik commits only when he asks; task diffs come from working-tree snapshots.
- Never touch `.agents/`, `.gitignore` or `.claude/settings.local.json`.
- Keep each file's own line endings. The tree mixes CRLF and LF.
- GPL-3.0. Copy no code from OpenMontage (AGPL) or Hypit.

### The thinkers
- Agents built now: **Claude Code** (`claude -p`) and **OpenCode** (`opencode run`). **Codex comes later.** Each agent is one entry in a list.
- The services for an API key:
  - `anthropic`;
  - `openai`;
  - `openrouter`, at `https://openrouter.ai/api/v1`;
  - `gemini`, at `https://generativelanguage.googleapis.com/v1beta/openai/`;
  - `custom`: any OpenAI-compatible address the creator types, such as Ollama's `http://localhost:11434/v1`.

  The builder checks each address against the service's own docs.
- **The default when nothing is chosen:** Claude Code if found, then OpenCode, then ask for a key.
- A key thinker is sent text only: it picks B-roll from file names, sizes and the prompt. An agent opens the pictures itself.
- `MAX_FIX_ROUNDS = 3`. After that, the step stops and the creator is told what is still wrong, in plain words.
- An agent may read files and, for a pitch, use its web tools. **It may write nothing.** Frameflow writes every file after checking it.

### The key
- It is stored with Electron's `safeStorage`, in the app's data folder.
- It never appears in `output/`, the repository, a log, the screen, a renderer-bound IPC payload or an error message.
- The engine gets it only as `FRAMEFLOW_KEY` in one job's environment.

### Facts and composition files
- **Facts for a pitch:**
  - an agent looks them up with its own web tools;
  - an Anthropic key uses Anthropic's web search;
  - any other key puts each needed fact in the plan's open questions instead.
- **Composition files carried in a storyboard answer:** a relative path inside the video's folder, only `.html`, `.css`, `.js`, `.svg` or `.json`, at most 512 KB a file and 4 MB in all.

### Tests and live runs
- Tests never call a model or an agent, and cost nothing. They use a stand-in thinker or a fake agent script.
- Live runs need Satwik's OK first.
- Never enter a key, and never run paid generation. HyperFrames snapshot always gets `--describe false`.

### The plan, the storyboard and Undo
- One change in words is **one** undo entry.
- Changes to the plan stay a draft (`plan_draft.json`) until Approve.
- Approving a plan when a storyboard exists writes the brief and the new storyboard as one change, which one Ctrl+Z takes back.

### The screens
- Dark only.
- Full keyboard use, WCAG AA.
- Hit targets at least 32 px, the main action 40 px, an 8 px grid.
- shadcn/ui controls.
- No confirm dialogs.
- Red has two jobs only: the current scene, and something to check (plus an overrun of the target length).
- **Every new screen's look is confirmed by Satwik before it is built** (Task 1).

## Review Focus

Failure modes the spec implies that no screen's happy path exercises, most likely first. Each has its test in the task named.

1. **An agent that answers badly:**
   - chatter around the answer, no fenced JSON block, broken JSON, or a schema failure: nothing is written, and the problems go back for a fix round;
   - after 3 rounds, one plain line, with the video's files as they were. (Task 2)
2. **The key leaking:** an SDK error that echoes the key or part of it, a key in a traceback, or a settings answer sent to the renderer. Every message is redacted, and the renderer only ever sees `hasKey`. (Tasks 2 and 7)
3. **The storyboard changed while a change in words was thinking** (a hand edit, Undo, an outside edit): refused as hand edits are, and nothing is lost. (Task 5)
4. **A composition file that tries to leave the video's folder** (`../x.html`, `C:\x.html`, `/x.html`, a `.exe`, an oversize file): the answer is refused with the reason, and nothing is written. (Task 4)
5. **Leaving while it thinks** (another video, the app closed, the same step asked again): the agent's whole process tree is stopped, the files are untouched, and the creator is told. (Task 7)

---

### Task 1: Design the new screens with Satwik (a gate)

**Files:** sketches in `.impeccable/mocks/decision/` (`prompt-v*.html`/`.png`); a confirmed section in `.impeccable/surfaces/app.md`.

This is done by the controller with Satwik, one step at a time (Impeccable), as plan 3's Task 6 was. No subagent does it, and nothing after this task is built until he confirms.

- [ ] **Step 1:** Sketch the prompt step for a new video on real material: the tier-list recording, the pitch's facts.
  - The idea typed in; the material added (recordings, images or clips, music, a script, looks); the shape (Reel 9:16, YouTube 16:9, Pitch 16:9, square 1:1).
  - Where "New video" lives in the rail.
- [ ] **Step 2:** Sketch the plan:
  - title, shape, target length, audience, tone, summary;
  - each fact with its source, page and quote, marked if Frameflow could not open it;
  - each open question with "answer in a line" and "remove";
  - a change in words to the plan;
  - Approve, which is off while questions remain;
  - and for a facts-only-by-hand key, a fact with an empty source to fill in.
- [ ] **Step 3:** Sketch the settings page:
  - how Frameflow thinks: the agents with found or not found, the key's service, key, model and address, and Test;
  - its place in the app, from the rail and Ctrl K.
- [ ] **Step 4:** Sketch the change-in-words box on the storyboard and the video step, and the thinking states:
  - preparing the material, writing the plan, checking the facts, writing the storyboard, checking it, applying the change;
  - "you can leave";
  - a failure after 3 rounds;
  - an agent not found or not signed in;
  - a key refused.
- [ ] **Step 5:** Show each sketch and wait for Satwik's changes or confirm. Save the confirmed layout, sizes, copy and states as a "Prompt step" section and a "Settings" section in `.impeccable/surfaces/app.md`, naming the sketches. Ledger it.

### Task 2: The thinker

**Files:**
- Create: `project/thinkers.py`
- Modify: `project/providers/anthropic_provider.py` (an `api_key` argument, an optional web search), `project/providers/openai_provider.py` (`api_key`)
- Test: `tests/test_thinkers.py`

**Interfaces:**
- Produces:
  - `MAX_FIX_ROUNDS = 3`
  - `class ThinkError(Exception)`. Its message is one plain line, already redacted.
  - `class Thinker(Protocol)`, with:
    - `name: str` ("Claude Code", "OpenCode", "Anthropic (claude-…)", …);
    - `can_search: bool`;
    - `def answer(self, system: str, request: str, schema: dict, check: Callable[[dict], list[str]]) -> dict`. It returns the first answer that the schema and `check` both accept. Otherwise it raises `ThinkError` after `MAX_FIX_ROUNDS` fix rounds, naming what is still wrong.
  - The agents:
    - `@dataclass(frozen=True) class Agent: id: str; name: str; command: str`;
    - `AGENTS = (Agent("claude", "Claude Code", "claude"), Agent("opencode", "OpenCode", "opencode"))`;
    - `def found_agents() -> list[dict]`, giving `[{"id", "name", "found": bool, "version": str | None}]`;
    - `class AgentThinker(agent: Agent, command: list[str] | None = None, timeout: float = ...)`. `command` overrides the executable, for tests.
  - `class KeyThinker(service: str, key: str, model: str | None = None, base_url: str | None = None)`. Its services are `SERVICES = ("anthropic", "openai", "openrouter", "gemini", "custom")`, and `can_search` is true only for `anthropic`.
  - `class StandInThinker(answers: list[dict | str], can_search: bool = True)`. It returns the answers in order and records each `(system, request)` in `.asked`. A `str` answer stands for an agent's broken output.
  - `def thinker_from_env(env: Mapping[str, str] = os.environ) -> Thinker` reads:
    - `FRAMEFLOW_THINKER`: `auto`, `agent:claude`, `agent:opencode` or `key`;
    - for a key, `FRAMEFLOW_SERVICE`, `FRAMEFLOW_MODEL`, `FRAMEFLOW_BASE_URL` and `FRAMEFLOW_KEY`.

    `auto` picks the first agent found, or raises `ThinkError("No agent was found on this PC. Choose one, or add an API key, in Settings.")`.
  - `def redact(text: str, secret: str | None) -> str` replaces the secret, and any run of 8 or more of its characters, with `…`.
- **An agent's answer** is the **last fenced ```json block** in its final message. The agent is run in the repository root with read-only tools: no file writing, no shell. The builder finds each agent's flags in its own `--help` and checks them on this PC: Claude Code's `--allowedTools`/`--disallowedTools`, and OpenCode's read-only agent. A fix round is a new run whose request carries the problems.

- [ ] **Step 1: Write the failing tests** in `tests/test_thinkers.py`. A fake agent script (`sys.executable` and a temp `.py` that prints scripted outputs) stands in for an agent.
  - `test_an_answer_the_check_accepts_is_returned`: `StandInThinker([{"a": 1}])` with a check that returns `[]` gives `{"a": 1}`.
  - `test_problems_go_back_for_a_fix_round`: the answers `[{"a": 0}, {"a": 1}]` with a check that refuses `a == 0`. The second request asked carries the check's problem text.
  - `test_after_three_fix_rounds_it_stops_with_what_is_still_wrong`: four bad answers raise `ThinkError`, whose message names the last problem.
  - `test_an_agents_answer_is_its_last_json_block`: the fake agent prints chatter, a ```json `{"a": 0}` ``` block, more chatter, and a ```json `{"a": 1}` ``` block. The result is `{"a": 1}`.
  - `test_an_agent_with_no_json_block_gets_a_fix_round` and `test_broken_json_gets_a_fix_round`.
  - `test_an_agent_not_found_says_so_in_one_line`: a command that does not exist raises `ThinkError`, whose message contains the agent's name and "not found".
  - `test_a_key_never_appears_in_an_error`: a `KeyThinker` whose fake client raises an exception containing the key `sk-test-0123456789abcdef`. The `ThinkError` message contains neither the key nor `0123456789`.
  - `test_auto_picks_the_first_agent_found` and `test_auto_with_no_agent_asks_for_one`, with `found_agents` patched.
  - `test_only_an_anthropic_key_can_search`.
  - `test_service_addresses`: `openrouter` and `gemini` use the base URLs in Global Constraints, and `custom` uses `FRAMEFLOW_BASE_URL`.
- [ ] **Step 2:** Run `python -m unittest tests.test_thinkers -v`.
  Expected: FAIL (no module `project.thinkers`).
- [ ] **Step 3:** Implement `project/thinkers.py`.
  - `KeyThinker` uses the existing providers' `submit(system, user, tool, check, max_attempts)`, with a `ToolSpec` built from the schema. It passes `api_key=key` to the SDK clients, so `ANTHROPIC_AUTH_TOKEN` is never used (`frameflow/5 findings/minor findings.md`).
  - When `can_search`, `AnthropicProvider` adds Anthropic's server web search tool. Load the `claude-api` skill for its exact tool definition.
- [ ] **Step 4:** Run `python -m unittest tests.test_thinkers -v`.
  Expected: PASS. Then run `python -m unittest discover -s tests`.
  Expected: OK.

### Task 3: The plan: written, changed, answered, approved

**Files:**
- Create: `project/app_think.py`
- Modify:
  - `project/produce.py`: `brief_request(folder, inputs, can_search=True)` adds the "no web search: put each needed fact in open_questions" line when false;
  - `project/produce.py`: `storyboard_request(folder, brief=None)` takes a draft brief instead of reading `brief.json`;
  - `project/app_api.py`: `describe()["plan"]`; `videos()` lists a folder that has only `plan_draft.json`.
- Test: `tests/test_app_think.py`, `tests/test_app_api.py`

**Interfaces:**
- Consumes: `Thinker`, `ThinkError`, `StandInThinker` (Task 2); `produce.prepare`, `produce.check_brief`, `produce.brief_request`.
- Produces:
  - `PLAN_DRAFT = "plan_draft.json"`.
  - `def new_folder(root: Path, prompt: str) -> Path`: a new, unique folder under `root`, named from the prompt's first words.
  - `def start(folder: Path, prompt: str, thinker: Thinker, *, footage=(), assets=(), music=(), looks=(), script: Path | None = None, shape: str | None = None) -> dict`: prepares the material (`produce.prepare`), then writes the plan draft.
  - `def change_plan(folder: Path, words: str, thinker: Thinker) -> dict`
  - `def answer_question(folder: Path, number: int, words: str, thinker: Thinker) -> dict`, where `number` counts from 1.
  - `def edit_plan(folder: Path, fields: dict) -> dict`. Hand edits, with no thinker: any brief field, `remove_question: int`, `fact: {number, url, quote}` (filling in a source), `drop_fact: int`.
  - `def approve(folder: Path, thinker: Thinker) -> Path`, defined in Task 4. It refuses while the draft has open questions, as `_confirmed_brief` does.
  - Each returns the draft. Each answer is checked against the brief schema and `produce.check_brief`'s rules. The fact-quote check runs on Approve, as today.
  - `describe(folder)["plan"]`: the draft as a dict, or `None`.

- [ ] **Step 1: Write the failing tests** in `tests/test_app_think.py`, with `StandInThinker` and generated media (no recordings):
  - `test_start_prepares_the_material_and_writes_a_draft`: `plan_draft.json` exists, `brief.json` does not, and `inputs.json` lists the files.
  - `test_the_plan_request_is_the_brief_request`: the thinker was asked with `brief_request.md`'s text.
  - `test_a_key_that_cannot_search_is_told_to_ask_for_facts`: with `can_search=False`, the request carries the open-questions line.
  - `test_change_plan_sends_the_words_and_the_draft`, `test_answer_question_folds_the_answer_in`.
  - `test_edit_plan_removes_a_question_and_fills_a_fact`.
  - `test_a_draft_failing_the_schema_costs_a_fix_round`.
  - `test_the_draft_is_never_written_to_brief_json`.
- [ ] **Step 2:** Add `test_describe_shows_the_plan_draft` and `test_videos_lists_a_folder_with_only_a_plan` to `tests/test_app_api.py`.
- [ ] **Step 3:** Run `python -m unittest tests.test_app_think tests.test_app_api -v`.
  Expected: the new tests FAIL.
- [ ] **Step 4:** Implement it. The system prompt for every answer says the agent writes nothing and answers only with the fenced JSON block.
- [ ] **Step 5:** Run the same command.
  Expected: PASS. Then run `python -m unittest discover -s tests`.
  Expected: OK.

### Task 4: The storyboard from the plan, written with the brief as one change

**Files:**
- Modify: `project/app_think.py` (`write_storyboard`, `approve`), `project/produce.py` (`check_buildable`), `project/storyboard_edit.py` (`replace`, pair entries in the history)
- Test: `tests/test_app_think.py`, `tests/test_storyboard_edit.py`, `tests/test_produce.py`

**Interfaces:**
- Consumes: Task 3's draft and `storyboard_request(folder, brief)`.
- Produces:
  - `def write_storyboard(folder: Path, brief: dict, thinker: Thinker) -> tuple[dict, list[dict]]`. It returns the board and the composition files `[{"path": str, "text": str}]`. The answer schema is the storyboard schema plus an optional `files` array.
  - **The check:** the storyboard schema; `produce.check_storyboard`, with the carried composition files counted as present; `produce.check_buildable`; and the composition file rules in Global Constraints.
  - `def check_buildable(folder: Path, board: dict, brief: dict, inputs: dict) -> list[str]`, in `produce.py`. It is the build's own refusals as problems, up to and including the voiceover (cached, so the build reuses it). It does no HyperFrames render, no OpenShot project, no checks and no preview. The builder splits `build_ir`/`build` so the build and this share one code path.
  - `approve(folder, thinker) -> Path`:
    - refused while the draft has open questions, or a fact fails `check_brief`;
    - otherwise writes the composition files, then `brief.json` and `storyboard.json` through `storyboard_edit.replace`;
    - then removes `plan_draft.json`.
  - `def replace(folder: Path, brief: dict, board: dict, expect: str | None) -> None`, in `storyboard_edit.py`:
    - writes both files;
    - pushes an undo entry that holds both files' bytes, named so `_top` still matches it by the storyboard's version;
    - `undo` and `redo` restore both;
    - with no storyboard before (a new video), it pushes no entry;
    - `expect` is refused as `edit`'s is.

- [ ] **Step 1: Write the failing tests:**
  - `test_approve_writes_the_brief_and_the_storyboard`.
  - `test_approve_is_refused_while_questions_remain`.
  - `test_one_undo_brings_back_the_old_plan_and_storyboard`, in `test_storyboard_edit.py`: replace, undo, and both files are byte for byte as before; redo restores both.
  - `test_a_hand_edit_after_a_replace_undoes_on_its_own`.
  - `test_a_storyboard_that_would_not_build_costs_a_fix_round`: a narration longer than its footage span (Piper is stubbed as the produce tests do), so the problem text reaches the second request.
  - `test_composition_files_are_written_inside_the_video`.
  - `test_a_composition_path_outside_the_video_is_refused`, for each of `../x/index.html`, `C:/x/index.html`, `/x/index.html`, `x/run.exe` and a 600 KB file. Nothing is written in any case. (Review Focus 4.)
- [ ] **Step 2:** Run `python -m unittest tests.test_app_think tests.test_storyboard_edit tests.test_produce -v`.
  Expected: the new tests FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the same command, then `python -m unittest discover -s tests`.
  Expected: PASS, then OK.

### Task 5: Changes in words

**Files:**
- Modify: `project/app_think.py` (`change_in_words`), `project/storyboard_edit.py` (`edit_many`, `check_ops`)
- Test: `tests/test_app_think.py`, `tests/test_storyboard_edit.py`

**Interfaces:**
- Consumes: `storyboard_edit`'s operations (`move`, `delete`, `add`, `words`, `title`, `over`, `picture`, `rename_chapter`, `keep_chapter`, `remove_chapter`, `video`), `version`, `EditError`, `CHANGED`.
- Produces:
  - `def check_ops(folder: Path, ops: list[dict]) -> list[str]`: applies the ops in order to a copy and writes nothing. It returns the first refusal's words, or `[]`.
  - `def edit_many(folder: Path, ops: list[dict], expect: str, chosen=()) -> list[str]`: all the ops, one write, **one** undo entry. It is refused as `edit` is when the version moved.
  - `def change_in_words(folder: Path, words: str, expect: str, thinker: Thinker) -> dict`:
    - returns `{"notes": [...], "summary": str}`;
    - the answer is `{"ops": [...], "summary": "one line of what changed"}` or `{"refused": "why, in one line"}`;
    - the request carries the storyboard, the creator's words and the operations' schema;
    - the check is `check_ops`;
    - the version is checked again after thinking, before `edit_many`.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_change_in_words_lands_as_one_undo`: two ops, then one undo, and the storyboard is byte for byte as before.
  - `test_a_change_the_ops_cannot_make_costs_a_fix_round`.
  - `test_a_refused_change_says_why_and_changes_nothing`.
  - `test_a_storyboard_changed_while_thinking_is_refused`: the stand-in thinker edits `storyboard.json` while answering. `EditError(CHANGED)` is raised and the hand edit is kept. (Review Focus 3.)
  - `test_edit_many_is_refused_when_the_version_moved`.
- [ ] **Step 2:** Run `python -m unittest tests.test_app_think tests.test_storyboard_edit -v`.
  Expected: the new tests FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the same command, then `python -m unittest discover -s tests`.
  Expected: PASS, then OK.

### Task 6: The engine's thinking jobs and the app API

**Files:**
- Modify: `project/app_think.py` (a `main()` command line), `project/app_api.py` (`thinkers`, `edit_plan`)
- Test: `tests/test_app_think.py`, `tests/test_app_api.py`

**Interfaces:**
- Produces:
  - **The command line** `python -m project.app_think <command> FOLDER [options]`:
    - `start FOLDER --prompt P [--footage F ...] [--asset F ...] [--music F ...] [--look F ...] [--script F] [--shape 9:16|16:9|1:1]`;
    - `plan-change FOLDER --words W`;
    - `answer FOLDER --question N --words W`;
    - `approve FOLDER`;
    - `change FOLDER --words W --version V`;
    - `test`.

    Each prints its steps as `==> ` lines and its details indented four spaces, as a build does: "Preparing the material", "Writing the plan with Claude Code", "Checking the facts", "Writing the storyboard", "Checking the storyboard", "Making the change". It exits 0. On failure it exits non-zero with one plain, redacted line on stderr.
  - The thinker is chosen by `thinker_from_env()`.
  - `test` makes one small answer through the thinker and prints "Ready: <thinker name>".
  - `app_api` serve methods:
    - `thinkers`, which returns `found_agents()`;
    - `edit_plan`, which takes `{folder, fields}` and returns `describe`.

- [ ] **Step 1: Write the failing tests:**
  - `test_start_prints_its_steps`: through `main()` with the stand-in thinker injected by an environment variable for tests, `FRAMEFLOW_THINKER=standin:<json file>`.
  - `test_a_failure_is_one_redacted_line_on_stderr`.
  - `test_serve_answers_thinkers_and_edit_plan`.
- [ ] **Step 2:** Run the new tests.
  Expected: FAIL.
- [ ] **Step 3:** Implement. The `standin:` thinker is test-only. Its JSON file holds the answers.
- [ ] **Step 4:** Run `python -m unittest discover -s tests`.
  Expected: OK.

### Task 7: The main process: settings, the key, and thinking jobs

**Files:**
- Create: `app/src/main/settings.ts`, `app/src/main/settings.test.ts`
- Modify:
  - `app/src/main/engine.ts`: `job()` takes `'thinking'` and an `env`; a new `think(folder, args, env, onEvent)`;
  - `app/src/main/ipc.ts`;
  - `app/src/preload/index.ts`;
  - `app/src/shared/types.ts`.
- Test: `app/src/main/engine.test.ts`, `app/src/main/settings.test.ts`

**Interfaces:**
- Consumes: Task 6's command line, and `thinkers`/`edit_plan`.
- Produces:
  - `type Thinking = 'auto' | 'agent:claude' | 'agent:opencode' | 'key'`
  - `interface Settings { thinking: Thinking; service?: 'anthropic' | 'openai' | 'openrouter' | 'gemini' | 'custom'; model?: string; baseUrl?: string }`
  - `interface SettingsView extends Settings { hasKey: boolean; agents: { id: string; name: string; found: boolean; version: string | null }[] }`
  - `type ThinkRequest =`
    - `{ kind: 'start'; prompt: string; footage: string[]; assets: string[]; music: string[]; looks: string[]; script?: string; shape?: string }`
    - `| { kind: 'plan-change'; words: string }`
    - `| { kind: 'answer'; question: number; words: string }`
    - `| { kind: 'approve' }`
    - `| { kind: 'change'; words: string; version: string }`
  - In `settings.ts`:
    - `loadSettings(dir: string): Settings`;
    - `saveSettings(dir: string, s: Settings): void`;
    - `saveKey(dir: string, key: string): void`, through `safeStorage.encryptString`. It throws "Windows could not keep the key safely, so it was not saved." when `safeStorage.isEncryptionAvailable()` is false;
    - `forgetKey(dir: string): void`;
    - `thinkerEnv(s: Settings, key: string | null): Record<string, string>`, giving the `FRAMEFLOW_*` variables of Task 2.
  - `FrameflowApi` additions:
    - `settings(): Promise<SettingsView>`;
    - `saveSettings(s: Settings): Promise<void>`;
    - `saveKey(key: string): Promise<void>`;
    - `forgetKey(): Promise<void>`;
    - `testThinking(onEvent): Promise<void>`;
    - `newVideo(prompt: string): Promise<string>`, which returns the new folder;
    - `think(folder: string, request: ThinkRequest, onEvent: (e: BuildEvent) => void): Promise<void>`;
    - `editPlan(folder: string, fields: Record<string, unknown>): Promise<Described>`;
    - `chooseFiles(kind: 'footage' | 'assets' | 'music' | 'looks' | 'script'): Promise<string[]>`, which adds each pick to the chosen set as `chooseFile` does.
  - A thinking job for a folder stops any running one for it. Quitting stops all.
  - The renderer never receives the key. `settings()` returns `hasKey` only.

- [ ] **Step 1: Write the failing tests:**
  - `settings.test.ts`, with `safeStorage` mocked:
    - a saved key round-trips through `thinkerEnv` as `FRAMEFLOW_KEY`;
    - `SettingsView` has no key field and its JSON has no key text (Review Focus 2);
    - with encryption unavailable, `saveKey` throws its line and writes nothing;
    - `forgetKey` removes it.
  - `engine.test.ts`:
    - `think` passes `env` to the child and runs `-m project.app_think`;
    - a second `think` on the same folder stops the first (its process tree, as `stop` does);
    - `stopAll` stops a thinking job (Review Focus 5).
- [ ] **Step 2:** Run `npx vitest run src/main` in `app/`.
  Expected: the new tests FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm test` and `npm run typecheck`.
  Expected: PASS, and clean.

### Task 8: The settings page

**Files:**
- Create: `app/src/renderer/src/settings/SettingsPage.tsx`, `app/src/renderer/src/settings/SettingsPage.test.tsx`
- Modify: `app/src/renderer/src/App.tsx`, `app/src/renderer/src/shell/VideoRail.tsx` and `CommandPalette.tsx` (the way in confirmed in Task 1)

**Interfaces:** Consumes Task 7's `settings`, `saveSettings`, `saveKey`, `forgetKey` and `testThinking`. Lays out as the "Settings" section confirmed in Task 1.

- [ ] **Step 1: Write the failing tests:**
  - the agents are listed with "found" or "not found", and a not-found agent cannot be chosen;
  - choosing a key shows service, key, model, and the address for `custom`;
  - the key field is a password field, is cleared after saving, and never shows the key again ("A key is saved", with Forget);
  - Test shows its steps, then "Ready: …" or the plain failure line;
  - every control is keyboard reachable;
  - auto reads "Claude Code (found on this PC)" when found.
- [ ] **Step 2:** Run `npx vitest run src/renderer/src/settings`.
  Expected: FAIL.
- [ ] **Step 3:** Implement to the confirmed sketch.
- [ ] **Step 4:** Run `npm test` and `npm run typecheck`.
  Expected: PASS.

### Task 9: The prompt step and the plan

**Files:**
- Create: `app/src/renderer/src/prompt/PromptStep.tsx`, `app/src/renderer/src/prompt/PlanView.tsx`, and their tests
- Modify:
  - `app/src/renderer/src/shell/TopBar.tsx`: `Step` gains `'prompt'`, and Prompt is enabled;
  - `app/src/renderer/src/App.tsx`: the routing, and a new video opens on Prompt;
  - `app/src/renderer/src/shell/VideoRail.tsx`: New video.

**Interfaces:** Consumes `newVideo`, `chooseFiles`, `think` (`start`, `plan-change`, `answer`, `approve`), `editPlan` and `describe().plan`. Lays out as the "Prompt step" section confirmed in Task 1.

- [ ] **Step 1: Write the failing tests:**
  - **New video:** New video gives an empty prompt. Writing the plan is off until there is an idea. It runs `think('start', …)` with the picked files and the shape, and shows its steps.
  - **The plan:**
    - every field is editable by hand through `editPlan`;
    - an open question can be answered in a line (`think('answer')`) or removed;
    - Approve is off while questions remain;
    - a fact with no source offers the page and the quote to fill in, or Drop;
    - a change in words runs `think('plan-change')`.
  - **Approve:** it runs `think('approve')`, then lands on the storyboard step with the new storyboard.
  - **Back a step:** Prompt from the storyboard shows the approved plan as a draft. Approving it again writes a new storyboard, and the toast offers Undo, which brings both back (through the existing undo).
  - **Leaving:** leaving while it thinks keeps it running. Coming back shows its steps. The notice and toast say when it is done, as builds do.
  - **Failure:** a failure after 3 rounds shows the engine's line and keeps the draft as it was.
- [ ] **Step 2:** Run `npx vitest run src/renderer/src/prompt`.
  Expected: FAIL.
- [ ] **Step 3:** Implement to the confirmed sketch.
- [ ] **Step 4:** Run `npm test` and `npm run typecheck`.
  Expected: PASS.

### Task 10: Changes in words on the storyboard and the video step

**Files:**
- Create: `app/src/renderer/src/words/ChangeInWords.tsx`, `ChangeInWords.test.tsx`
- Modify: `app/src/renderer/src/storyboard/Storyboard.tsx`, `app/src/renderer/src/video/VideoScreen.tsx`, `CommandPalette.tsx`

**Interfaces:** Consumes `think('change', { words, version })` and the existing undo and toasts. Lays out as confirmed in Task 1.

- [ ] **Step 1: Write the failing tests:**
  - a sentence runs `think('change')` with the storyboard's current version;
  - when it is done, the storyboard reloads and the toast says the summary with Undo, and one Undo takes all of it back;
  - a refusal shows its one line;
  - a storyboard changed meanwhile shows the existing "changed outside the app" message;
  - the box is reachable from the keyboard and from Ctrl K;
  - Enter sends;
  - Esc closes it while it is not thinking.
- [ ] **Step 2:** Run `npx vitest run src/renderer/src/words`.
  Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm test` and `npm run typecheck`.
  Expected: PASS.

### Task 11: Check it against the brief

**Files:** none new. Fixes land in the files above, each with a test that fails first.

- [ ] **Step 1:** Run Impeccable's detector on the source and on each new screen's live DOM, saved as HTML, as plan 3 did. Fix every finding, or name the one you keep and why.
- [ ] **Step 2: Live, with Satwik's OK first.** These use his Claude Code and OpenCode plans:
  - a new reel from a prompt and the tier-list recording, in `output/prompt-check/` (git-ignored), with Claude Code. Watch the plan, answer an open question, approve, check the storyboard, build;
  - the same prompt with OpenCode;
  - a change in words on each;
  - back a step and approve again, then Undo;
  - a pitch prompt, checking its facts' quotes.
- [ ] **Step 3:** The settings page in the real window at 1440 × 900 and 1100 × 700:
  - choosing each agent;
  - Test;
  - a key flow up to Save, with a made-up key the creator types, and Test refused for it;
  - Forget.

  Then: red's two jobs, 32 px targets, radii, and Tab focus. Bring the window to the front first.
- [ ] **Step 4:** A real key only if Satwik gives one and says so: Test, and one plan.
- [ ] **Step 5:** Show Satwik the running app, and ask what to change.
- [ ] **Step 6:** Update the vault:
  - milestone 10;
  - the status note with the test counts;
  - the pending decision "how the app thinks without Claude Code", now decided;
  - a run note for the live runs;
  - a decision note for the thinking.

  End with a short progress note.
