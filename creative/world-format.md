# How to write a world

A world is an editing style treated as a working system: how it cuts, frames, sets type, grades and sounds, and the one move that makes it recognisable, with where it comes from. A project's catalog is a folder of world files, `projects/<slug>/worlds/<id>.md`, one world per file. Write them in Frameflow's own words; references are links or local paths, never copied media.

## The file

Front matter first: one JSON object between two `---` lines (JSON, not YAML). Its fields:

- `id` — the file's name without `.md`: lower case, digits and hyphens.
- `name` — what the creator will see.
- `family` — one of the six below.
- `lineage` — where it comes from, in a sentence.
- `tags` — three or more words to tell it from its neighbours.
- `avoid` — optional: what it must never become.
- `source` — `proposed` (Frameflow proposed it), `reel` (written from a reel the creator pointed at), `video` (written from a video they made and liked) or `creator` (they wrote it).
- `references` — optional: links or local paths.

Then seven sections, each a `## ` heading with a few lines under it, none empty:

- **Form** — how it works, in one or two sentences. Its first sentence is the catalog's one-line summary.
- **Cut** — shot lengths, rhythm, what a cut lands on.
- **Camera** — framing and stillness. Moves (push-ins, punches, ramps) wait for a later piece of Frameflow; say what the framing does without them.
- **Type** — faces, where text sits, how it behaves.
- **Grade** — a strategy first (true colour, one committed hue, crushed contrast), then a look.
- **Sound** — the music's role, and where silence or the room's own sound belongs.
- **Signature move** — the one thing that makes it recognisable.

## The six families

A roll deals across families, so a catalog should span them:

- `print` — magazines, zines, lookbooks, catalogues, labels. *A garment's care label.*
- `screen` — film, television, title sequences. *A heist film's crew introductions.*
- `music` — music videos, performance, record culture. *A skate video's part on tape.*
- `broadcast` — sport, news, live graphics. *A football broadcast's line-up card.*
- `interface` — devices, apps, signage. *A sneaker app's drop countdown.*
- `ritual` — places and ceremonies. *A fitting room's three-way mirror; a runway walk with show notes.*

## A working system, not a costume

A world gives the video disciplines: a rhythm to keep, a place for type, a strategy for colour, a role for sound. It never gives it a filter. A VHS overlay on everything, or a copied reference, is a costume: it can be put on any video and says nothing about this one. When a world challenges another and loses, what it hands over is a discipline ("one rhythm for the whole reel"), never a surface trick.

## An example

```markdown
---
{"id": "care-label", "name": "Care label", "family": "print", "lineage": "The woven labels and size tags sewn into a garment, read up close.", "tags": ["label", "condensed type", "true colour", "close detail"], "avoid": ["centred captions over a bedroom", "a warm film grade"], "source": "proposed"}
---

## Form

The video reads like the garment's own label: short factual lines, set small where a tag would sit, over close looks at the thing itself. The clothes are the content; the text is their specification.

## Cut

Short shots of detail (collar, placket, seam, cuff), one or two beats each, then one long hold on the whole fit. Cuts land on downbeats.

## Camera

Close and still on details, then a still medium or wide frame for the fit. No handheld drift; the frame holds while the garment moves.

## Type

A small condensed sans, upper case, set in a corner or near the edge where a tag sits, never centre screen. Lines are content: "100% cotton", "henley", "3 buttons". Each line appears on a cut and holds.

## Grade

True colour: the fabric as it is, no warm film and no teal. Contrast kept gentle so texture shows.

## Sound

The song carries it, cut to its downbeats; the room's own sound stays low under it, so fabric and footsteps are felt rather than heard.

## Signature move

The label lines change with each cut, like flipping a tag to read the other side.
```
