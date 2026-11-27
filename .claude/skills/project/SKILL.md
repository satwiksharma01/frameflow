---
name: project
description: Make or change a Frameflow project - a creator's channel, page or series with its own catalog of video worlds - acting as the editor yourself. Use when the user wants a project for their channel or page, new worlds proposed for it, a world added from a reel or from a video they liked, or a world dropped.
---

# A creator's project, and its catalog of worlds

A project is a creator's channel, page or series: who they are, who watches, the rules they keep, and a catalog of **worlds**, the editing styles their videos are made in. When a video is made in a project (`produce --project <slug>`), the catalog leads its direction, so the channel stays recognisably itself. Projects live in the git-ignored `projects/<slug>/`; nothing in them is ever committed. Run everything from the repository root.

1. **Make it.** `python -m project.projects new <slug> --name "<name>"`, the slug in lower case with hyphens. Then fill in `projects/<slug>/project.json` with the user, in their words: `about` (who they are and what they make), `audience`, `platforms`, `goals`, and `commitments`, the standing rules ("never a voiceover"). Ask only what you cannot infer. A brand kit of their own goes in `projects/<slug>/brand.json`, in the same form as `brand/brand.json`.

2. **Propose its first worlds.** `python -m project.projects propose <slug>`, read `projects/<slug>/worlds_request.md` in full, and the `creative/` files it names. Write each world to `projects/<slug>/worlds/<id>.md`, then run `python -m project.projects check <slug>` and fix what it reports. Show the user each world in a line or two: its name, family, where it comes from, and its signature move. **They keep or drop each.**

3. **A world from a reel they point at.** `python -m project.projects from-reel <slug> "<video>"` studies the reel (a sheet of its frames with their times, its cuts, its music's tempo). Read the request, open the sheet, write the one world it asks for, `check`, and show it to the user.

4. **A world from a video they made and liked.** `python -m project.projects from-video <slug> output/<name>`: the video must have been made with a direction. Write the one world the request asks for, `check`, and show it.

5. **Drop a world.** `python -m project.projects drop <slug> <id>` moves it to `worlds/dropped/`, so a drop can be undone by moving it back.

**Rules:** worlds are written in Frameflow's own words, each a working system (how it cuts, frames, sets type, grades and sounds, and its one signature move), never a costume or a copy. References are links or local paths, never copied media.
