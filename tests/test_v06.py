import copy
import importlib.util
import json
import os
import tempfile
import time
import unittest
import wave
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from muzhun.editing import StaleRevision
from muzhun.lyrics import (align_lines, lrc_timestamp, ordered_matches, parse_lyrics,
                           process_lyrics, refresh, revise_lyrics, save_lyrics, units, write_lrc)
from muzhun.server import create_app

ROOT = Path(__file__).resolve().parents[1]


def record(text="hello world\nbright sky", duration=20):
    lines, _ = parse_lyrics(text, duration)
    words = [{"word": w, "start": s, "end": e} for w, s, e in
             [("hello", 2, 2.5), ("world", 2.6, 3), ("bright", 8, 8.5), ("sky", 8.6, 9)]]
    result = {"kind": "lyrics", "revision": 0, "metadata": {"duration": duration},
              "lines": align_lines(lines, words, duration), "history": {"undo": [], "redo": []}}
    refresh(result)
    return result


def wav_bytes(seconds=2):
    target = BytesIO()
    with wave.open(target, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes(b"\0\0" * int(16000 * seconds))
    return target.getvalue()


class LyricsTests(unittest.TestCase):
    def test_normalization_matches_cjk_and_latin_without_rewriting_original(self):
        self.assertEqual(units("ＬｏＲＡ，天空 bright!"), ["lora", "天", "空", "bright"])
        lines, _ = parse_lyrics("  天空，LoRA!\n天空，LoRA!  ", 20)
        self.assertEqual([r["original"] for r in lines], ["天空，LoRA!", "天空，LoRA!"])

    def test_repeated_choruses_match_different_audio_occurrences(self):
        lines, _ = parse_lyrics("shine on\nbright sky\nshine on", 20)
        words = [{"word": word, "start": i + 2, "end": i + 2.5}
                 for i, word in enumerate("shine on bright sky shine on".split())]
        aligned = align_lines(lines, words, 20)
        self.assertEqual([r["start"] for r in aligned], [2, 4, 6])

    def test_introduction_and_instrumental_gap_are_not_divided_evenly(self):
        result = record()
        self.assertEqual([(r["start"], r["end"]) for r in result["lines"]], [(2, 3), (8, 9)])
        lrc = write_lrc(result["lines"])
        self.assertIn("[00:03.00]\n[00:08.00]bright sky", lrc)

    def test_missing_lyrics_stay_visible_without_fake_time(self):
        result = record("hello world\nunheard extra words\nbright sky")
        self.assertIsNone(result["lines"][1]["start"])
        self.assertFalse(result["summary"]["exportable"])
        self.assertEqual(result["summary"]["total"], 3)

    def test_matching_coverage_is_not_a_review_mark(self):
        result = record()
        self.assertEqual(result["lines"][0]["coverage"], 1)
        self.assertEqual(result["summary"]["reviewed"], 0)

    def test_boundary_with_no_anchor_has_an_explicit_issue(self):
        result = record("lost hello world\nbright sky")
        self.assertIn("句首或句尾缺少锚点", result["lines"][0]["issues"])
        self.assertEqual(result["lines"][0]["text"], "lost hello world")

    def test_invalid_asr_time_does_not_become_an_anchor(self):
        lines, _ = parse_lyrics("hello", 20)
        aligned = align_lines(lines, [{"word": "hello", "start": float("nan"), "end": 3}], 20)
        self.assertIsNone(aligned[0]["start"])

    def test_alignment_has_a_work_bound(self):
        with self.assertRaisesRegex(ValueError, "分段"):
            ordered_matches(["a"] * 4000, ["b"] * 4000)

    def test_lrc_offset_multitags_and_clear_event(self):
        lines, source = parse_lyrics("[ar:Original demo]\n[offset:250]\n[00:01.50][00:05.50]hello\n[00:03.00]\n", 10)
        self.assertEqual(source, "supplied-lrc")
        self.assertEqual([(r["start"], r["end"]) for r in lines], [(1.25, 2.75), (5.25, 10)])

    def test_mixed_timed_and_untimed_lyrics_are_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "混有"):
            parse_lyrics("[00:01]first\nsecond", 20)

    def test_srt_keeps_text_and_time(self):
        lines, source = parse_lyrics("1\n00:00:02,000 --> 00:00:03,000\noriginal lyric\n", 20)
        self.assertEqual((source, lines[0]["start"], lines[0]["original"]), ("supplied-srt", 2, "original lyric"))

    def test_invalid_lrc_seconds_offset_or_times_fail(self):
        for text in ("[00:61]bad", "[offset:nan]\n[00:01]bad", "[offset:5000]\n[00:01]bad", "[00:21]bad"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_lyrics(text, 20)

    def test_word_timed_lrc_is_not_exported_as_literal_lyric_text(self):
        with self.assertRaisesRegex(ValueError, "逐字"):
            parse_lyrics("[00:01]<00:01.2>hello <00:01.5>world", 20)

    def test_centisecond_rounding_carries_minutes(self):
        self.assertEqual(lrc_timestamp(59.999), "[01:00.00]")
        self.assertEqual(lrc_timestamp(125.123), "[02:05.12]")

    def test_review_then_change_invalidates_then_undo_restores(self):
        initial = record()
        marked = revise_lyrics(initial, {"revision": 0, "edits": [{"id": 1, "reviewed": True}]})
        changed = revise_lyrics(marked, {"revision": 1, "edits": [{"id": 1, "text": "hello earth"}]})
        self.assertFalse(changed["lines"][0]["reviewed"])
        restored = revise_lyrics(changed, {"revision": 2, "action": "undo"})
        self.assertTrue(restored["lines"][0]["reviewed"])
        self.assertEqual(restored["lines"][0]["original"], "hello world")
        redone = revise_lyrics(restored, {"revision": 3, "action": "redo"})
        self.assertEqual(redone["lines"][0]["text"], "hello earth")

    def test_old_revision_or_nonfinite_edit_leaves_original_unchanged(self):
        initial = record()
        snapshot = copy.deepcopy(initial)
        with self.assertRaises(StaleRevision):
            revise_lyrics(initial, {"revision": 7, "edits": []})
        for start in (float("nan"), -1, 30, True):
            with self.subTest(start=start), self.assertRaises(ValueError):
                revise_lyrics(initial, {"edits": [{"id": 1, "start": start}]})
        self.assertEqual(initial, snapshot)

    def test_new_timing_and_review_must_be_separate_operations(self):
        with self.assertRaises(ValueError):
            revise_lyrics(record(), {"edits": [{"id": 1, "start": 2.1, "reviewed": True}]})
        with self.assertRaises(ValueError):
            revise_lyrics(record("unheard"), {"edits": [{"id": 1, "reviewed": True}]})

    def test_global_shift_is_bounded_and_clears_review(self):
        marked = revise_lyrics(record(), {"edits": [{"id": 1, "reviewed": True}]})
        shifted = revise_lyrics(marked, {"offset": 0.3})
        self.assertEqual(shifted["lines"][0]["start"], 2.3)
        self.assertFalse(shifted["lines"][0]["reviewed"])
        with self.assertRaises(ValueError):
            revise_lyrics(marked, {"offset": -3})

    def test_lrc_round_trip_and_exports_do_not_keep_stale_files(self):
        result = record()
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            save_lyrics(result, output)
            imported, _ = parse_lyrics((output / "lyrics.lrc").read_text("utf-8"), 20)
            self.assertEqual([(r["text"], r["start"], r["end"]) for r in imported],
                             [(r["text"], r["start"], r["end"]) for r in result["lines"]])
            revised = revise_lyrics(result, {"edits": [{"id": 1, "start": None, "end": None}]})
            save_lyrics(revised, output)
            self.assertFalse((output / "lyrics.lrc").exists())
            self.assertFalse((output / "lyrics.srt").exists())
            self.assertTrue((output / "lyrics-result.json").exists())

    def test_real_audio_lrc_import_does_not_load_asr(self):
        with tempfile.TemporaryDirectory() as name, patch("muzhun.lyrics.recognize_audio") as asr:
            root = Path(name)
            source = root / "demo.wav"
            source.write_bytes(wav_bytes())
            result = process_lyrics(source, root / "out", "[00:00.20]original demo", "base", root / "cache")
            self.assertTrue(result["summary"]["exportable"])
            self.assertEqual(result["asr"]["engine"], "supplied-timing")
            asr.assert_not_called()


class LyricsApiTests(unittest.TestCase):
    def test_upload_edit_and_revision_specific_download(self):
        with tempfile.TemporaryDirectory() as name, TestClient(create_app(Path(name))) as client:
            token = client.get("/api/status").json()["token"]
            self.assertEqual(client.post("/api/lyrics", files={"audio": ("demo.wav", wav_bytes())}).status_code, 403)
            created = client.post("/api/lyrics", headers={"X-Muzhun-Token": token},
                                  files={"audio": ("demo.wav", wav_bytes())}, data={"lyrics": "[00:00.20]original demo"})
            self.assertEqual(created.status_code, 200, created.text)
            job = created.json()["id"]
            for _ in range(100):
                state = client.get(f"/api/lyrics/{job}").json()
                if state["status"] in {"ready", "error"}:
                    break
                time.sleep(.01)
            self.assertEqual(state["status"], "ready", state)
            self.assertIn("original demo", client.get(f"/api/lyrics/{job}/files/lyrics.lrc?revision=0").text)
            revised = client.post(f"/api/lyrics/{job}/revise", headers={"X-Muzhun-Token": token},
                                  json={"revision": 0, "edits": [{"id": 1, "reviewed": True}]})
            self.assertEqual(revised.status_code, 200, revised.text)
            self.assertEqual(client.get(f"/api/lyrics/{job}/files/lyrics.lrc?revision=0").status_code, 409)
            self.assertEqual(client.get(f"/api/lyrics/{job}/files/state.json").status_code, 404)
            conflict = client.post(f"/api/lyrics/{job}/revise", headers={"X-Muzhun-Token": token}, json={"revision": 0})
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(client.get("/lyrics").status_code, 200)

    def test_deepseek_destination_respects_its_home_and_shared_home(self):
        spec = importlib.util.spec_from_file_location("portable_installer", ROOT / "scripts/install_skill.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with patch.dict(os.environ, {"DSH_HOME": str(ROOT / ".cache/dsh-home"), "DSH_AGENTS_HOME": str(ROOT / ".cache/shared-home")}):
            self.assertEqual(installer.default_destination("deepseek"), ROOT / ".cache/dsh-home/skills/muzhun-subtitles")
            self.assertEqual(installer.default_destination("agents"), ROOT / ".cache/shared-home/skills/muzhun-subtitles")
        self.assertEqual(installer.default_destination("claude").parts[-3:], (".claude", "skills", "muzhun-subtitles"))


if __name__ == "__main__":
    unittest.main()
