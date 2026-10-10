# Independent evaluation

A: original transcription with a fixed lower caption.
B: whole-video glossary/OCR correction plus ordinary OCR and profile-region avoidance, independently.
C: time-local correction evidence plus mentioned-region protection, width alternatives, and sequence layout optimization, including timed position segments within the same cue.

B is an in-project control. It is not a reconstruction of every competing product. All modes use the same initial transcript and style settings. Comparing edited C with untouched A/B measures an assisted workflow, not automatic algorithm gains.

Without SRT, the initial transcription uses visible terms as hotword hints. All three modes share these hints. A is therefore not an unprompted ASR baseline; isolate hotword contribution with a separate on/off comparison when evaluating it.

Reserve new clips that were not used to tune aliases or region weights. Ask someone who understands the content to mark correct terms and important regions before viewing scores. The synthetic demo is a controlled failure fixture, not independent data.

Fill the generated annotations-template.json:

~~~json
{
  "items": [
    {
      "start": 1.0,
      "end": 5.0,
      "terms": ["LoRA"],
      "regions": [[0.10, 0.72, 0.90, 0.94]]
    }
  ]
}
~~~

Use nonoverlapping label intervals for aggregate seconds. A term listed in an interval is counted as present or absent; this is term recall, not WER, precision, or whole-transcript correctness. Record false corrections manually against the original audio/reference. Evaluate important-region overlap by independently marked rectangles, not by copying automatic bindings.

For the contribution of timed avoidance, compare the same C transcript with position_policy static and adaptive before manual edits. Split labels when an important panel changes location; a whole-cue union loses the time information. Blocked seconds count any intersection with a specified region, not how much of it is hidden. Check that SRT still contains one event per edited cue and that ASS/MP4 show the intended segment sequence. The generator's moving-panel fixture and verify_dynamic_demo.py can exercise this mechanism; these known synthetic rectangles are not an independent user benchmark. Its best_fixed_candidate_using_truth is an evaluation-only oracle within the same candidate set, not an engine prediction.

blind-pack produces index.html, three anonymous MP4s, an Excel-readable CSV and a short instruction file. Testers extract the entire ZIP and double-click index.html. The offline page randomizes viewing order, plays one clip at a time, accepts optional observations and downloads the completed CSV. No data is uploaded. The public page and private key share a batch ID so returned results can be matched correctly. The mode correspondence remains in blind-key.json outside the ZIP. Keep identical fonts; record familiarity, wrong terms, false corrections, blocked seconds, editing minutes, clarity and willingness to use a second video. Leave unmeasured values blank. Give the private key to testers only after scoring when requested.

Report sample size, selection method, model, provided-SRT versus ASR source, synthetic status, manual interventions, raw counts and meaningful limits. Leave accuracy and editing-time improvement unclaimed until actually measured.

Each batch has its own blind-test-BATCH.zip and friend-test/BATCH/index.html. The latest private key is blind-key.json; older keys remain in blind-keys/BATCH.json, outside the anonymous archives. Match returned CSV files by batch ID. Pages flag manual intervention as an assisted workflow; use untouched reports for automatic comparisons.
