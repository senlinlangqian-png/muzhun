---
name: muzhun-subtitles
description: "Produce and review video subtitles with screen-linked terminology and placement, or make line-timed LRC/SRT from audio and supplied lyrics. Run the local Muzhun engine and inspect unresolved timing or wording."
---

# Muzhun Subtitles

Produce usable subtitles with the Muzhun engine. Retain the original transcription, inspect correction evidence, and protect the content currently being explained. The skill's value comes from running and reviewing the engine, not from claiming generic instructions are a new recognition model.

## Start

Run this skill's scripts/run.py with the desired CLI command. The launcher discovers a repository checkout, a local installation record, or MUZHUN_HOME. Run doctor first when the runtime is not known. Read [references/cli.md](references/cli.md) for commands and the small edit schema.

This skill is portable across local agents that can read files and run Python, including DeepSeek Harness, Codex, Claude Code, Cursor, Gemini CLI, OpenCode and Kimi Code CLI. Product-specific invocation syntax only loads these instructions; scripts/run.py is the shared execution entrypoint. If a host has no skill menu, ask it to read this SKILL.md and execute that launcher. In a sandbox, initialize the engine and inputs inside that sandbox; a host runtime record does not grant remote filesystem access. Do not interpret a model-only chat as a local execution environment. Installation support does not establish that every host and model combination has been tested.

Doctor never downloads speech models. If it reports failed checks, use its repair hints before processing. A missing speech model is expected for a first run; supplied SRT and built-in demos do not require one. For missing runtime setup, use the project's launch and install commands in references/cli.md. Do not assume the user has Codex's bundled Python.

Use absolute paths for user inputs and output directories; the launcher runs the engine from its project root.

## Audio and lyrics

For audio-to-LRC requests, use the lyrics command, not video deliver. Read the lyrics section of [references/cli.md](references/cli.md). A supplied TXT is the wording authority; include repeated choruses in performance order. Existing LRC or SRT imports its own times and skips ASR. Without supplied text, the output wording is an ASR draft.

New runs retain raw ASR words and segments. If the user provides corrected lyrics after transcription, use lyrics-align with the current revision to reuse those anchors. Undo restores the previous wording source, times and review marks. A 0.6 record has no saved word anchors: run the audio into a new output directory before realigning, or import an already timed LRC/SRT. Do not overwrite the user's usable original run to hide a failed alignment.

Automatic Chinese transcription defaults to simplified text, retaining the raw transcription in original and recognition; use --script original when requested. Supplied lyrics keep their exact script. Matching normalizes script internally without rewriting the text. The explicit simplify action is reversible and clears review only on changed lines. Low-recognition, foreign-fragment and credit-like hints are review prompts, not permission to delete text automatically.

Inspect lyrics-result.json: lines with null start/end could not be aligned and block complete subtitle export. Never fill those times by distributing lyrics evenly across the track. The current method uses ordered ASR word anchors, not singing-specific forced alignment; coverage is text-match coverage, not an accuracy probability. Listen especially to introductions, instrumental gaps, repeated choruses, drawn-out singing and flagged boundaries. Preserve lyrics.original when editing. Save timing changes with lyrics-revise and the current revision; only mark reviewed after listening to that saved interval. Deliver LRC/SRT plus material unresolved timing, and distinguish ordinary line-level LRC from word-by-word karaoke highlighting.

Use the user's video and any supplied SRT or glossary. With no stated preference, choose profile auto and the professional style; choose gaming styling when the user requests it. Small is the default multilingual model; Base is a faster CPU preview. A supplied SRT is the transcription authority for the processing run; the engine then checks terminology against the picture. Do not report that supplied text was independently recognized.

## Process and review

1. Run deliver into a new output directory for a normal end-to-end request. It processes, renders an MP4, verifies basic file structure, and makes a ZIP with editable ASS/SRT, a review page, a manifest and previews decoded from the actual rendered video. Use process when the task only needs analysis or editing; use inspect for screen inspection without transcription.
2. Read result.json and delivery-C/manifest.json: profile evidence, asr source, pending suggestions, bindings, layout warnings, manual edits and verification scope. One cue may have multiple timed placements sharing its id. Match by id and interval, not list index. View the actual preview image files listed in the manifest, especially both sides of a position change, the longest caption and an unresolved cue. Where tools permit, listen to the output; basic file checks do not verify spoken meaning.
3. A nearby screen term supports a spelling candidate; it does not prove the audio said that word. Listen or use the provided authoritative transcript when a candidate could change meaning. Keep unverified candidates pending. Preserve intentional gamer nicknames, identifiers, versions, numbers, and units.
4. Correct a mistaken profile or region using revise. If changing text, replan its footprint as well. Use replace for repeated mistakes: the default command only previews; inspect the before/after rows, scope to confirmed cue ids, then apply with that preview's revision. Whole Latin words are the default, protecting identifiers such as LoRA2 and my_LoRA. Preserve existing manual overrides when deciding a candidate. Reuse the report for all edits rather than rerunning OCR and speech recognition.
5. C defaults to adaptive positions within a cue. Check every move for readability and missed important content; do not call sampled OCR object tracking. Position changes can lag a sampling interval. Use position_policy static if the user prefers each sentence to stay put. A pin locks the whole cue. Timed manual regions apply only during their specified interval in adaptive mode.
6. Run review to list unchecked cues. Only use review --ids after actually listening to those intervals and checking the picture, or following an authoritative transcript plus visual check. Pending word decisions must be resolved first. A manual review stamp applies to that exact C-mode text, timing and layout; changes clear affected stamps. Never mark the entire report reviewed merely because it has zero pending suggestions. undo/redo persist up to 30 compact revisions and restore matching review stamps; use them to recover mistakes.
7. After revisions, run package on the existing report to refresh the delivery without rerunning speech recognition or OCR. By default deliver the ZIP and its review.html, alongside the MP4 if useful. ASS preserves timed position segments; SRT keeps each original edited cue once and carries no position. The manifest separates human review from automated estimates; do not report automatic recognition as fully verified.

Profile detection is a keyword rule, not a calibrated classifier. CS2 and Valorant guards are configurable HUD presets, not object detection. This release binds visible terms and labels; it cannot guarantee understanding of all actions or professional topics. Mention only limitations encountered in the user's material.

## Compare or evaluate

For friend testing or innovation validation, read [references/evaluation.md](references/evaluation.md). Run an untouched A/B/C comparison before manual edits. Keep identical initial subtitles and fonts. Create blind-pack when requested and keep blind-key.json outside the anonymous archive. The anonymous ZIP contains an offline index.html, three clips and a scoring CSV; testers extract the whole folder, watch in the randomized order and download their filled CSV. Do not reveal the key before scoring.

## Completion

Check that exported files exist, the video contains a readable subtitle track, timestamps fit the source, and confirmed important information is visible. Report actual paths, transcription source, material unresolved suggestions, and what was verified. Distinguish synthetic demonstrations, engine estimates, and independent human evaluation; never turn internal overlap scores into accuracy or saved-time claims.
