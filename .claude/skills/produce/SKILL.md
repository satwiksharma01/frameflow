---
name: produce
description: Make a video from a prompt with Frameflow - a reel, a YouTube video, a pitch, a product ad, with or without the user on camera, or one made like a reference video they give - as an editable OpenShot project, acting as the editor yourself so no API key is needed. Use when the user describes a video they want made, or wants one like another video, optionally with a script, recordings, images, clips or music, rather than asking to cut one raw recording (first-cut) or change an existing project (edit).
---

# A video from a prompt, with you as the editor

Frameflow does the mechanical work: transcribing recordings, reading the voiceover, rendering titles and captions with HyperFrames, turning images into clips, building the project. You decide what the video is. The user approves twice: the brief, then the storyboard.

1. **Prepare.** Pick a folder under `output/` named for the video. From the repository root, pass the user's prompt in their own words and everything they gave you:

   ```
   python -m project.produce output/<name> --prepare "<prompt>" [--script FILE] [--footage VIDEO ...] [--asset FILE ...] [--music FILE ...] [--look LUT ...]
   ```

   `--look` takes the user's own colour LUTs (`.cube` files) to choose the video's look from; OpenShot's own are offered either way.

   If it stops on a recording with "no usable speech", tell the user the measured numbers and stop.

2. **Brief.** Read `brief_request.md` in full and write `brief.json`. For a pitch, or any video that states facts about the world, research them with your web tools as the request says: each with who says it, its page, and the exact words on that page. Run `python -m project.produce output/<name> --brief` and fix what it reports. Show the user the brief in plain words - what the video is, for whom, how long, which shape - with any open questions, and each fact with its source and link, marking any Frameflow could not open for them to check. **Wait for them to confirm.** Put their answers into `brief.json` and remove `open_questions`.

3. **Storyboard.** Run `python -m project.produce output/<name> --storyboard`, read `storyboard_request.md` in full and write `storyboard.json`. Footage spans start and end inside the measured pauses listed for each recording. End a span in a pause of at least a quarter of a second where there is one: the build leaves the last word heard that much room, and a shorter pause right after a word can be the silence inside its last sound, before a final "k" or "t". Show the user the script, each scene in one line (what is seen, what is said, any caption, card or B-roll), whether what is said is shown as word-by-word captions (`spoken_captions`), whether the cuts land on the music's beat (`cut_to_beat`), and the look, if any (`look`: which LUT, and how strongly), and what any `generated` picture or clip would cost. **Wait for them to confirm**, and change it as they ask.

   **Made like a reference video** the user gives you (a reel, a short, an ad they want theirs to be like), the storyboard comes from Agent Video instead. Run `python -m project.produce output/<name> --reference "<video>"`, read the `analysis-request.md` it names in full, look at the reference's frames and contact sheet and listen to it as the request says, and write `analysis.json` and `concepts.json` beside it: what you observed, each with the stretch of the reference that shows it, or "unknown"; and two or three concepts that keep its structure with the user's own material. Run `--concepts` and fix what it reports. Show the user what you found and the concepts, and **wait for them to pick one**. Run `--concept <id>`; with `--sample 10` it is only the opening scenes, to build and look at first. Show that storyboard as above and wait for them to confirm. Agent Video adds no narration. What its storyboards cannot say - a tier list or banner that stays up under the speaker, pictures popping up as things are said - write as one HyperFrames composition and add it to `storyboard.json` as its `overlay` after `--concept`; snapshot it with `npx hyperframes@0.8.199 snapshot <folder> --at <seconds> --describe false` before building (`--describe false` keeps it from sending frames to Gemini when a key is set).

4. **Build.** Run `python -m project.produce output/<name> --build --open`. If it reports problems, fix `storyboard.json` and run it again until it succeeds. If the storyboard has `generated` scenes and the build stops over the cap, tell the user what each costs and add `--budget <dollars>` only once they say so.

5. **Report.** Tell the user the length against the brief, what is on each track, anything the build flagged with `!` in the picture, and that it is an ordinary project: they can change it in OpenShot, or ask for changes in words (the edit skill).
