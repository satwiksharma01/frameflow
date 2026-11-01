---
name: produce
description: Make a video from a prompt with Frameflow - a reel, a YouTube video, a pitch, a product ad, with or without the user on camera - as an editable OpenShot project, acting as the editor yourself so no API key is needed. Use when the user describes a video they want made, optionally with a script, recordings, images, clips or music, rather than asking to cut one raw recording (first-cut) or change an existing project (edit).
---

# A video from a prompt, with you as the editor

Frameflow does the mechanical work: transcribing recordings, reading the voiceover, rendering titles and captions with HyperFrames, turning images into clips, building the project. You decide what the video is. The user approves twice: the brief, then the storyboard.

1. **Prepare.** Pick a folder under `output/` named for the video. From the repository root, pass the user's prompt in their own words and everything they gave you:

   ```
   python -m project.produce output/<name> --prepare "<prompt>" [--script FILE] [--footage VIDEO ...] [--asset FILE ...] [--music FILE ...] [--look LUT ...]
   ```

   `--look` takes the user's own colour LUTs (`.cube` files) to choose the video's look from; OpenShot's own are offered either way.

   If it stops on a recording with "no usable speech", tell the user the measured numbers and stop.

2. **Brief.** Read `brief_request.md` in full and write `brief.json`. Show the user the brief in plain words - what the video is, for whom, how long, which shape - with any open questions. **Wait for them to confirm.** Put their answers into `brief.json` and remove `open_questions`.

3. **Storyboard.** Run `python -m project.produce output/<name> --storyboard`, read `storyboard_request.md` in full and write `storyboard.json`. Footage spans start and end inside the measured pauses listed for each recording. Show the user the script, each scene in one line (what is seen, what is said, any caption, card or B-roll), whether what is said is shown as word-by-word captions (`spoken_captions`), whether the cuts land on the music's beat (`cut_to_beat`), and the look, if any (`look`: which LUT, and how strongly). **Wait for them to confirm**, and change it as they ask.

4. **Build.** Run `python -m project.produce output/<name> --build --open`. If it reports problems, fix `storyboard.json` and run it again until it succeeds.

5. **Report.** Tell the user the length against the brief, what is on each track, and that it is an ordinary project: they can change it in OpenShot, or ask for changes in words (the edit skill).
