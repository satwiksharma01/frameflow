---
name: publish
description: Write the title, description, tags and chapters for posting a finished Frameflow video on YouTube, acting as the writer yourself so no API key is needed. Use when the user asks for a title, description, tags, chapters or timestamps for a video Frameflow made, or wants it ready to upload.
---

# A publish package, with you as the writer

Frameflow works out where each chapter plays in the project as it is now and checks the package against YouTube's limits. You write the words and pick where each chapter starts.

1. **Prepare.** Run from the repository root:

   ```
   python -m project.publish "<project.osp>" --prepare
   ```

2. **Write.** Read `publish_request.md` beside the project in full and follow it, and write the package to `publish.json` beside the project. If the user wants links in the description (their other channels, a product), ask for them; never make one up.

3. **Check it and write it out.**

   ```
   python -m project.publish "<project.osp>" --write
   ```

   If it reports problems, fix `publish.json` and run it again until it succeeds.

4. **Report.** Give the title and the chapters with their times, and say where `publish.txt` is. Tell the user to run `--write` again after any change to the project, by hand or by asking, so the chapter times follow the cut. Uploading is theirs.
