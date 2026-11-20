# The prompt step, the settings page, and changes in words: design

**For:** plan 4 of 4 of Frameflow's desktop app (`app/`), on top of plans 1–3 (the storyboard, editing it, the video step).
**Decided with Satwik:** 2026-11-14, in conversation. What he decided is marked as his; everything else is marked as my call.
**Related:** `.impeccable/surfaces/app.md` (the confirmed brief), `PRODUCT.md`, the produce skill (`.claude/skills/produce/SKILL.md`), the vault's `pending decision - how the app thinks without claude code`.

---

## Intent

The app has the second and third of its three steps: the storyboard and the video. It cannot yet start a video.

Today the thinking is done by Claude Code in a chat, following the produce skill. That covers the brief, the storyboard, and changes asked for in words. The engine writes a request file, Claude Code writes the answer, and the engine checks it.

Plan 4 brings that thinking into the app:

- **The prompt step.** The creator says what they want and adds their own material. Frameflow writes a plan, which is the brief. The creator approves or changes it, then Frameflow writes the storyboard and opens it on the storyboard step.
- **A settings page.** The creator chooses what does the thinking.
- **Changes in words.** On the storyboard and video steps the creator can ask for a change in a sentence, and it lands as one change they can undo.

**Why:**
- The product's job is "idea to a postable video, approving each step (prompt, plan, storyboard, video)". Without the first step, the app only works on videos someone made in a chat.
- **Satwik's:** the app must be versatile. A creator can think with an agent already on their PC, or with their own API key, "cause when we scale user must have options".

## Goals

1. **A new video from the prompt step.** The creator:
   - types the idea;
   - adds recordings, images or clips, music, a script, or colour looks (`.cube`);
   - picks the shape: Reel 9:16, YouTube 16:9, Pitch 16:9 or square 1:1.

   Frameflow prepares the material, then writes the plan.
2. **The plan, for approval.** It shows title, shape, target length, audience, tone and summary. For a pitch it also shows each fact with who says it, its page, and the quoted words, marking the ones Frameflow could not open. Open questions are listed too.
   - The creator can change any field by hand, or ask for a change in words ("make it 30 seconds, for founders").
   - Approve writes the storyboard. Nothing is written before approval, and nothing is built before the storyboard step's own Build.
3. **Back a step.** From the storyboard the creator can go back to the plan, change it, and have the storyboard written again. They are told first that this replaces the storyboard. This is not a confirm dialog: the replaced storyboard can be put back with Undo, as every change can.
4. **The settings page.** It has one section for now, how Frameflow thinks:
   - **An agent on this PC.** Frameflow lists the agents it knows, marks those it finds installed, and the creator picks one. Built now: **Claude Code** and **OpenCode**, the two on this PC. **Codex** comes later (Satwik's), when its command-line tool is installed. Each agent is one entry: how to find it and how to run it without a window.
   - **An API key.** The creator picks a service:
     - Anthropic;
     - OpenAI;
     - OpenRouter;
     - Gemini through its OpenAI-compatible address;
     - any other OpenAI-compatible address, including a model on the creator's own PC through Ollama.

     They then paste the key, pick or type a model, and press **Test**, which makes one small call.
   - **My call:** when nothing is chosen, Frameflow uses Claude Code if it finds it, then OpenCode, then asks for a key.
5. **Changes in words**, on the storyboard and the video step. A sentence goes to the thinker with the current storyboard. The answer comes back as the edits the app already makes by hand: move, delete, add, words, title, what is over a scene, picture, chapters, the whole video's settings.
   - The whole answer lands as **one change**, so one Ctrl+Z or the toast's Undo takes all of it back.
   - It is refused, as hand edits are, if the storyboard changed meanwhile.
   - The creator is told in one line what was changed.
6. **Steps as they happen.** While the thinker works, the screen shows each step: preparing the material, writing the plan, checking the facts, writing the storyboard, checking it, applying the change. The creator can leave the screen and is told when it is done, by the toast and the desktop notice that builds already use.

## Non-goals (for plan 4)

- **An MCP toolbox** that would let the AI drive Frameflow itself. **Satwik's:** "we will create a mcp for this in future".
- **Codex**, until its command-line tool is on the PC. **Satwik's.**
- **My calls, each kept for its own plan:**
  - a video made like a reference video (Agent Video's analysis and concepts);
  - several shorts from one recording;
  - a first cut of one raw recording;
  - the publish package.
- **Settings beyond how Frameflow thinks:** the brand kit, first run, export. These stay out, as the brief has them.
- **Paying for anything** without the creator's say: generated pictures and clips keep their $0 cap.

## Anti-goals

- A thinker that writes files Frameflow has not checked. Every answer goes through the same checks a chat-written one does today.
- A key that ends up on screen, in a log, in a video's folder or in an error message.
- An app that works only with Claude Code.
- A change in words that cannot be undone in one step, or that silently overwrites a hand edit.
- Copying code from OpenMontage (AGPL) or Hypit.

## Approaches

Three ways were considered.

**A. Frameflow drives, and the thinker writes one answer at a time. Chosen.** For each step Frameflow writes the request it already writes:
- `brief_request.md` for the plan;
- `storyboard_request.md` for the storyboard;
- for a change in words, the storyboard with the sentence.

The thinker sends back only the answer. Frameflow checks it. If it has problems, they go back to the thinker for a fix, for a few rounds, and each step is shown on screen.

- **Gains:**
  - one path for an agent and for a key;
  - Frameflow keeps the files, the checks and the steps;
  - a change in words is an ordinary edit with Undo;
  - a new agent or key service is one entry.
- **Costs:** a thin layer in the engine that sends a request to a thinker and reads the answer back.

**B. The agent drives, as in a chat today.** The app tells the agent to follow the produce skill, and the agent runs Frameflow's commands itself.
- **Gains:** little new code for Claude Code.
- **Costs:**
  - the app can only guess which step the agent is on;
  - each agent behaves differently;
  - an API key cannot run commands, so it would need a second path;
  - a change in words would skip Undo.

**C. Give the thinker Frameflow's actions as tools**, an MCP server for agents and tool calls for keys. The thinker decides what to do and when.
- **Gains:** one toolbox for everything, usable outside the app too.
- **Costs:**
  - the most work;
  - the order is the AI's, so the app has to follow it;
  - nothing for the app that A does not give.

**Satwik chose A.** In his words: "for now ai only has to do the required work like generation, editing etc", with C "in future".

## How it works (the parts decided)

### The thinker, one interface

The engine gains one layer: a thinker takes a request and returns an answer that passes a check. It has two kinds.

- **Key thinkers** use the provider layer the engine already has (`project/providers/`):
  - `submit(system, user, tool, check, max_attempts)` is a tool-calling loop that resends the checker's problems until the answer is accepted;
  - Anthropic and OpenAI-compatible providers exist; OpenRouter, Gemini's compatible address and Ollama are OpenAI-compatible addresses;
  - this layer has never been run live.
- **Agent thinkers** run the agent without a window, in the repository, with the request and an instruction to write only the answer:
  - Claude Code: `claude -p`;
  - OpenCode: `opencode run`.

  Frameflow reads the answer, checks it, and resends the problems in a new run. The agent may read files and, for a pitch, use its web tools. **My call:** it may not write the video's files; Frameflow writes them after checking.
- **My call:** at most **3 fix rounds**. After that the step stops and the creator sees what is still wrong, in plain words.
- **Errors, said in one plain line each:**
  - the agent is not found, not signed in, or out of its usage;
  - the key is wrong;
  - the account is out of credit;
  - the service is unreachable;
  - the thinker took too long.

  None of these may show a traceback or the key.

### The three answers

1. **The plan.** `brief.json`, against the brief schema, then the existing check, which opens every fact's page to look for its quote.
2. **The storyboard.** `storyboard.json`, with any composition files it carries, checked as below.
3. **A change in words.** A list of the existing storyboard operations (`project/storyboard_edit.py`). Each one is checked as a hand edit is, and all are applied as one change, which is one entry in the undo history. It needs a way to apply several operations as one; today each operation is one entry.

**My call: what counts as a check failure for the storyboard, and so costs a fix round.**

- Failures:
  - the schema;
  - the existing `check_storyboard`;
  - everything the build itself would refuse, such as narration longer than its footage span, or a file that does not exist. This means a dry run of the build's own validation, with no rendering.
- Not failures. These stay instructions, as they are in a chat today:
  - about 30 scenes at most for a long video;
  - chapters past about 12 scenes;
  - spans in measured pauses, which the build already snaps into pauses;
  - using only the brief's facts. No code can check that.

**My call: compositions and overlays.** For a video made only from a prompt, HyperFrames compositions are the graphics, so the storyboard answer may carry them.

- Each comes as a set of files with its path inside the video's folder and its text. Frameflow writes them after checking:
  - the path stays inside the video's folder;
  - only web text files (`.html`, `.css`, `.js`, `.svg`, `.json`);
  - a size limit.
- An agent writes nothing itself, as for the other answers.
- The build's HyperFrames render is their real check. A composition that fails to render fails the build, which the creator sees as today.

### The plan: open questions, approval, and going back

**My calls:**

- **Open questions.** The plan's open questions are listed with it. The creator can:
  - answer one in a line, which goes to the thinker as a change in words to the plan;
  - or remove it.

  Approve is offered once none is left, as the engine already requires (`_confirmed_brief` refuses a storyboard while `open_questions` is not empty).
- **Facts the thinker could not look up.** The creator can add the page and the words on it for each one, or drop it. Facts about the creator's own product need no source, as in a chat today.
- **Changes to the plan stay a draft until Approve.** Nothing is written to `brief.json` until then, so a build in between never mixes a new plan with an old storyboard.
- **Approving a changed plan when a storyboard exists.**
  - Approve writes the plan and the new storyboard together, as one change.
  - Its undo entry holds both files, so one Ctrl+Z brings back the old plan and the old storyboard together. Today's history keeps only `storyboard.json`, so it grows to hold the brief as well for this kind of change.
  - Hand edits and changes in words on the storyboard stay as they are: one file per entry.

### Facts for a pitch

The facts come in three ways, depending on the thinker:
- an agent looks them up with its own web tools;
- an Anthropic key uses Anthropic's web search;
- any other key cannot look things up, so the plan puts each needed fact in its open questions for the creator, rather than letting a model state facts from memory.

The existing check then opens every page either way.

### Pictures

**My call:**
- **An agent** opens the creator's images and clip frames itself to choose B-roll, as in a chat today.
- **A key thinker** is sent text only in plan 4, so it chooses B-roll from the files' names, sizes and the prompt. Sending pictures needs new multi-part messages in both providers, more cost on the creator's key, and it fails on text-only models, many of Ollama's included.

This is a known limit, listed for a later plan.

### Keys and settings

- **My call:** the key is stored with Electron's `safeStorage` (encrypted by Windows for this user) in the app's own data folder, never in `output/` or the repository.
- The engine receives it for the run only, as an environment variable of that process, and never writes it.
- The settings themselves, meaning which thinker and which service and model, sit beside it in a plain file.

### Testing

- Tests use a stand-in thinker, so no test calls a model or costs anything.
- **Live checks:**
  - **Claude Code and OpenCode on this PC.** They use Satwik's own plans; he is asked before the first live run.
  - **A key only with Satwik's own key, when he says.** He enters it himself.

## The screens: designed with Satwik, one step at a time

The prompt step, the plan, the settings page and the place to ask for a change in words are new screens and parts. **Satwik's rule:** "ask me before finalizing anything", step by step under his control.

So the plan's first task is a gate, as plan 3's Task 6 was. The screens are sketched in the confirmed Swiss direction, using the existing tokens, type, corners and red's two jobs, on real material. Nothing is built until he confirms. Their layout, wording and sizes are decided there, not here.

Constraints the sketches must keep, from the brief:
- dark only;
- full keyboard use, WCAG AA;
- targets at least 32 px, the main action 40 px, an 8 px grid;
- shadcn/ui controls;
- no confirm dialogs;
- every step can be revisited.

## Left to the builder

- The exact command-line arguments for each agent, from its own help, checked on this PC.
- How an agent's answer is found in its output: a marked block or a file.
- The default model offered for each key service.
- How long a step may take before it is stopped.
- Where the settings file lives in the app's data folder.
- How the prompt step's material is picked: the Windows file dialog, as for a scene's picture.
- The words of each error, in the brief's voice.

## Open, for Satwik later

- Whether the settings page shows what a key's run cost, when the service says.
- Which agents come after Codex.
