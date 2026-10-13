# Video subtitles

Use `deliver VIDEO --out NEW_DIRECTORY` for end-to-end work; `process` for analysis and editable SRT/ASS only. Supply `--srt` when the user already has authoritative subtitles; this skips ASR and must not be described as independent recognition. Prefer profile auto and professional style unless the user asks for gaming styling. `--language zh` helps when the language is known; `--glossary FILE` supplies terms. `--script original` preserves the recognized Chinese script.

Read result.json and delivery-C/manifest.json. Check pending corrections, recognition_review, screen bindings, layout warnings and the exact revision. One cue may contain several timed placements; match by cue id and interval. View actual rendered preview images, especially position changes and long captions. Check spoken meaning where audio playback is available.

Use revise for text, time, profile or protected-region changes. Replacement previews do not mutate; inspect them before applying with the preview revision. Whole Latin words protect identifiers such as LoRA2. Preserve prior manual decisions. C can change position within a cue; use position_policy static if the user prefers one position per sentence. A pin locks the whole cue. Sampled OCR and configurable game guards are not object tracking.

Use review only after actually checking the saved sentence. Changed text, timing or placement invalidates affected stamps. Undo/redo preserve up to 30 compact editions. After edits use package, which refreshes exports without repeating OCR or ASR. ASS retains positions and style; SRT retains each edited cue once and carries no position. Deliver MP4/ZIP plus review.html as appropriate; do not claim a basic file check establishes recognition accuracy.
