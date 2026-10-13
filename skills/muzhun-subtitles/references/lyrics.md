# Audio, speech and lyrics

Run `lyrics AUDIO --out NEW_DIRECTORY --content speech` for courses/podcasts, or `--content song` for music. Supply `--text FILE` for the user's correct TXT/LRC/SRT, `--language` when known and `--glossary FILE` for names and terms. With no text, the wording is an ASR draft. Repeated choruses must appear in performance order in supplied text.

LRC/SRT imports its own time and skips ASR. Plain-text lyrics use ordered recognized word anchors. This remains assisted alignment rather than singing-specific forced alignment: virtual voices, strong accompaniment and drawn-out singing can leave many lines unlocated. coverage is text-match coverage, not timing accuracy. Inspect lines with null start/end; they prevent complete subtitle export. Preserve their text and report them instead of guessing times.

Use lyrics-align with the current revision to re-use stored anchors after the user supplies correct text. For a mistaken repeated chorus, use lyrics-revise with `{"action":"align-range","id":2,"start":50,"end":65,"revision":N}`. It uses only anchors in that actual interval and leaves other lines untouched.

lyrics-revise supports split (id, at character index, explicit playback time), merge with the following line, delete, simplify, edit, offset, undo and redo. A timed split needs a real playback point inside the sentence; an untimed split remains untimed. The browser provides a selectable PCM waveform, line operations and recent audio. Deletion is explicit and undoable; recognition hints do not authorize deleting lyrics automatically.

Save before listening and marking a line reviewed. Check introductions, instrumental gaps, repeated sections, flagged boundaries and timing overlap. Chinese automatic output defaults to simplified while raw recognition and original wording remain; supplied lyrics retain their script. A 0.6 run lacks word caches: import timed lyrics or run the source into a new directory before text re-alignment. Deliver ordinary line-timed LRC/SRT; word-by-word karaoke highlighting is not implemented.
