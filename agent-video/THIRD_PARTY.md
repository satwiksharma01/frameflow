# Third-party components

The implementation uses Node.js standard libraries and has no third-party JavaScript package dependencies. The source, example project JSON, and agent instruction file in this directory were authored for this independent implementation.

FFmpeg and FFprobe are separate executables installed by the operator. They are not included in this product package. Their licenses and the licenses of enabled codecs depend on the selected build; inspect your chosen FFmpeg distribution before bundling or redistributing it. Official documentation: https://ffmpeg.org/legal.html and https://ffmpeg.org/ffmpeg-filters.html.

Caption rendering uses a font already installed on the operator's machine (Arial, DejaVu Sans, or Liberation Sans). A working copy may appear in a local job directory. No font file is included in this product package. Font redistribution rights belong to the chosen font and its license; local job artifacts are excluded from the package allowlist.

Hypit and REA are not dependencies, included components, or runtime requirements of this product. Reference research lives outside this directory and must remain outside product releases. This inventory is not a legal determination about commercialization or independently chosen future integrations.

Local transcription calls an operator-installed [whisper.cpp](https://github.com/ggml-org/whisper.cpp) executable and a compatible model. Neither executable, library nor model weights are included in the product archive. The verification used official build b5454 and tiny.en weights downloaded through the official model instructions. Operators should inspect the licenses supplied with their selected executable and model before redistribution.

The local end-to-end verification used the official repository's [JFK speech sample](https://github.com/ggml-org/whisper.cpp/blob/master/samples/jfk.wav). The speech file and all derived audio/video verification artifacts remain under local tooling/output directories and are excluded from the product package.
