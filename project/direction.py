#!/usr/bin/env python3
"""The direction step: a committed direction for a video, between its brief and its storyboard.

The agent frames the video (its mechanism, its viewer's scene, the rut it must avoid) and, when no catalog leads the
round, digs seven candidates from the audience's culture. Frameflow's code then rolls, from a recorded seed: inside a
project with unshown worlds the catalog leads, otherwise the candidates do. The agent writes the hand from the roll;
the creator chooses, re-rolls or pins; the choice is written to direction.json, a contract the storyboard follows.

A video's round files sit in <video>/direction/ (request.md, candidates.json, roll.json, hand_request.md, hand.json,
state.json), earlier rounds in direction/round-<n>/, and the chosen direction.json beside brief.json. The engine
never calls a model: it writes requests and checks answers.
"""
import hashlib
import json
from pathlib import Path

from project import projects
from project.projects import World
from project.validate import ValidationError, load_schema, validate

LIMIT_IN_CATALOG = 2        # challengers when a catalog world leads
LIMIT_AGAINST_CANDIDATE = 3  # catalog worlds challenging a candidate that leads
DIRECTION_FILE = "direction.json"
WORK = "direction"
ROUND_FILES = ("request.md", "candidates.json", "roll.json", "hand_request.md", "hand.json")
REGISTERS = ("plain", "safer", "bolder")
CONTRACT = ("thesis", "own_world", "story", "first_two_seconds", "signature_move")


class DirectionError(Exception):
    pass


def seed_key(brief: dict, catalog_digest: str, round_no: int, register: str) -> str:
    """What the roll is drawn from: the same brief, catalog, round and register always give the same roll."""
    text = "\n".join([json.dumps(brief, sort_keys=True), catalog_digest, str(round_no), register])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def seed_reference(key: str) -> str:
    return key[:16]


def catalog_leads(worlds: list[World], shown: set[str], register: str) -> bool:
    """Inside a project with unshown worlds the catalog leads (Satwik, 2026-11-22), except on a bolder re-roll."""
    return register != "bolder" and any(w.id not in shown for w in worlds)


def rank(items: list[dict], key: str, salt: str) -> list[dict]:
    """The items in the seed's order: by the hash of the key, the salt and each id, highest first, ties by id."""
    by_id = sorted(items, key=lambda item: item["id"])
    return sorted(by_id, key=lambda item: hashlib.sha256((key + salt + item["id"]).encode("utf-8")).hexdigest(),
                  reverse=True)


def _deal(ranked: list[dict], lead_family: str, limit: int) -> list[str]:
    """Challengers in rank order, one per family before any family repeats; the lead's family counts as taken."""
    picked, families = [], {lead_family}
    for item in ranked:
        if len(picked) < limit and item["family"] not in families:
            picked.append(item)
            families.add(item["family"])
    picked += [item for item in ranked if item not in picked][:limit - len(picked)]
    return [item["id"] for item in picked]


def roll(key: str, worlds: list[World], candidates: list[dict], shown: set[str], register: str) -> dict:
    """What leads this round, and which catalog worlds challenge it."""
    unshown = [{"id": w.id, "family": w.front["family"]} for w in worlds if w.id not in shown]
    if catalog_leads(worlds, shown, register):
        ranked = rank(unshown, key, "lead")
        return {"lead": {"kind": "world", "id": ranked[0]["id"]},
                "challengers": _deal(ranked[1:], ranked[0]["family"], LIMIT_IN_CATALOG)}
    pool = [c for c in candidates if c["id"] not in shown]
    if not pool:
        raise ValueError("nothing is left to lead: every world and candidate has been shown")
    lead = rank(pool, key, "lead")[0]
    return {"lead": {"kind": "candidate", "id": lead["id"]},
            "challengers": _deal(rank(unshown, key, "deal"), lead["family"], LIMIT_AGAINST_CANDIDATE)}


# --- the step -------------------------------------------------------------------------------

def state(folder: Path) -> dict:
    path = Path(folder) / WORK / "state.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"round": 0, "register": "plain", "shown": [], "rerolls_in_a_row": 0}


def _save_state(folder: Path, st: dict) -> None:
    _write(Path(folder) / WORK / "state.json", st)


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read(path: Path, kind: str) -> dict:
    """A file the agent wrote, checked against its schema; a problem is a message naming the file."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        validate(doc, kind)
    except (json.JSONDecodeError, ValidationError) as e:
        raise DirectionError(f"{path} needs fixing:\n  {e}") from None
    return doc


def _json_block(doc) -> str:
    return f"```json\n{json.dumps(doc, indent=2, ensure_ascii=False)}\n```"


def _catalog(inputs: dict) -> tuple[str | None, list[World]]:
    slug = inputs.get("project")
    return slug, (projects.worlds(slug) if slug else [])


def _register_lines(st: dict) -> list[str]:
    lines = []
    if st["register"] == "safer":
        lines.append("- **A safer round.** Render the most conventional version of what is left, and the standard, "
                     "measured against named competitors: which channels or brands already make this kind of video, "
                     "and how this one would sit beside theirs.")
    if st["rerolls_in_a_row"] >= 2:
        lines.append(f"- **This is re-roll {st['rerolls_in_a_row']} in a row.** Before anything else, ask the creator what "
                     f"quality is missing, and let their answer steer the framing.")
    return lines


def _request(folder: Path, brief: dict, st: dict, slug: str | None, asked: bool) -> Path:
    """The round's first request: the framing, and the candidates when no catalog leads."""
    work = Path(folder) / WORK
    mode = brief.get("mode")
    project = _json_block(projects.load(slug)) if slug else "No project: this video is a one-off."
    catalog = f"\n## The project's catalog\n\n{projects.index(slug)}\n" if slug else ""
    if asked:
        foreign = (" This is a bolder round: **foreign forms only, at full commitment**. Nothing from this kind of "
                   "video's own world, nothing from the rounds before." if st["register"] == "bolder" else "")
        candidates = f"""## Candidates

No catalog leads this round, so dig seven candidates from the audience's culture.{foreign}

- Each has an `id` (lower case and hyphens), a `name`, a `family` (print, screen, music, broadcast, interface or
  ritual), `why` it resonates with this audience and can carry this video, `how` it looks, moves and sounds, and
  `literal`: true when it takes the brief's own picture literally.
- At least three families. At most one literal. None built from the creator's own tools of the trade (a camera,
  a timeline, a ring light).
- Each is a working system, not a costume: it gives the video disciplines, never a filter."""
    else:
        candidates = """## Candidates

The project's catalog leads this round: Frameflow deals the lead and its challengers from the worlds above. Write
`"candidates": []`."""
    round_name = f"{st['round']}, {st['register']}" if st["register"] != "plain" else str(st["round"])
    read_mode = (f"`creative/modes.md#{mode}`" if mode
                 else "`creative/modes.md` (the brief has no mode: choose the one that fits)")
    path = work / "request.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""# A direction for "{brief['title']}"

Before its storyboard, this video gets a direction: a short contract the storyboard follows. This is round
{round_name}. Frame the video first; then Frameflow rolls.

## The brief

{_json_block(brief)}

## The project

{project}
{catalog}
## Read first

- `creative/INDEX.md`, then {read_mode}, and `creative/calibration.md`. Read them; they are not copied here.
{chr(10).join(_register_lines(st))}
## The framing

Always, before any look is chosen:

- `mechanism`: how this video works, in a sentence.
- `viewer_scene`: the viewer's real scene: where they are, on what, with sound or without.
- `cultural_home`: where this audience already looks, what they collect, the places and rituals they know.
- `must_prove`: what the first two seconds must prove.
- `rut`: `default`, what this kind of video always looks like, and `opposite`, its predictable opposite. Both are out.

{candidates}

## Write

`{(work / "candidates.json").as_posix()}`, matching the schema below. Then run:

```
python -m project.produce "{Path(folder).as_posix()}" --direction
```

## Schema

{_json_block(load_schema("candidates"))}
""", encoding="utf-8")
    return path


def _hand_request(folder: Path, brief: dict, framing: dict, lead, challengers: list[World], rolled: dict,
                  st: dict) -> Path:
    """The request for the hand: the lead and the challengers' files to read, and the rules for the cards."""
    work = Path(folder) / WORK
    if isinstance(lead, World):
        leads = f"The catalog world `{lead.id}` ({lead.front['name']}). Read `{lead.path.as_posix()}`."
    else:
        leads = f"The candidate `{lead['id']}`:\n\n{_json_block(lead)}"
    against = "\n".join(f"- `{w.id}` ({w.front['name']}, {w.front['family']}): read `{w.path.as_posix()}`"
                        for w in challengers) or "None this round."
    path = work / "hand_request.md"
    path.write_text(f"""# The hand

Frameflow rolled (seed `{rolled['seed']}`, round {rolled['round']}, {rolled['register']}). Write the hand the creator
chooses from.

## The brief

{_json_block(brief)}

## The framing

{_json_block(framing)}

## What leads

{leads}

## What challenges it

{against}

## Rules

- **Render the lead for this video:** the world supplies the form and the grammar, the video supplies every fact,
  and the rut stays out.
- **Fuse each challenger** with the video the same way.
- **Judge each challenger** against the lead on two axes only: does the audience recognise itself, and is the
  video's point clear. Its `verdict` is `wins` (beats the lead on both), `competitive` (holds one) or `declined`
  (loses both).
- **A declined challenger gives the lead one discipline**, never a surface trick: write it as the challenger's
  `kept`, and on the lead's card as a `raises` entry, `{{"from": "<the challenger's source>", "discipline": "..."}}`.
- **Add one pick card** (`kind: pick`) for your own first choice, when the roll did not deal it: the catalog world you
  would have chosen for this video, or your top candidate.
- **Add the standard card** (`kind: standard`, `id` and `source` both `standard`): the category's default played
  straight. Never recommend it.
- **Every card is a full contract:** `thesis` (the one idea, and the default it refuses); `own_world` (grade, type
  voice, caption system, cut rhythm, sound, recognisable with the content removed); `story`; `first_two_seconds`
  (exactly what is in frame, on screen and in the sound); `signature_move`; `honest_risk`.
- **Only what the storyboard can say today:** which shots, in what order and how long; cuts on the beat or not; the
  grade (a LUT); type as titles, cards and an overlay; captions on or off; the music's level. No zooms, ramps,
  transitions or sound effects yet.
- **Ids:** the lead's card is `lead` and the standard's `standard`; any other card's id is its `source`.
- **Before writing, apply the calibration test** in `creative/calibration.md` to the lead.
{chr(10).join(_register_lines(st))}
## Write

`{(work / "hand.json").as_posix()}`, matching the schema below. Then run:

```
python -m project.produce "{Path(folder).as_posix()}" --direction
```

## Schema

{_json_block(load_schema("hand"))}
""", encoding="utf-8")
    return path


def advance(folder: Path, brief: dict, inputs: dict) -> tuple[str, Path | None]:
    """Do the next thing in the round: (what to print, the file written or to read)."""
    folder = Path(folder)
    st, work = state(folder), folder / WORK
    if (folder / DIRECTION_FILE).is_file():
        return f"Direction: {_read(folder / DIRECTION_FILE, 'direction')['name']}", None
    if st.get("pin"):
        return "The creator pinned a direction: write direction.json as the request asks.", work / "request.md"
    if not (work / "candidates.json").is_file():
        slug, catalog = _catalog(inputs)
        asked = not catalog_leads(catalog, set(st["shown"]), st["register"])
        return (f"Round {st['round']}: frame the video{', with seven candidates' if asked else ''}.",
                _request(folder, brief, st, slug, asked))
    if not (work / "roll.json").is_file():
        slug, catalog = _catalog(inputs)
        doc = _read(work / "candidates.json", "candidates")
        problems = check_candidates(doc, not catalog_leads(catalog, set(st["shown"]), st["register"]))
        if problems:
            raise DirectionError(f"{work / 'candidates.json'} needs fixing:\n" + "\n".join(f"  {p}" for p in problems))
        key = seed_key(brief, projects.digest(slug), st["round"], st["register"])
        try:
            dealt = roll(key, catalog, doc["candidates"], set(st["shown"]), st["register"])
        except ValueError:
            raise DirectionError("nothing is left to lead: re-roll bolder for fresh candidates, or pin a direction "
                                 "in the creator's words") from None
        rolled = {"seed": seed_reference(key), "round": st["round"], "register": st["register"], **dealt,
                  "shown_before": st["shown"], "worlds": {w.id: w.path.as_posix() for w in catalog}}
        _write(work / "roll.json", rolled)
        by_id = {w.id: w for w in catalog}
        lead = (by_id[dealt["lead"]["id"]] if dealt["lead"]["kind"] == "world"
                else next(c for c in doc["candidates"] if c["id"] == dealt["lead"]["id"]))
        challenged = f", challenged by {', '.join(dealt['challengers'])}" if dealt["challengers"] else ""
        return (f"Rolled (seed {rolled['seed']}): {dealt['lead']['id']} leads{challenged}.",
                _hand_request(folder, brief, doc["framing"], lead, [by_id[c] for c in dealt["challengers"]], rolled, st))
    if not (work / "hand.json").is_file():
        return (f"Write {(work / 'hand.json').as_posix()} as {(work / 'hand_request.md').as_posix()} asks, then run "
                f"--direction again.", None)
    hand = _read(work / "hand.json", "hand")
    problems = check_hand(hand, json.loads((work / "roll.json").read_text(encoding="utf-8")))
    if problems:
        raise DirectionError(f"{work / 'hand.json'} needs fixing:\n" + "\n".join(f"  {p}" for p in problems))
    return hand_text(hand), None


def check_candidates(doc: dict, asked: bool) -> list[str]:
    """What is wrong with the framing and candidates beyond their schema."""
    framing = doc["framing"]
    problems = [f"framing: {k} is empty" for k in ("mechanism", "viewer_scene", "cultural_home", "must_prove")
                if not str(framing.get(k, "")).strip()]
    found = doc["candidates"]
    if not asked:
        return problems + (['the catalog leads this round: write "candidates": []'] if found else [])
    if len(found) != 7:
        problems.append(f"there are {len(found)} candidates; write exactly seven")
    ids = [c["id"] for c in found]
    twice = sorted({i for i in ids if ids.count(i) > 1})
    if twice:
        problems.append(f"candidate ids must be distinct: {', '.join(twice)} appear more than once")
    families = {c["family"] for c in found}
    if len(families) < 3:
        problems.append(f"the candidates span {len(families)} families; use at least three")
    literal = sum(1 for c in found if c["literal"])
    if literal > 1:
        problems.append(f"{literal} candidates take the brief literally; at most one may")
    return problems


def check_hand(hand: dict, roll: dict) -> list[str]:
    """What is wrong with the hand, against the roll it was written from."""
    cards, problems = hand["cards"], []
    kinds = {k: [c for c in cards if c["kind"] == k] for k in ("lead", "challenger", "pick", "standard")}
    leads = kinds["lead"]
    if len(leads) != 1:
        problems.append(f"the hand has {len(leads)} lead cards; it needs exactly one")
    elif leads[0]["source"] != roll["lead"]["id"]:
        problems.append(f"the lead card is {leads[0]['source']}, but the roll dealt {roll['lead']['id']}")
    if len(kinds["pick"]) > 1:
        problems.append(f"the hand has {len(kinds['pick'])} pick cards; at most one")
    if leads and any(p["source"] == leads[0]["source"] for p in kinds["pick"]):
        problems.append("the pick is the lead; a pick is only for a first choice the roll did not deal")
    if len(kinds["standard"]) != 1:
        problems.append(f"the hand has {len(kinds['standard'])} standard cards; it needs exactly one")
    for c in kinds["challenger"]:
        if c["source"] not in roll["challengers"]:
            problems.append(f"challenger {c['source']} was not dealt; the roll dealt "
                            f"{', '.join(roll['challengers']) or 'none'}")
        if "verdict" not in c:
            problems.append(f"challenger {c['source']} has no verdict")
    full = [c for c in kinds["challenger"] if c.get("verdict") in ("wins", "competitive")]
    if len(full) > 3:
        problems.append(f"{len(full)} challengers are shown in full; at most three")
    raised = {r["from"] for lead in leads for r in lead.get("raises", [])}
    for c in kinds["challenger"]:
        if c.get("verdict") == "declined":
            if not c.get("kept"):
                problems.append(f"declined challenger {c['source']} says nothing it gave the lead (kept)")
            if c["source"] not in raised:
                problems.append(f"declined challenger {c['source']} is not among the lead card's raises")
    ids = [c["id"] for c in cards]
    twice = sorted({i for i in ids if ids.count(i) > 1})
    if twice:
        problems.append(f"card ids must be distinct: {', '.join(twice)} appear more than once")
    return problems


def _card_lines(c: dict, label: str, names: dict[str, str]) -> list[str]:
    lines = [f"{label}: {c['name']}  ·  thesis: {c['thesis']}",
             f"  own world: {c['own_world']}",
             f"  story: {c['story']}",
             f"  first two seconds: {c['first_two_seconds']}",
             f"  signature move: {c['signature_move']}",
             f"  risk: {c['honest_risk']}"]
    lines += [f"  raised by {names.get(r['from'], r['from'])}: {r['discipline']}" for r in c.get("raises", [])]
    return lines + [f"  (--choose {c['id']})"]


def hand_text(hand: dict) -> str:
    """The hand as the creator reads it: the lead, full challengers, the pick, the declined, the standard last."""
    cards = hand["cards"]
    names = {c["source"]: c["name"] for c in cards}
    lines = []
    for c in cards:
        if c["kind"] == "lead":
            lines += _card_lines(c, "Lead (rolled)", names)
    for c in cards:
        if c["kind"] == "challenger" and c.get("verdict") != "declined":
            lines += _card_lines(c, f"Challenger, {c.get('verdict', 'unjudged')}", names)
    for c in cards:
        if c["kind"] == "pick":
            lines += _card_lines(c, "Frameflow's pick", names)
    lines += [f"Declined: {c['name']} (kept: {c.get('kept', '')})" for c in cards
              if c["kind"] == "challenger" and c.get("verdict") == "declined"]
    lines += [f"The standard: {c['name']}  ·  {c['thesis']}  (--choose {c['id']})" for c in cards
              if c["kind"] == "standard"]
    lines.append('Choose one (--choose <card id>), re-roll (--reroll plain|safer|bolder), or pin your own '
                 '(--pin "<words>").')
    return "\n".join(lines)


def choose(folder: Path, card_id: str) -> Path:
    """Write the chosen card as the video's direction."""
    folder = Path(folder)
    work = folder / WORK
    if not (work / "hand.json").is_file():
        raise DirectionError("there is no hand to choose from yet: run --direction until it prints one")
    hand = _read(work / "hand.json", "hand")
    rolled = json.loads((work / "roll.json").read_text(encoding="utf-8"))
    problems = check_hand(hand, rolled)
    if problems:
        raise DirectionError(f"{work / 'hand.json'} needs fixing:\n" + "\n".join(f"  {p}" for p in problems))
    card = next((c for c in hand["cards"] if c["id"] == card_id), None)
    if card is None:
        raise DirectionError(f"there is no card {card_id} in the hand: {', '.join(c['id'] for c in hand['cards'])}")
    worlds = rolled.get("worlds", {})
    kind = "standard" if card["kind"] == "standard" else "world" if card["source"] in worlds else "candidate"
    doc = {"name": card["name"], **{f: card[f] for f in CONTRACT},
           "source": {"kind": kind, **({} if kind == "standard" else {"id": card["source"]})},
           "seed": rolled["seed"], "pinned": False,
           **({"world_path": worlds[card["source"]]} if kind == "world" else {})}
    validate(doc, "direction")
    _write(folder / DIRECTION_FILE, doc)
    st = state(folder)
    st["rerolls_in_a_row"] = 0
    _save_state(folder, st)
    return folder / DIRECTION_FILE


def _close_round(folder: Path, st: dict) -> None:
    """Move the round's files, and any direction chosen in it, into direction/round-<n>/."""
    work = folder / WORK
    done = work / f"round-{st['round']}"
    for path in [work / name for name in ROUND_FILES] + [folder / DIRECTION_FILE]:
        if path.is_file():
            done.mkdir(parents=True, exist_ok=True)
            path.replace(done / path.name)


def _from_folder(folder: Path, name: str) -> dict:
    path = folder / name
    if not path.is_file():
        raise DirectionError(f"{path} is missing")
    return json.loads(path.read_text(encoding="utf-8"))


def reroll(folder: Path, register: str, brief: dict | None = None, inputs: dict | None = None) -> Path:
    """Start the next round: every card already shown is out. The brief and inputs default to the folder's own."""
    if register not in REGISTERS:
        raise DirectionError(f"re-roll plain, safer or bolder, not {register}")
    folder = Path(folder)
    work = folder / WORK
    brief = brief if brief is not None else _from_folder(folder, "brief.json")
    inputs = inputs if inputs is not None else _from_folder(folder, "inputs.json")
    st = state(folder)
    shown = list(st["shown"])
    if (work / "roll.json").is_file():
        rolled = json.loads((work / "roll.json").read_text(encoding="utf-8"))
        shown += [rolled["lead"]["id"], *rolled["challengers"]]
    if (work / "hand.json").is_file():
        shown += [c["source"] for c in json.loads((work / "hand.json").read_text(encoding="utf-8"))["cards"]
                  if c["kind"] == "pick"]
    carried = None
    if register != "bolder" and (work / "candidates.json").is_file():
        old = json.loads((work / "candidates.json").read_text(encoding="utf-8"))
        if any(c["id"] not in shown for c in old["candidates"]):
            carried = old       # the candidates left are rolled again; none new are asked for
    _close_round(folder, st)
    st.update(round=st["round"] + 1, register=register, shown=list(dict.fromkeys(shown)),
              rerolls_in_a_row=st["rerolls_in_a_row"] + 1)
    st.pop("pin", None)
    _save_state(folder, st)
    _, catalog = _catalog(inputs)
    if carried is not None and not catalog_leads(catalog, set(st["shown"]), register):
        _write(work / "candidates.json", carried)
    return advance(folder, brief, inputs)[1]


def pin(folder: Path, words: str, brief: dict) -> Path:
    """Skip the roll: the creator gives the direction in their own words."""
    folder = Path(folder)
    st = state(folder)
    _close_round(folder, st)
    st.update(round=st["round"] + 1, pin=words, rerolls_in_a_row=0)
    _save_state(folder, st)
    path = folder / WORK / "request.md"
    path.write_text(f"""# A direction in the creator's own words

The creator pinned the direction:

> {words}

Write it as the contract this video's storyboard will follow. Keep their words and their intent; fill in only what
they leave open, from the brief. Read `creative/calibration.md` first, so nothing they did not ask for comes from habit.

## The brief

{_json_block(brief)}

## Write

`{(folder / DIRECTION_FILE).as_posix()}`, matching the schema below: `name`, `thesis` (the one idea, and the default
it refuses), `own_world`, `story`, `first_two_seconds`, `signature_move`, and

```json
{{"source": {{"kind": "pin"}}, "seed": null, "pinned": true}}
```

Then run `python -m project.produce "{folder.as_posix()}" --direction`.

## Schema

{_json_block(load_schema("direction"))}
""", encoding="utf-8")
    return path


def storyboard_section(folder: Path) -> str:
    """The storyboard request's Direction section: the contract, its world and the rules; empty with no direction."""
    path = Path(folder) / DIRECTION_FILE
    if not path.is_file():
        return ""
    doc = _read(path, "direction")
    labels = {"thesis": "Thesis", "own_world": "Own world", "story": "Story", "first_two_seconds": "First two seconds",
              "signature_move": "Signature move"}
    lines = ["## Direction", "",
             f"The creator chose a direction{', in their own words' if doc['pinned'] else ''}: **{doc['name']}**. "
             f"It is a contract.", ""]
    lines += [f"- **{labels[f]}:** {doc[f]}" for f in CONTRACT]
    if doc.get("world_path"):
        lines += ["", f"It comes from the project's world `{doc['world_path']}`: read it for the grammar."]
    lines += ["", "1. The storyboard follows the contract.",
              "2. Its first two seconds are as written.",
              "3. Anything the storyboard cannot say yet is left out, not imitated, and listed after the script for "
              "the creator.",
              "4. The brand kit's font and colours bind titles, cards and captions, and the direction works within "
              "them: placement, size, case, behaviour. Only when the kit names no font does the direction's own face "
              "come in, through an overlay composition with its font file copied beside it."]
    return "\n".join(lines) + "\n"
