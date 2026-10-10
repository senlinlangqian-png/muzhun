import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from muzhun.editing import StaleRevision
from muzhun.lyrics import (align_lines, parse_lyrics, process_lyrics, recognition_issues,
                           refresh, revise_lyrics, save_lyrics, units)
from muzhun.server import create_app
from test_v06 import wav_bytes


def recognized(language="zh"):
    return ([{"word": "夜風", "start": .2, "end": .6}, {"word": "的聲音", "start": .6, "end": 1.2}],
            [{"text": "夜風的聲音", "start": .2, "end": 1.2, "no_speech_prob": .1, "avg_logprob": -.2}],
            {"engine": "test-recognizer", "language": language, "model": "base"})


def draft(root, text="", language="zh", script="auto"):
    source = root / "original.wav"
    source.write_bytes(wav_bytes())
    with patch("muzhun.lyrics.recognize_audio", return_value=recognized(language)) as asr:
        result = process_lyrics(source, root / "out", text, "base", root / "cache", language, script=script)
    return result, asr


class LyricsRefinementTests(unittest.TestCase):
    def test_script_variants_match_without_rewriting_supplied_wording(self):
        self.assertEqual(units("夜風的聲音"), units("夜风的声音"))
        lines, _ = parse_lyrics("夜風的声音", 2)
        result = align_lines(lines, recognized()[0], 2)
        self.assertEqual(result[0]["text"], "夜風的声音")
        self.assertEqual(result[0]["coverage"], 1)
        self.assertEqual(result[0]["anchor_text"], "夜風的聲音")

    def test_automatic_chinese_is_simplified_and_raw_asr_is_retained(self):
        with tempfile.TemporaryDirectory() as name:
            result, _ = draft(Path(name))
            self.assertEqual(result["lines"][0]["text"], "夜风的声音")
            self.assertEqual(result["lines"][0]["original"], "夜風的聲音")
            self.assertEqual(result["recognition"]["segments"][0]["text"], "夜風的聲音")
            self.assertTrue(result["summary"]["can_realign"])

    def test_explicit_original_and_non_chinese_auto_are_preserved(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for language, script in (("zh", "original"), ("ja", "auto")):
                with self.subTest(language=language, script=script):
                    result, _ = draft(root, language=language, script=script)
                    self.assertEqual(result["lines"][0]["text"], "夜風的聲音")

    def test_supplied_traditional_text_is_preserved_even_with_simplified_option(self):
        with tempfile.TemporaryDirectory() as name:
            result, _ = draft(Path(name), "夜風的聲音", script="simplified")
            self.assertEqual(result["lines"][0]["text"], "夜風的聲音")
            self.assertEqual(result["text_source"], "provided-lyrics")

    def test_realign_uses_saved_anchors_and_undo_restores_text_source_and_review(self):
        with tempfile.TemporaryDirectory() as name:
            original, _ = draft(Path(name))
            marked = revise_lyrics(original, {"revision": 0, "edits": [{"id": 1, "reviewed": True}]})
            with patch("muzhun.lyrics.recognize_audio") as asr:
                aligned = revise_lyrics(marked, {"revision": 1, "action": "realign", "lyrics": "夜风\n的声音"})
                asr.assert_not_called()
            self.assertEqual([r["text"] for r in aligned["lines"]], ["夜风", "的声音"])
            self.assertEqual(aligned["summary"]["reviewed"], 0)
            self.assertEqual(aligned["text_source"], "provided-lyrics")
            restored = revise_lyrics(aligned, {"revision": 2, "action": "undo"})
            self.assertEqual(restored["lines"], marked["lines"])
            self.assertEqual(restored["text_source"], "asr-transcript")
            self.assertEqual(restored["script_output"], "simplified")
            redone = revise_lyrics(restored, {"revision": 3, "action": "redo"})
            self.assertEqual(redone["lines"], aligned["lines"])
            self.assertEqual(redone["text_source"], "provided-lyrics")

    def test_missing_anchor_and_stale_revision_do_not_change_original(self):
        with tempfile.TemporaryDirectory() as name:
            original, _ = draft(Path(name))
            snapshot = copy.deepcopy(original)
            with self.assertRaises(StaleRevision):
                revise_lyrics(original, {"revision": 9, "action": "realign", "lyrics": "夜风"})
            with self.assertRaises(ValueError):
                revise_lyrics(original, {"revision": 0, "action": "realign", "lyrics": 5})
            self.assertEqual(original, snapshot)
            old = copy.deepcopy(original)
            old.pop("recognition")
            with self.assertRaisesRegex(ValueError, "旧记录"):
                revise_lyrics(old, {"action": "realign", "lyrics": "夜风"})

    def test_old_record_can_import_timed_lyrics_without_audio_anchors(self):
        with tempfile.TemporaryDirectory() as name:
            original, _ = draft(Path(name))
            original.pop("recognition")
            updated = revise_lyrics(original, {"action": "realign", "lyrics": "[00:00.40]原创歌词"})
            self.assertEqual(updated["text_source"], "supplied-lrc")
            self.assertEqual(updated["lines"][0]["start"], .4)

    def test_legacy_list_history_can_still_undo_and_redo(self):
        with tempfile.TemporaryDirectory() as name:
            original, _ = draft(Path(name))
            earlier = copy.deepcopy(original["lines"])
            earlier[0]["text"] = "之前的文字"
            original["history"]["undo"].append(earlier)
            restored = revise_lyrics(original, {"action": "undo"})
            self.assertEqual(restored["lines"], earlier)
            redone = revise_lyrics(restored, {"action": "redo"})
            self.assertEqual(redone["lines"], original["lines"])

    def test_explicit_simplify_only_invalidates_changed_lines_and_is_undoable(self):
        with tempfile.TemporaryDirectory() as name:
            original, _ = draft(Path(name), "夜風\n的声音")
            marked = revise_lyrics(original, {"edits": [{"id": 1, "reviewed": True}, {"id": 2, "reviewed": True}]})
            converted = revise_lyrics(marked, {"action": "simplify"})
            self.assertEqual(converted["lines"][0]["text"], "夜风")
            self.assertEqual(converted["lines"][0]["original"], "夜風")
            self.assertFalse(converted["lines"][0]["reviewed"])
            self.assertTrue(converted["lines"][1]["reviewed"])
            restored = revise_lyrics(converted, {"action": "undo"})
            self.assertEqual(restored["lines"], marked["lines"])

    def test_zero_length_words_are_points_not_invented_durations(self):
        lines, _ = parse_lyrics("夜风", 2)
        words = [{"word": "夜", "start": .2, "end": .2}, {"word": "风", "start": .8, "end": 1}]
        aligned = align_lines(lines, words, 2)[0]
        self.assertEqual((aligned["start"], aligned["end"]), (.2, 1))
        self.assertTrue(any("时间点" in issue for issue in aligned["issues"]))
        for word in words:
            word.update(start=.2, end=.2)
        unknown = align_lines(lines, words, 2)[0]
        self.assertIsNone(unknown["start"])
        self.assertIsNone(unknown["end"])

    def test_time_past_audio_does_not_make_invalid_interval(self):
        lines, _ = parse_lyrics("夜风", 2)
        aligned = align_lines(lines, [{"word": "夜风", "start": 2.01, "end": 2.02}], 2)
        self.assertIsNone(aligned[0]["start"])

    def test_suspicious_transcripts_are_flagged_and_never_deleted(self):
        self.assertTrue(recognition_issues({"text": "字幕by示例", "no_speech_prob": .9}, "zh"))
        self.assertTrue(recognition_issues({"text": "Instrumental music"}, "zh"))
        self.assertFalse(recognition_issues({"text": "夜风的声音"}, "zh"))
        with tempfile.TemporaryDirectory() as name:
            words, cues, info = recognized()
            cues[0]["no_speech_prob"] = .9
            with patch("muzhun.lyrics.recognize_audio", return_value=(words, cues, info)):
                root = Path(name)
                source = root / "source.wav"
                source.write_bytes(wav_bytes())
                result = process_lyrics(source, root / "out", "", "base", root / "cache")
            self.assertEqual(result["summary"]["total"], 1)
            self.assertTrue(result["lines"][0]["issues"])

    def test_realign_keeps_unheard_lines_and_removes_previous_full_exports(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            original, _ = draft(root)
            aligned = revise_lyrics(original, {"action": "realign", "lyrics": "夜风的声音\nmissing unheard line"})
            save_lyrics(aligned, root / "out")
            self.assertEqual(aligned["summary"]["total"], 2)
            self.assertIsNone(aligned["lines"][1]["start"])
            self.assertFalse((root / "out/lyrics.lrc").exists())
            self.assertTrue((root / "out/lyrics-result.json").exists())

    def test_fixed_overlap_does_not_keep_a_stale_warning(self):
        with tempfile.TemporaryDirectory() as name:
            result, _ = draft(Path(name), "夜风\n的声音")
            result["lines"][0]["end"] = .9
            refresh(result)
            self.assertIn("与下一行时间重叠", result["lines"][0]["issues"])
            fixed = revise_lyrics(result, {"edits": [{"id": 1, "end": .6}]})
            self.assertNotIn("与上一行时间重叠", fixed["lines"][1]["issues"])

    def test_api_realign_and_undo_restore_download_source(self):
        with tempfile.TemporaryDirectory() as name, patch("muzhun.lyrics.recognize_audio", return_value=recognized()), TestClient(create_app(Path(name))) as client:
            headers = {"X-Muzhun-Token": client.get("/api/status").json()["token"]}
            created = client.post("/api/lyrics", headers=headers, files={"audio": ("demo.wav", wav_bytes())}, data={"language": "zh"})
            job = created.json()["id"]
            for _ in range(100):
                state = client.get(f"/api/lyrics/{job}").json()
                if state["status"] in {"ready", "error"}:
                    break
                time.sleep(.01)
            self.assertEqual(state["status"], "ready", state)
            endpoint = f"/api/lyrics/{job}/revise"
            updated = client.post(endpoint, headers=headers, json={"revision": 0, "action": "realign", "lyrics": "夜风\n的声音"})
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertEqual(updated.json()["summary"]["total"], 2)
            self.assertEqual(client.get(f"/api/lyrics/{job}/files/lyrics.lrc?revision=0").status_code, 409)
            restored = client.post(endpoint, headers=headers, json={"revision": 1, "action": "undo"})
            self.assertEqual(restored.json()["text_source"], "asr-transcript")
            downloaded = client.get(f"/api/lyrics/{job}/files/lyrics.lrc?revision=2")
            self.assertIn("夜风的声音", downloaded.text)
            forbidden = client.post("/api/lyrics", headers=headers, files={"audio": ("demo.wav", wav_bytes())}, data={"script": "unknown"})
            self.assertEqual(forbidden.status_code, 400)


if __name__ == "__main__":
    unittest.main()
