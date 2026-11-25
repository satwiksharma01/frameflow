# The agent's eyes: open-source tools Frameflow can use, and Higgsfield's GitHub

**Date:** 2026-11-22 · **Status:** research, not a spec · **Follows:** [2026-11-22-cardboard-research.md](2026-11-22-cardboard-research.md), section 7 ("Eyes")

**How licences were checked:** code licences from GitHub's own `license` field (`gh api repos/<owner>/<repo>`); model-weight licences from each Hugging Face model card's `license:` tag; installed packages from their metadata. Code and weights are listed separately, because a model's weights often carry a different licence from its code. Checked on 2026-11-22.

**A constraint carried over:** Frameflow avoids a PyTorch install (`project/transcribe.py` uses whisper.cpp for that reason). ONNX Runtime 1.25 (MIT) and OpenCV 4.12 (Apache-2.0) are already installed, ONNX Runtime with the Piper voices. Every model below has an ONNX build or can run through one, so the eyes need no new runtime.

---

## What "eyes" means here

The abilities Cardboard's agent has and Frameflow's lacks:
1. seeing inside a clip;
2. finding the shot cuts;
3. finding a shot by meaning;
4. describing a shot and where things are in it;
5. knowing where the person is;
6. cutting the person out;
7. hearing speech apart from music;
8. judging whether a shot looks good;
9. looking at its own finished result.

## The tools, ability by ability

| Ability | Pick | Code licence | Weights licence | Runs on | Why, and the alternatives |
|---|---|---|---|---|---|
| 1. See inside a clip (frame sheets, single frames) | **ffmpeg** | (already used) | — | CPU | No new dependency: a tiled frame sheet per clip, as run 11 did by hand and the taste-engine plan's `from-reel` already specifies |
| 2. Shot cuts | **TransNetV2** (soCzech/TransNetV2, 1.1k stars) | **MIT** | **MIT** (in the repository) | CPU, via ONNX | The strongest open shot-boundary model. *Simpler alternative:* PySceneDetect (BSD-3-Clause, 5.6k stars, active) or ffmpeg's scene score, with no model at all |
| 3. Search by meaning | **CLIP ViT-B/32**, LAION's weights (`laion/CLIP-ViT-B-32-laion2B-s34B-b79K`) or the ONNX build `Xenova/clip-vit-base-patch32` | **MIT** (openai/CLIP, open_clip) | **MIT** | CPU, via ONNX | Turns every shot's frames and every query ("the close-up of the collar") into vectors, then compares them. *Better but not MIT:* SigLIP 2 (Apache-2.0). *Avoid:* Apple's MobileCLIP (its licence restricts use) |
| 3b. The index itself | **plain NumPy** | (already used) | — | CPU | A creator's library is thousands of shots, not millions: a cosine comparison in NumPy is enough. *If it ever grows:* FAISS (**MIT**, 42k stars) |
| 4. Describe a shot; find a thing in it; read its text | **Florence-2** base (0.23B) or large (`microsoft/Florence-2-base`, ONNX build `onnx-community/Florence-2-base`) | **MIT** | **MIT** | CPU, via ONNX | One small model that captions a frame, finds objects with boxes ("the tote bag" gives its box, which tells a zoom where to land) and reads on-screen text. *Larger, Apache-2.0:* Moondream 2, SmolVLM, Qwen2.5-VL-7B. *Avoid:* Qwen2.5-VL-3B (no open licence on its card) |
| 5. Where the person is (reframing, text off faces) | **OpenCV**'s face detector (already used); **MediaPipe** for body and face landmarks | Apache-2.0 | Apache-2.0 | CPU | Frameflow's reframing and picture check already use OpenCV. MediaPipe adds the whole body, so a full-body outfit shot stays framed. *For tracking across frames:* ByteTrack (**MIT**) and Roboflow `supervision` (**MIT**, 52k stars) |
| 6. Cut the person out (text behind the head) | **rembg** with **BiRefNet** | **MIT** (rembg, BiRefNet) | **MIT** (`ZhengPeng7/BiRefNet`) | CPU, via ONNX | Per-frame masks of the subject. The fix for the reviewer's "hook text in front of the head". Slow on long clips, so use it only on the frames a title sits over. *Steadier on video:* RobustVideoMatting, **GPL-3.0**: not MIT, but compatible with Frameflow's own GPLv3 |
| 7. Speech apart from music | **whisper.cpp** (already used) + **Silero VAD** | **MIT** (both) | **MIT** | CPU | Silero says where someone is actually speaking, so music in a clip isn't turned into "lyrics", as run 11's transcripts were. *To pull music out of a recording:* Demucs (**MIT**, but archived in 2024: no fixes coming) |
| 8. Does this shot look good? | **OpenCV** measures (sharpness, exposure, shake) + **an aesthetic score** on the CLIP vectors already computed | Apache-2.0 | improved-aesthetic-predictor: **Apache-2.0** | CPU | Ranks blurry, dark or shaky takes down before the agent sees them. The aesthetic score reuses ability 3's vectors at almost no cost |
| 9. Look at its own result | **The creator's own agent** (Claude Code, OpenCode, or their key) | — | — | the agent | Claude and the others already see images. Frameflow renders a frame sheet of the built preview and asks the agent to judge it against the plan and the direction. Free under the creator's own plan, exactly what Cardboard's "look" does |

### Considered and left out

- **video-db/Director** (MIT): an agent framework for video, but built around VideoDB's paid cloud service.
- **modelscope/FunClip** (MIT): clipping by an LLM, built on FunASR, which is tuned for Chinese; Frameflow's `shorts` already does this with the creator's agent.
- **Moment-DETR** (MIT code): its weights are trained on the QVHighlights dataset, which as far as I know is licensed non-commercial (not checked this time).
- **Ultralytics YOLO:** AGPL-3.0.

## How the eyes would fit Frameflow

At **prepare**, once per clip and cached beside the clip's transcript:
- a frame sheet;
- shot cuts;
- per-shot CLIP vectors, a Florence-2 caption, quality measures, and where the person is;
- speech regions from Silero.

The result is a **shot index** (`shots.json`) in the video folder. Requests carry a short summary of the shots, not the frames. The agent opens a frame sheet only when it needs to, which is the same harness rule as the playbooks.

At **storyboard**, a scene can name a shot by meaning ("the collar close-up"), and Frameflow resolves it through the index to a clip and a start time. No more reading frames by hand.

After **build**, a **look step** runs alongside the deterministic checks:
- Frameflow renders a frame sheet of the preview (it already renders frames for the picture check);
- the agent judges it against the plan and the contract;
- what the agent finds becomes fix requests, as the check by ear's findings already do.

**Cost:**
- Everything above is free and local.
- First run: the models add a few hundred MB of downloads, made once like the whisper model.
- Indexing a few minutes of clips takes a few minutes on CPU; a GPU makes it much faster.
- The look step uses the creator's own agent.

---

## Higgsfield's GitHub (github.com/higgsfield-ai)

Eleven public repositories. The ones that matter to Frameflow:

| Repository | Licence | What it is | What it means for Frameflow |
|---|---|---|---|
| **skills** (2k stars) | **MIT** | Nine agent skills for Claude Code, Codex and Cursor that drive Higgsfield's paid API through its CLI. They cover generation across 30+ models (Veo 3.1, Kling 3.0, Seedance 2.5, Soul V2 and others), Soul ID (a face-faithful character), product photoshoots, brand kits, faceless videos, YouTube thumbnails, and a "Virality Predictor" that scores finished videos | **The connector, ready-made.** "Connect Higgsfield" can mean installing their CLI and skills with the creator's own Higgsfield account: generation and virality scores, paid by the creator, nothing for Frameflow to build. Their `evals/` folder (fixed scenarios scored by a rubric, by hand, each round) is a simple pattern Frameflow's skills could copy |
| **cli** (721 stars) | **MIT** | The command line for their API: images, video, 3D, audio, and finished-video analysis from 40+ models | What the skills call. It needs a Higgsfield account and credits |
| **higgsfield-video-engineer** (15 stars, new) | **MIT** | Short animated films where every frame is drawn by code: their own WebGPU path tracer renders felt, paper, clay, glass and smoke locally, on Mac, Windows and Linux, with no account. An agent follows a pipeline: story, music, shot plan, concept images, characters and set, rough cut, look, final render, sound, review, delivery | Free, local, stylised 3D motion: a candidate for "motion graphics from one line" beyond what HyperFrames draws, like Cardboard's 3D product spins. It's young and GPU-heavy (about 40 s a frame on an M4 Max at final quality), so it's for later, for short inserts only. Its staged pipeline is a good model for how Frameflow's own agent steps are laid out |
| higgsfield-client (Python), higgsfield-js | Apache-2.0; none | SDKs for their API | The JavaScript SDK has no licence, so its code can't be reused; the CLI makes both unnecessary |
| higgsfield | Apache-2.0 | GPU orchestration for training large models | Not relevant |
| app-templates, cursor-plugin, omagotchi, homebrew-tap, terraform-aws-alternat | various | Templates, plugins, packaging | Not relevant |

**In short:** Higgsfield's open source is mostly the road into its paid platform, plus one free local renderer. That's good news for "connect Higgsfield later": it's an install of their MIT CLI and skills under the creator's account, not something Frameflow has to build.
