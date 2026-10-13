---
name: muzhun-subtitles
description: "Generate and edit local video subtitles or audio LRC/SRT. Use for speech transcription, screen-linked terminology checks, subtitle placement, lyric timing correction, and rendered video delivery."
---

# Muzhun Subtitles

Run the local Muzhun engine, inspect its actual results, and deliver editable subtitles. The browser and this skill use the same engine. A host must be able to read files and execute Python; a model-only chat cannot run the engine.

## Start and route

Use this skill's `scripts/run.py` with the commands in [references/cli.md](references/cli.md). Input and output paths must be absolute because the launcher changes to the engine directory.

- **Video:** read [references/video.md](references/video.md). `deliver` recognizes speech, checks visible terms, lays out subtitles, renders an MP4 and makes a reviewable ZIP. Use `process` for subtitle files without rendering.
- **Audio or songs:** read [references/lyrics.md](references/lyrics.md). Use `lyrics`, with `--content speech` for spoken audio and `--content song` for singing. A supplied TXT controls wording; LRC/SRT imports its own timestamps.
- **Existing result:** use the edit, review, undo, re-alignment and package commands. Do not re-run recognition just to change text, timing or placement.
- **Evaluation:** read [references/evaluation.md](references/evaluation.md) only for comparisons or friend testing.

Run `doctor` when the runtime is unknown. If missing, download the full source from the project's GitHub Releases, extract it, then run `python scripts/run.py setup --source ABSOLUTE_PROJECT --agent AGENT`. Alternatively run `python scripts/setup.py --agent AGENT` from the full project. The standalone skill ZIP does not include the processing engine. Setup installs dependencies, installs a verified CJK font only if necessary, and registers the selected skill. It does not download speech models. Do not assume Codex's bundled Python exists on another user's computer.

The launcher finds MUZHUN_HOME first, then its install record, a containing source checkout, or the shared engine record created by setup. A machine's record does not grant access to its filesystem from another sandbox. Use an engine and inputs accessible inside the actual execution environment.

## Recognition and delivery decisions

Video limits are 2 GB / 2 hours; audio is 512 MB / 2 hours. Longer inputs run in 5-minute owner windows with context overlap, real global time offsets, and reusable completed chunks. Retry an interrupted run in the same output directory; a new normal task should use a new directory. Do not overwrite a usable result to conceal failure.

Small is the balanced default; Base is a quick CPU preview, and large-v3-turbo is a larger, slower option when requested. Set the known language and provide verified terminology when useful. Larger models and model word scores are not guarantees of accuracy. Speech uses VAD; songs do not silently discard singing with speech-only VAD. First use downloads the chosen model.

Preserve raw wording and supplied text. Chinese ASR display defaults to simplified while retaining the original. Screen text supports a correction candidate but does not prove what was spoken. Keep uncertain changes pending, preserve identifiers and nicknames, and never replace missing lyric timings with evenly distributed guesses.

Review the saved result and actual exported previews. Human review marks require listening and, for video, checking the picture; zero pending proposals does not mean fully reviewed. State the transcription source, unresolved words/timings, actual output paths and checks performed. Distinguish synthetic demonstrations, internal estimates, and independent user evaluation.
