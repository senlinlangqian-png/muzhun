# CLI and edit schema

## Portable installation

Install the repository environment first: on Windows run `run.ps1 -InstallOnly`; on macOS/Linux run `python3 scripts/launch.py --install-only`. Then run the project interpreter with `scripts/install_skill.py --agent deepseek` (DeepSeek Harness), `--agent claude`, `--agent cursor`, `--agent codex`, `--agent gemini`, `--agent opencode`, `--agent kimi`, or `--agent agents` (shared ~/.agents/skills). Windows also supports `install-skill.ps1 -Agent deepseek`. Existing installations require --update / -Update. --destination overrides the target. This copies the same skill and writes a runtime record local to that device; a copied record from someone else's computer is not portable.

DeepSeek Harness uses DSH_HOME/skills, default ~/.dsh/skills. In a normal local skill-enabled session invoke /muzhun-subtitles. Codex uses $muzhun-subtitles; Claude Code and Cursor use /muzhun-subtitles. If discovery is disabled or unavailable, explicitly load this SKILL.md and execute its scripts/run.py with a working Python interpreter. This does not install or configure the agent itself.

Gemini CLI uses ~/.gemini/skills, OpenCode uses ~/.config/opencode/skills, and Kimi Code CLI uses ~/.kimi/skills. Ask these agents to use the muzhun-subtitles skill; do not assume an identical slash command in every host. Current Codex also documents ~/.agents/skills, so --agent agents is an alternative for a new installation. Keep a single installed copy per discovery scope to avoid stale duplicates; the codex target preserves this desktop's CODEX_HOME / ~/.codex setup. Tool and shell access must be enabled in the chosen agent session.

## Audio / LRC

~~~text
python scripts/run.py lyrics AUDIO.mp3 --text LYRICS.txt --out OUTPUT --model small --language zh
python scripts/run.py lyrics AUDIO.wav --out OUTPUT --model base
python scripts/run.py lyrics AUDIO.mp3 --text EXISTING.lrc --out OUTPUT
python scripts/run.py lyrics AUDIO.mp3 --out OUTPUT --language zh --script original
python scripts/run.py lyrics-align OUTPUT/lyrics-result.json --text CORRECTED.txt --revision 0
python scripts/run.py lyrics-revise OUTPUT/lyrics-result.json --edits edits.json
~~~

TXT is one performed line per row, including each repeated chorus. LRC/SRT supplies timing and skips ASR. lyrics-result.json records the exact original wording, raw recognition words/segments, ASR provenance, text-match coverage, timing issues, human review, revision and 30-step undo/redo. Null times stay visible for manual location; LRC/SRT are written only when every line has a valid time. Output is ordinary line-timed LRC (not word-highlight karaoke). Blank LRC events request clearing during an instrumental gap; player support varies.

lyrics-align reuses recognition.words without rerunning ASR and replaces the complete lyric timeline with the supplied rows. Use the actual current revision, not the example zero. A 0.6 report has no raw word cache and needs a new processing run for plain-text realignment; importing a timed LRC/SRT still works. The action can be undone, including the previous wording source and human marks. A fully timed result is still a draft until listened to.

--script auto (default) simplifies automatic Chinese transcription only; original keeps the recognizer's script and simplified explicitly converts it. Supplied text is unchanged regardless of that option. Matching normalizes traditional/simplified characters internally. To explicitly convert an existing result, use {"revision":0,"action":"simplify"}; original text remains saved and only changed rows lose review marks. This is script conversion, not semantic correction. recognition segments retain low-reliability evidence and credit/foreign-fragment hints prompt review; never silently remove a line based on those hints.

Edits use the current report revision:

~~~json
{"revision": 0, "edits": [{"id": 2, "start": 8.2, "end": 11.4, "text": "Supplied lyric"}]}
~~~

After listening to the saved interval, a separate edit may set reviewed:true for that id. Changed timing/text clears that mark. To shift all timed lines: {"revision":1,"offset":0.3}; negative times or times beyond the source are rejected. To undo/redo: {"revision":2,"action":"undo"}. Use lyrics-revise for these reports; the video revise/undo commands have a different schema.

## Video

Use scripts/run.py as the entrypoint, from the installed skill directory or with its absolute path. Arguments are forwarded to the discovered project Python.

~~~text
python scripts/run.py doctor
python scripts/run.py doctor --full
python scripts/run.py deliver INPUT.mp4 --out OUTPUT --model small
python scripts/run.py deliver INPUT.mp4 --srt INPUT.srt --out OUTPUT
python scripts/run.py inspect INPUT.mp4 --out INSPECTION
python scripts/run.py process INPUT.mp4 --out OUTPUT --profile auto --model base
python scripts/run.py process INPUT.mp4 --srt INPUT.srt --out OUTPUT --glossary terms.txt
python scripts/run.py revise OUTPUT/result.json --edits edits.json
python scripts/run.py replace OUTPUT/result.json --find "罗拉" --replace "LoRA"
python scripts/run.py replace OUTPUT/result.json --find "罗拉" --replace "LoRA" --ids 2 5 --apply --revision 3
python scripts/run.py review OUTPUT/result.json
python scripts/run.py review OUTPUT/result.json --ids 2 5 --revision 4
python scripts/run.py undo OUTPUT/result.json --revision 5
python scripts/run.py redo OUTPUT/result.json --revision 6
python scripts/run.py package OUTPUT/result.json --mode C
python scripts/run.py render OUTPUT/result.json --mode C
python scripts/run.py blind-pack OUTPUT/result.json
python scripts/run.py evaluate OUTPUT/result.json --annotations truth.json
~~~

On Windows, if python is unavailable, use the runtime recorded in references/runtime.json. The installation record is machine-specific and intentionally excluded from the public skill source. When no runtime exists, follow the repository README setup instead of inventing a result.

Profiles: auto, ai-code, cs2, valorant, general.
Styles: professional, gaming, minimal.
Position policies: adaptive (default, C can move within a cue) or static (one position per cue). Pass --position-policy to process/deliver, or settings.position_policy to revise. A/B keep one position per cue.
Models: tiny, base, small, medium, large-v3-turbo. First use downloads the selected model; there is no API key or automatic cloud fallback.

Glossary: one canonical term per line. Optional explicit misspellings after =, separated with |. Example: LoRA=罗拉|洛拉. A known spelling is not authority to rewrite an intentional nickname.

The report includes metadata, asr, frames, cues, settings, plans, edits, estimates, revision, review_marks and edit_history. Frame image paths are relative to the output directory. OCR and placement rectangles are [left, top, right, bottom], normalized to 0–1. Times are seconds. revision is a monotonically increasing edit number, separate from the application version. Pass it back with a mutation to reject stale edits. The example revision numbers below must be replaced by the actual current values.

Edit payload:

~~~json
{
  "revision": 3,
  "settings": {
    "profile": "ai-code",
    "style": "professional",
    "font": "sans",
    "font_scale": 1.0,
    "position_policy": "adaptive",
    "regions": [
      {"rect": [0.12, 0.70, 0.88, 0.94], "label": "正在讲解的参数表", "start": 1, "end": 5}
    ],
    "pins": {"1": [0.5, 0.15]}
  },
  "edits": {
    "1": {"decisions": {"p-COPY-KEY-FROM-REPORT": "rejected"}},
    "2": {"text": "这里使用 PyTorch。", "start": 5, "end": 8}
  }
}
~~~

font is sans, bold or mono. Here mono chooses a clean alternative CJK face, not a true monospace face. pins use normalized center coordinates and lock the entire cue in mode C, including after a mid-sentence scene change. Set pins to an empty object to restore automatic placement. Regions use half-open intervals [start,end); omitted bounds mean from zero/through the end.

plans.C can contain several placements with the same id. Select the record whose start <= playback time < end. Each has segment_index, segment_count, movement_reason and samples with observed frame times. Nearby repeated bindings keep their own time/image records. The minimum within-cue hold is 1.2 seconds; a move must materially reduce current occlusion, so a safe position is not abandoned merely to return to the preferred bottom anchor. Rapid changes may remain blocked and require manual review. Extraction is sampled, not frame-by-frame tracking.

An edit object replaces that cue's existing edit object; include any existing decisions or timing overrides that should remain. A text override takes precedence over automatic suggestions. Use the exact stable key from cues[].proposals[].key for each decision, so changing profile or glossary cannot apply a rejection to a different suggestion. Legacy zero-based indices are migrated against the previous report's candidates. Supplying an empty edit object clears its overrides; new reports preserve source_start/source_end for timing resets. Single-track overlapping cues are rejected with an explanation.

replace defaults to a non-writing preview, with cue ids, before/after text and occurrence counts. --apply writes only confirmed changes and recalculates screen bindings and placement once for the batch. --ids scopes the changes; --ignore-case and --substring relax the default case-sensitive, whole-Latin-word matching. Chinese literals do not require Latin word boundaries. No regular expressions are evaluated, and replacement strings are literal. Blank resulting captions are rejected. Always inspect the preview before applying and pass --revision with the preview's value.

review without --ids lists each cue's pending, layout_review and reviewed fields. review --ids records actual human C-mode review; --unmark removes it. Unresolved word suggestions block a positive mark. The stamp covers text, time, word decisions and C layout. A change invalidates affected marks. Human marks are self-reported workflow records, not measured accuracy. Marking review alone does not run planning or recognition. undo/redo restore settings, overrides and matching review marks, including after reopening the report; each history operation increments revision and a new edit clears redo. History keeps 30 saves and contains no duplicate OCR frame data.

Exports: subtitles-A/B/C.srt and .ass, result.json, optional video-A/B/C.mp4 from CLI render. The web app uses video-C-rN.mp4 and delivery-C-rN.zip to identify a specific revision N. Saving a change hides previous export links until exporting again. render uses source_video in the report or --video. Frame evidence is not a verified transcript.

Optional MUZHUN_FONT points to a local readable font file. The engine measures that font and supplies it to FFmpeg. Fonts are not bundled in delivery ZIPs; another editor must have a compatible font to reproduce ASS positions. The rendered MP4 preserves the visible result.

deliver defaults to mode C and prints report plus delivery paths as JSON on stdout; progress goes to stderr. package prints its output/review/manifest/video paths, draft status, counts and basic render verification. A delivery ZIP contains relative paths only: video.mp4, subtitles.ass, subtitles.srt, review.html, manifest.json, and previews/*.jpg. Keep result.json and raw frames locally for later revisions. --synthetic-demo explicitly marks controlled synthetic input; do not mark real recordings as synthetic or pass a synthetic fixture off as independent evaluation.

For a standalone skill ZIP, install the Muzhun engine from its source package first. Windows: run run.ps1 -InstallOnly, then install-skill.ps1. macOS/Linux: run sh run.sh --install-only, then .venv/bin/python scripts/install_skill.py. Windows users need 64-bit Python 3.10+ (3.12 recommended); the source launcher has no Codex runtime dependency. Setup installs processing dependencies from package registries, not speech models. First ASR use downloads the selected model.

The installer writes CODEX_HOME/skills or ~/.codex/skills, matching this desktop setup. Use --destination for another host's documented skill folder (for example ~/.agents/skills/muzhun-subtitles). Use --update only for an intentional update. Moving the engine folder requires rerunning the installer with --update, or explicitly setting MUZHUN_HOME to the new initialized root; this override takes priority over a saved record. Do not install duplicate skills under the same name in multiple directories.

doctor returns structured checks, repair hints and cached-model names, and exits nonzero for a failed required check. --full additionally loads the OCR and speech engine libraries without downloading models. Cache presence is not proof that transcription is correct. serve --open-browser opens the browser after readiness; an occupied requested port is skipped, and the actual address is printed.
