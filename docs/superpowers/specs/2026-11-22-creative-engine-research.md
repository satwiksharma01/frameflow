# Creative engine research: how Impeccable makes UI with taste, and the same engine for video

**Date:** 2026-11-22 · **Status:** research for the creative-engine design, not a spec · **Read:** Impeccable's skill as installed in this repo (`.claude/skills/impeccable/`: `SKILL.md`, `new-work.md`, `craft-floor.md`, `typeset.md`, `colorize.md`, `mode-persuade.md`, `shape.md`, `bolder.md`, `quieter.md`, `critique.md`, `visualize.md`) and its engine on GitHub (`pbakaus/impeccable`: `skill/reference/new-work-world.md`, `crates/context/src/catalog.rs`, `roll_selection.rs`, `concept_seed.rs`, `crates/live/assets/antipatterns.json`).

The question: how does Impeccable get an AI to make work with a point of view, not features but the philosophy and the machinery, and what would the same thing be for Frameflow's videos?

---

## 1. The problem it is built against

Left alone, a model converges. Asked for "a landing page for X", every run lands on one of a handful of looks, whatever X is. Impeccable names them outright: a warm cream ground with a high-contrast serif and a terracotta accent; near-black with one neon accent and glowing edges; editorial hairlines with an italic serif and small tracked mono labels; flat saturated ink with black boxes and hard offset shadows. Its whole design is a set of counterweights to that pull, placed at every step where the model would otherwise take the most probable answer.

Frameflow has the same problem in video, and this session produced a clean example of it: the outfit reel built on 2026-11-22 (run 11 in the vault) has centred white sans-serif text with a soft shadow, a warm film grade at 70%, and hard cuts on the beat. Every choice was defensible and the result is the category default. Nothing in it could not have been guessed from "outfit reel" alone.

---

## 2. How Impeccable handles creativity: fourteen principles

### 2.1 Truth lives in layers, and the look is written down last

- `PRODUCT.md` holds product truth: who it is for, what it does, brand commitments.
- `DESIGN.md` holds the durable visual system: palette, type, components, as tokens.
- A **surface brief** holds strategy for one page or artifact, including the **direction contract** (below).
- A context script loads all three once per session, so every command starts from the same truth.

The telling detail: on a new visual world, `DESIGN.md` is written **at the finish, from what was built**, by a separate documenter. A rulebook written before the build gets defended against reality; one written after describes it.

### 2.2 The mode sets the ambition

Before anything visual, the surface gets a mode that says what success is for the visitor:

| Mode | The visitor | Ambition shows as |
|---|---|---|
| Persuade | decides and acts | full commitment, a world that owns the page |
| Operate | completes a task | precision and restraint; brand lives in details |
| Read | understands something | structure for comprehension |
| Experience | is inside the work | the work leads from the first viewport |

The mode is chosen from the surface, not the product: a tool's landing page is Persuade, a fashion house's docs are Read. Every later rule (how much colour, which faces, how far a world may reach) is scaled by it.

### 2.3 Inherit before inventing

`new-work.md` first decides what is already true: a redesign keeps product truth and replaces the look; an established world is inherited; an incomplete brand is expanded with the user; only with no visual authority is a world invented. A section or feature inside an established surface inherits it and is "never turned into a new identity exercise". The amount of invention is a decision, not a default.

### 2.4 Ask only what changes the work

Two or three questions per round, chosen by mode (Persuade: who must act, what they should believe, what real proof earns it; Experience: what leads, what interaction matters). Two bans: never ask for values (CSS numbers), and never offer canned aesthetic lanes ("minimal / bold / playful?"). Menus of styles hand the choice to a taste function and invite the safest one.

### 2.5 Name the rut, then dig in the audience's culture

For a new world the model must first write down:
- the product's unique mechanism in one sentence, the audience's real scene, its cultural home, and what this first surface must prove;
- **the rut**: the page this category always ships *and its predictable opposite*. Both are excluded. A brief that paints its own picture (a product name, a metaphor) adds its literal reading to the rut: at most one candidate may use it.

Then it derives **seven candidates from the audience's cultural world**: visual systems, artifacts, places or rituals the audience knows by heart, including the publications, notation, identity programs and interfaces they read daily. Each gets one line on why it resonates and can carry the mechanism, and one on how it looks (ground, main colours, type voices, the one signature that makes it recognisable). Two prompts widen the search: what would this be as a physical object, and what did its world look like before the web. Two rules stop the search stopping early: near-duplicates count once, and if more than three of seven share a material family, keep digging until three families are covered. On working screens, candidates never come from the tools the audience operates: a terminal handed to a dashboard comes back "as a costume of that tool".

### 2.6 Let a seeded roll choose, from a curated catalog of working worlds

This is the engine's heart, and it is code, not prose (`concept_seed.rs`, `roll_selection.rs`, `catalog.rs`):

- A script hashes a seed and **assigns** which of the model's own directions leads. The dice break the model's ranking habit (it would always put its most probable idea first) while the user still gets a real choice. The seed is recorded, so a round is reproducible.
- It also **deals challengers from a curated catalog of "worlds"**. A world is a working system, not a mood board. An entry carries its `form` (a 40 to 360 character description of how it works), its `lineage` (where it comes from), `tags`, what to `avoid`, its `system` grammar, its `family`, a `wellTier` (graphic, interaction or atmosphere), an approval flag, and two images, a board and a hero, shown as the **QUALITY BAR**: the finish level the build must reach.
- Dealing is diversity-aware (one per family before repeats) and mode-aware: Operate draws five of six challengers from the graphic tier, because instrument and atmosphere worlds dealt to working screens "became costumes of the tool".
- Each challenger is **fused** with the product (the world supplies form and grammar, the product supplies every fact) and judged on exactly two axes, audience identification and product clarity. Verdict: wins, competitive, or declined.
- A declined challenger is not wasted: the model names the one **discipline** of its system the lead lacks (a palette's total commitment, a grid's density courage) and raises the lead to match, written as a named line. Disciplines transfer; **clothes** (a button's shadow, a display face, a motif) never do. One world owns the page.
- The user sees one fully committed direction, its alternates, **one** card for the model's own top pick (never a ranked list), and the **standing exit**: the category standard played straight, always available, never recommended. Re-roll comes in three registers: plain, safer, bolder. A user-pinned direction beats the roll; the model may re-roll on its own only on factual grounds, never taste.

### 2.7 Know your own priors

Impeccable tells the model what it tends to do and treats that as already spent:
- the four convergent looks above, and a named list of training-data default faces (Fraunces, Playfair, Space Grotesk, Inter as display and more). Using one needs a reason no other face satisfies, and "a subject association is never that reason";
- a test: if someone could guess the aesthetic from the category alone, *or from the category plus what it avoids*, rework it;
- a measured prior: warm, bookish or child-facing subjects come out cream, serif and lamplit even when not asked; "treat that first palette as already spent".

### 2.8 Strategy before values; type and colour as roles

- **Colour:** pick a strategy first (Restrained, Committed, Full palette, Drenched), then the dosage, then hues. Light or dark is never a default: write one sentence of physical scene (who, where, what light) and let it decide. Build roles (canvas, text, action, state, data), not a bag of swatches.
- **Type:** "choose faces like objects from the subject's world, in the mode's register". Name the roles first (display, body, label, data), make adjacent roles unmistakable, use the fewest families that make the hierarchy obvious. Two separate assessments: a typographic judgment first, then a mechanical scan, so the detector does not anchor taste.
- **Fonts by measurement:** when building from an approved image, the face is not guessed: `font-match` measures cap height, width and weight from the pixels and ranks candidates from a fingerprint index of the Google Fonts catalogue.

### 2.9 Commit fully, in depth not spread

"Build the assigned direction, not a safer interpretation of it." Every atom is rebuilt in the world's vocabulary; a stock component inside a committed world is a lapse. Commitment is **one dominant move** plus the material that supports it, not effects everywhere: "busy is louder, not bolder". The first viewport is a thesis, not a header, with a memory test: if someone left after one viewport, what would they describe an hour later? If the honest answer is a mood, the concept has not committed. Prove, don't claim. Author the assets; never fill a gap with chrome (gradients, glass, icon tiles). Motion is one orchestrated moment, not scattered effects.

### 2.10 Write the decision down as a contract

Before code, about 150 words in six blocks: THESIS (the one idea, and the category arrangement it refuses), OWN-WORLD (palette and component language, recognisable with all content removed), STORY (what the visitor understands, believes, does), FIRST VIEWPORT (the exact composition), FORM (the chosen form and the seed reference), FINISH (the exit condition). "If a block reads like a mood, the direction is not decided yet." Every later reviewer audits against it.

### 2.11 Visualise, then measure; never trust memory

On a visual build, three high-fidelity comps go to one approval point ("one comp invites rubber-stamping"). The approved comp then becomes a measured contract: regions with boxes and sampled palettes, type measured from pixels, and gates that diff the build's screenshots against the comp region by region. The reason is stated plainly: models believe their recreation succeeded when it did not.

### 2.12 A floor and a detector

The craft floor lists checks on the built result (contrast, spacing, type measure, one motion moment, every state) and a refuse list of category defaults. A deterministic detector of 62 rules runs as a hook after every UI edit, split into **slop** (AI tells: gradient text, the icon tile over a heading, cream backgrounds, the kicker label above a heading, buzzwords) and **quality** (low contrast, cramped padding, a straggling last word), plus **conformance** to `DESIGN.md` (a font, colour, radius or size not in the system). A clean scan is a floor, not proof of taste.

### 2.13 Judgment in a fresh context, in bounded rounds

Critique runs two isolated assessments: an unanchored design review first, then the detector's evidence. The finish review is a **fresh** agent that never sees the build conversation ("a reviewer that inherits your transcript inherits your framing, your optimism"). It returns one of four dispositions (ship, fix, rebuild, recapture). Two rounds is the budget; beyond that the user decides.

### 2.14 Refinement that keeps scope and voice

The refine commands are judgment, not effects: **bolder** amplifies what the system already owns ("the bolder version should look more like the same brand, not less"), commits one move then quiets around it, and passes a skeleton test (strip the words: does the structure still say why it matters?). **Quieter** keeps the point of view ("generic quiet looks like gray text on white"). Scope is sovereign: touch only the named target.

---

## 3. The same engine for video

The principles carry over almost one for one. What changes is the material: a video's "world" is how it cuts, frames, types, grades and sounds over time.

| Impeccable | For Frameflow's videos | Frameflow today |
|---|---|---|
| PRODUCT.md | **Creator file:** who you are, your audience, what you make, standing commitments ("never a voiceover", "always my own audio") | partly: the brief per video; the brand kit |
| DESIGN.md, written at the finish | **Channel style:** title and caption type, grade, motion grammar, sound signature, as tokens; written and updated **from approved videos**, not before | the brand kit (font, colours, logo) |
| Surface brief + direction contract | **Video brief + direction contract** | the brief; no contract |
| Modes | **Video modes** (3.1) | one set of rules for everything |
| Inherit before inventing | An episode inherits its series and channel; only a new channel or series invents a world | nothing to inherit yet |
| Ask only what changes the work | Per-mode questions; never ask for values ("which LUT?") or style menus | the brief's open questions |
| Name the rut; dig in the audience's culture | Name the reel this category always ships and its opposite; derive seven directions from the audience's visual culture (3.3) | none |
| Seeded roll + catalog of worlds | **A catalog of video worlds** dealt by a seeded roll (3.2) | "make it like this" gives 2 or 3 concepts from one reference |
| Know your priors | A calibration list of AI-video tells and default faces (3.4) | none |
| Strategy before values | Grade strategy before a LUT; type roles before a face; a viewing-scene sentence before light or dark | a LUT is picked directly |
| Commit in depth | One **signature move** per video; the first two seconds are a thesis | none |
| Direction contract | THESIS, OWN-WORLD, STORY, FIRST TWO SECONDS, SIGNATURE MOVE, FORM + seed (3.5) | none |
| Visualise, then measure | **Key-frame comps** before the build; build frames measured against them (3.6) | the first-frame mock-up made by hand on 2026-11-22 |
| Floor and detector | Checks on the built video, split into quality and slop (3.7) | picture checks (black frames, captions off screen, graphics over faces), the check by ear, loudness |
| Fresh-context critic | A critic that watches the contact sheet and reads the listening report against the contract, with no build history | none |
| Refinement vocabulary | punchier, calmer, tighten, retime, regrade, retype, resound, critique, polish (3.8) | changes in words, without a craft vocabulary |

### 3.1 Video modes: what success is for the viewer

| Mode | The viewer | Success | Ambition |
|---|---|---|---|
| **Stop** | is scrolling | stops, stays to the end, replays | the first two seconds carry everything; bold |
| **Show** | wants to look | feels the thing: the outfit, the place, the product | the work leads; a world may own the frame |
| **Persuade** | must decide | believes one claim and acts | the claim and the proof are unmistakable; world in service of clarity |
| **Teach** | has a question | understands, and could repeat it | structure and legibility first; brand in details |
| **Tell** | follows a story | is carried to the end | rhythm and sound lead; restraint in graphics |

The nine kinds of video in the playbook list map onto these: an outfit reel is Show, a talking short is Stop, a pitch is Persuade, an explainer and a software demo are Teach, a vlog is Tell. The mode, not the kind, scales how far the world may reach.

### 3.2 A video world, as a catalog entry

The equivalent of Impeccable's world is an **editing style treated as a working system**, from the audience's culture. An entry holds:

- **form:** how it works, in one or two sentences;
- **cut grammar:** shot lengths, rhythm, what a cut lands on, transitions it allows;
- **camera grammar in the edit:** framing, push-ins, punches, ramps, stillness;
- **type voice:** faces and how they sit and move (a stamp, a subtitle, a label, a credit);
- **grade:** a strategy (true colour, one committed hue, crushed contrast, bleached) and its LUT;
- **sound signature:** the music's role, sound effects, silence;
- **signature move:** the one thing that makes it recognisable;
- **lineage, tags, avoid, family, tier;**
- **quality bar:** reference stills and timestamps of a reference clip, as links, never copies.

Families, so a roll spans them: print and editorial (magazine, zine, lookbook, catalogue), film and television (a title sequence, a broadcast format, a documentary school), music video and performance, sport and broadcast graphics, interfaces and devices, physical rituals and places (a fitting room, a drop queue, a market).

Mode quotas carry over: Teach should rarely be dealt atmosphere worlds, for the same reason Operate is not dealt instrument worlds.

### 3.3 The rut for video, and digging past it

For each kind of video, write down the reel it always becomes and its predictable opposite, and exclude both. For the outfit reel:
- **the rut:** centred white sans-serif text, trending audio, every shot one beat long, a warm film grade, a whip on every transition;
- **its opposite:** black-and-white slow motion with a moody piano.

Then seven directions from the audience's culture, across three or more families. For a menswear audience, for example: a garment care label and size tag; a sneaker-drop countdown; a skate-video part on tape; a fashion magazine's contact sheet; a laundromat's wash cycle; a runway walk with show notes; a museum object label. Each says how it looks, moves and sounds.

### 3.4 Calibration: the AI-video tells

The equivalent of Impeccable's convergent looks and banned faces, to treat as already spent:
- centred white captions with a yellow active word on every short, whether anyone speaks or not;
- a slow push-in on every still, and a zoom punch on every sentence;
- a teal-and-orange or warm-film grade by default;
- a whoosh and a whip on every cut;
- stock B-roll under uplifting corporate music;
- neon gradient title cards with a glow;
- letterbox bars plus slow motion as "cinematic";
- a synthetic voice over a music bed;
- the default caption faces of the short-form apps.

The test carries over unchanged: if the edit could be guessed from the category alone, or from the category plus what it avoids, rework it.

### 3.5 The direction contract for a video

About 150 words, in the brief, audited at the end:
- **THESIS:** the one idea, and the category default it refuses;
- **OWN-WORLD:** grade, type voice, caption system, motion grammar, sound signature; recognisable with the content removed;
- **STORY:** what the viewer feels, understands and does;
- **FIRST TWO SECONDS:** exactly what is in frame, on screen and in the sound;
- **SIGNATURE MOVE:** the one orchestrated moment;
- **FORM:** the chosen world and the seed.

### 3.6 Key frames before the build, measured after

Three options of the key frames (the first frame, the signature moment, the last frame) at the video's own aspect, one approval point, then the build's rendered frames are compared with the approved ones: title position and size, the grade sampled from the frame, text inside the safe zones. Frameflow already renders frames for its picture check; this turns "nothing wrong" into "matches what was approved".

### 3.7 A floor and a detector for video

Split as Impeccable splits it:
- **quality:** a hook present in the first two seconds (motion or text on frame one); text inside the platform's safe zones; text contrast against the frame behind it; text on screen long enough to read; a cut rate within the mode's range; loudness and true peak; music ducked under speech; no black frames, covered faces or audio pops (built already); nothing drawn from a file that should not show (the MP3 cover art of run 11 in the vault);
- **slop:** the same move on every cut; word-by-word captions on a reel with no speech; a default caption face; a push-in on every still;
- **conformance:** a face, colour, grade or sound outside the channel style.

### 3.8 Refinement vocabulary

The same verbs, as judgment on a finished storyboard: **punchier** raises the signature move the video already owns and quiets the rest; **calmer** keeps the point of view; **tighten** removes; **retime** changes rhythm; **regrade**, **retype** and **resound** work on one layer; **critique** and **polish** as in Impeccable. Scope is sovereign: "make scene 3 punchier" touches scene 3.

### 3.9 Where the playbooks fit

The playbooks are not the creative engine. They are the **craft floor and the technique library**: how a hook works, cut rates by mode, safe zones, how to duck music. They are read on demand. The **worlds** carry taste and direction, the **roll** keeps runs from converging, and the **contract** records the decision. A video made from playbooks alone is competent and generic; that is exactly the gap Impeccable's engine exists to close.

---

## 4. Worked example: the outfit reel, again

What was built: the rut, almost item for item.

What the engine would have done: named that rut, derived seven directions, rolled. Suppose the roll assigns **the care label**:
- **thesis:** the reel reads like the garment's own label; refuses centred captions over a bedroom;
- **own-world:** true-colour grade (fabric honesty, no warm film); type set like a woven label, small and condensed, placed where a tag sits, not centre screen; label lines as content ("100% cotton · henley · 3 buttons");
- **first two seconds:** a tight shot of the collar and placket with the label line stamping in on the first downbeat;
- **signature move:** a speed ramp into the turn, landing on the drop;
- **sound:** the song, plus fabric and footstep foley on the cuts.

It would be a different video from the same four clips. Two things would still be missing: the motion edits (the engine cannot ramp or punch yet), and a close-up of the fabric, which the clips do not have. A shooting playbook would have asked for one.

---

## 5. What Frameflow would need, as engine pieces

In dependency order, each its own design and plan:

1. **Truth layers:** a creator file and a channel style, the style written from approved videos.
2. **Modes and calibration:** the five video modes; the rut and the AI-video tells, as knowledge the planner reads.
3. **The direction round:** derivation from the audience's culture, a seeded roll over a curated catalog of video worlds, the pick card, the standing exit, re-roll registers, and pins (a "make it like this" reference is a pin).
4. **The direction contract** in the brief, audited at the end.
5. **The edit vocabulary in the engine:** motion, transitions, type behaviour, sound design. Without it a world can be chosen but not built.
6. **Key-frame comps and measurement; the video detector; a fresh-context critic.**
7. **The refinement verbs.**
8. **The craft playbooks**, read on demand through the harness.

## 6. Open questions for Satwik

- **Who curates the catalog of video worlds?** Impeccable's catalog is curated and approved, with reference images. Frameflow's would need reference stills or clips per world (as links), and someone with taste to approve them.
- **How much choice per video?** Impeccable puts a full decision page in front of the user for a new world. For a 9-second reel that may be too heavy; a channel's world might be chosen once and inherited, with a roll only for a new series.
- **Comps before the build:** key-frame comps need image generation (Frameflow's generator is behind a $0 cap) or HyperFrames renders of the type over real frames, as the first-frame mock-up was made.
