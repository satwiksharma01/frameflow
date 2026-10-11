# Contributing

Start with the [README](README.md) and [engineering notes](docs/ENGINEERING.md). For core changes, Python 3.13 and `python -m pip install -r requirements.txt` are sufficient; real media checks also need the documented Shotcut, FFmpeg and Whisper setup.

Before opening a pull request:

```bash
python -m unittest discover -s tests -v
python -m examples.demo_timeline
```

Explain the failing behavior, your change, and which checks ran. For a bug, add a small regression case to the existing relevant test module. Core tests should not call a paid model provider or depend on a private recording. Report media-dependent skips and any full workflow checks separately.

Useful bounded contributions include reproducing a refused manual edit with a minimal `.mlt`/sidecar fixture, testing another operating system's full media workflow, and improving provider error handling with mocked clients. Discuss new timeline operations before implementing them: preserving existing edits is part of the contract.

Use synthetic or redistributable media in reports. Remove credentials, personal recordings and machine-specific paths. Contributions use this repository's existing GPL-3.0 license.
