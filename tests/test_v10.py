import copy
import io
import os
import json
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from muzhun.editing import StaleRevision
from muzhun.lyrics import parse_lyrics, probe_audio, process_lyrics, revise_lyrics
from muzhun.pipeline import replan
from muzhun.server import create_app
from muzhun.transcription import pcm_window, recognize, speech_cues, windows
from muzhun.waveform import envelope
from test_engine import report
from test_v06 import record, wav_bytes
from test_v04 import load_script


def engine_segment(text, start, end):
    word = SimpleNamespace(word=text, start=start, end=end, probability=np.float32(.98))
    return SimpleNamespace(words=[word], text=text, start=start, end=end, no_speech_prob=.05, avg_logprob=-.1)


class LongRecognitionTests(unittest.TestCase):
    def test_seam_word_is_kept_when_neither_decode_owns_its_midpoint(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); path = root / "audio.wav"; path.write_bytes(wav_bytes(4))
            responses = [[engine_segment(" The", 1.9, 2.3)],
                         [engine_segment(" The", 1.7, 2.1), engine_segment(" sun.", 2.4, 2.9)]]
            count = 0
            def transcribe(*_, **kwargs):
                nonlocal count
                segments = responses[count]; count += 1
                return iter(segments), SimpleNamespace(language="en")
            words, _, _ = recognize(path, "base", root, lambda *_: None, chunk_seconds=2,
                engine_factory=lambda *_: SimpleNamespace(transcribe=transcribe))
            self.assertEqual([w["word"].strip() for w in words], ["The", "sun."])
            self.assertTrue(words[0]["boundary_review"])

    def test_windows_cover_two_hours_once_with_bounded_context(self):
        chunks = list(windows(7200))
        self.assertEqual(len(chunks), 288)
        self.assertEqual(chunks[0][1], 0)
        self.assertEqual(chunks[-1][2], 7200)
        for left, right in zip(chunks, chunks[1:]):
            self.assertEqual(left[2], right[1])
        self.assertTrue(all(end - start <= 29 for _, _, _, start, end in chunks))

    def test_pcm_reads_only_requested_interval(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "audio.wav"
            path.write_bytes(wav_bytes(5))
            result = pcm_window(path, 2, 3)
            self.assertEqual(result.dtype, np.float32)
            self.assertEqual(len(result), 16000)

    def test_chunk_offsets_no_duplicates_and_completed_cache_skips_model(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); path = root / "audio.wav"; path.write_bytes(wav_bytes(7))
            # For a 3s owner window, the second window reads from 1s.
            responses = [[engine_segment(" first", .3, .7)], [engine_segment(" second", 2.3, 2.7)], [engine_segment(" last", 2.3, 2.7)]]
            calls = []
            def transcribe(samples, **options):
                calls.append((len(samples), options))
                return iter(responses[len(calls) - 1]), SimpleNamespace(language="en", language_probability=np.float32(.99))
            engine = SimpleNamespace(transcribe=transcribe)
            words, _, info = recognize(path, "base", root, lambda *_: None,
                engine_factory=lambda *_: engine, chunk_seconds=3)
            self.assertEqual([w["start"] for w in words], [.3, 3.3, 6.3])
            self.assertTrue(all(length <= 7 * 16000 for length, _ in calls))
            self.assertTrue(calls[0][1]["vad_filter"])
            # Repetitive real speech must not trigger stochastic fallback that
            # invents repetitions and loses subsequent utterances.
            self.assertEqual(calls[0][1]["temperature"], 0)
            with patch("muzhun.media.whisper_model", side_effect=AssertionError("must reuse cache")):
                again, _, cached = recognize(path, "base", root, lambda *_: None, chunk_seconds=3)
            self.assertEqual(again, words)
            self.assertEqual(cached["cached_chunks"], 3)
            json.dumps(info)

    def test_failure_retains_completed_chunk_and_retry_continues(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); path = root / "audio.wav"; path.write_bytes(wav_bytes(4))
            attempts = 0
            def failing(*_, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 2: raise RuntimeError("interrupted")
                return iter([engine_segment(" first", .2, .8)]), SimpleNamespace(language="en")
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                recognize(path, "base", root, lambda *_: None,
                    engine_factory=lambda *_: SimpleNamespace(transcribe=failing), chunk_seconds=2)
            resumed = SimpleNamespace(transcribe=lambda *_a, **_k: (iter([engine_segment(" second", 2.2, 2.8)]), SimpleNamespace(language="en")))
            words, _, info = recognize(path, "base", root, lambda *_: None, engine_factory=lambda *_: resumed, chunk_seconds=2)
            self.assertEqual(info["cached_chunks"], 1)
            self.assertEqual([w["word"].strip() for w in words], ["first", "second"])

    def test_singing_does_not_enable_speech_vad_and_accepts_language_hints(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); path = root / "audio.wav"; path.write_bytes(wav_bytes())
            options = []
            def transcribe(*_, **kwargs):
                options.append(kwargs)
                return iter([engine_segment(" 歌詞", .1, .9)]), SimpleNamespace(language="zh")
            recognize(path, "base", root, lambda *_: None, singing=True, language="zh", hints=["LoRA"],
                      engine_factory=lambda *_: SimpleNamespace(transcribe=transcribe))
            self.assertFalse(options[0]["vad_filter"])
            self.assertEqual(options[0]["language"], "zh")
            self.assertEqual(options[0]["hotwords"], "LoRA")

    def test_cache_does_not_reuse_different_settings(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); path = root / "audio.wav"; path.write_bytes(wav_bytes())
            calls = []
            def transcribe(*_, **kwargs):
                calls.append(kwargs)
                return iter([engine_segment(" hello", .1, .9)]), SimpleNamespace(language="en")
            engine = lambda *_: SimpleNamespace(transcribe=transcribe)
            recognize(path, "base", root, lambda *_: None, engine_factory=engine)
            recognize(path, "base", root, lambda *_: None, singing=True, engine_factory=engine)
            self.assertEqual(len(calls), 2)

    def test_corrupt_completed_chunk_is_recomputed_instead_of_stalling_retry(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); path = root / "audio.wav"; path.write_bytes(wav_bytes())
            engine = lambda *_: SimpleNamespace(transcribe=lambda *_a, **_k: (
                iter([engine_segment(" hello", .1, .9)]), SimpleNamespace(language="en")))
            recognize(path, "base", root, lambda *_: None, engine_factory=engine)
            checkpoint = next((root / ".recognition").glob("*/*.json"))
            checkpoint.write_text("[]", "utf-8")
            words, _, info = recognize(path, "base", root, lambda *_: None, engine_factory=engine)
            self.assertEqual(info["cached_chunks"], 0)
            self.assertEqual(words[0]["word"], " hello")

    def test_actual_audio_over_old_ten_minute_limit_can_be_probed(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "long.wav"
            with wave.open(str(path), "wb") as output:
                output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                for _ in range(601): output.writeframesraw(b"\0\0" * 16000)
            self.assertAlmostEqual(probe_audio(path)["duration"], 601)

    def test_sentence_splitting_keeps_real_times_and_review_hints(self):
        words = [{"word": " Hello.", "start": 1, "end": 2, "probability": .2},
                 {"word": " World!", "start": 2.2, "end": 3.2, "probability": .99}]
        cues = speech_cues(words, [], 4)
        self.assertEqual([(c["original"], c["start"], c["end"]) for c in cues], [("Hello.", 1, 2), ("World!", 2.2, 3.2)])
        self.assertTrue(cues[0]["recognition_review"])

    def test_decimal_and_latin_terms_do_not_make_orphaned_numeric_cues(self):
        words = [{"word": text, "start": i * .3, "end": (i + 1) * .3} for i, text in enumerate([
            "现在", "把", " PyTorch", " 的", "学习率", "设置", "为", " 0.", "001。"])]
        cues = speech_cues(words, [], 4)
        self.assertEqual(len(cues), 1)
        self.assertIn("0.001", cues[0]["original"])
        long = [{"word": "参数" * 16, "start": 0, "end": 4.8},
                {"word": " 0.", "start": 4.8, "end": 5},
                {"word": "001。", "start": 5, "end": 5.3}]
        self.assertTrue(speech_cues(long, [], 6)[-1]["original"].endswith("0.001。"))

    def test_video_script_normalization_retains_original_and_identifiers(self):
        source = report(); source["asr"] = {"engine": "faster-whisper", "language": "zh"}
        source["cues"][0]["original"] = "畫面中的 LoRA2 與 PyTorch"
        updated = replan(source, {"script": "auto"})
        self.assertEqual(updated["cues"][0]["original"], "畫面中的 LoRA2 與 PyTorch")
        self.assertIn("画面中的 LoRA2 与 PyTorch", updated["cues"][0]["text"])
        original = replan(source, {"script": "original"})
        self.assertIn("畫面", original["cues"][0]["text"])

    def test_audio_speech_keeps_uncertain_word_and_boundary_review_flags(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); source = root / "speech.wav"; source.write_bytes(wav_bytes())
            def recognition(path, output, *_):
                (output / "audio.wav").write_bytes(path.read_bytes())
                return ([{"word": " Hello.", "start": .1, "end": .9, "probability": .1, "boundary_review": True}],
                        [], {"language": "en", "engine": "faster-whisper"})
            with patch("muzhun.lyrics.recognize_audio", side_effect=recognition):
                result = process_lyrics(source, root / "out", "", "base", root, content="speech")
            self.assertFalse(result["lines"][0]["reviewed"])
            self.assertTrue(any("边界" in issue for issue in result["lines"][0]["issues"]))


class InstallationAndOCRTests(unittest.TestCase):
    def test_verified_font_download_rejects_changed_bytes(self):
        fonts = load_script("fonts")
        with tempfile.TemporaryDirectory() as name, patch.dict(os.environ, {}, clear=True), \
             patch.object(fonts.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)), \
             patch.object(fonts.urllib.request, "urlopen", return_value=io.BytesIO(b"unexpected download")):
            root = Path(name)
            with self.assertRaisesRegex(RuntimeError, "校验失败"):
                fonts.ensure_font(Path(sys.executable), root)
            self.assertFalse((root / ".cache/fonts/NotoSansCJKsc-Regular.otf").exists())

    def test_invalid_explicit_font_does_not_download_a_replacement(self):
        fonts = load_script("fonts")
        with tempfile.TemporaryDirectory() as name, patch.dict(os.environ, {"MUZHUN_FONT": "missing-font"}), \
             patch.object(fonts.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)), \
             patch.object(fonts.urllib.request, "urlopen") as download:
            with self.assertRaisesRegex(RuntimeError, "MUZHUN_FONT"):
                fonts.ensure_font(Path(sys.executable), Path(name))
            download.assert_not_called()

    def test_downloaded_project_font_is_available_to_actual_renderer(self):
        from muzhun.media import burn_video
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            font = root / ".cache/fonts/NotoSansCJKsc-Regular.otf"
            font.parent.mkdir(parents=True); font.write_bytes(b"fixture font bytes")
            out = root / "output"; out.mkdir()
            with patch("muzhun.media.__file__", str(root / "src/muzhun/media.py")), \
                 patch("muzhun.layout.font_path", return_value=(str(font), "Noto Sans CJK SC")), \
                 patch("muzhun.media.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as renderer:
                burn_video(root / "source.mp4", out / "subtitles.ass", out / "video.mp4", lambda *_: None)
                command = renderer.call_args.args[0]
                self.assertIn("fontsdir=fonts", command[command.index("-vf") + 1])
                self.assertEqual((out / "fonts/custom.otf").read_bytes(), font.read_bytes())

    def test_identical_frame_reuses_ocr_without_sharing_mutable_boxes(self):
        from muzhun.media import recognize_frames
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "a.jpg").write_bytes(b"same encoded frame")
            (root / "b.jpg").write_bytes(b"same encoded frame")
            frames = [{"image": image, "width": 100, "height": 100} for image in ("a.jpg", "b.jpg")]
            with patch("muzhun.media.ocr_engine") as factory:
                factory.return_value.return_value = ([[[[1, 2], [30, 2], [30, 10], [1, 10]], "LoRA", .99]], None)
                recognize_frames(frames, root, lambda *_: None)
                self.assertEqual(factory.return_value.call_count, 1)
            self.assertTrue(frames[1]["ocr_reused"])
            frames[0]["ocr"][0]["rect"][0] = .9
            self.assertEqual(frames[1]["ocr"][0]["rect"][0], .01)

    def test_unified_setup_writes_resolved_record_only_after_install(self):
        launcher, installer, fonts = load_script("launch"), load_script("install_skill"), load_script("fonts")
        with patch.dict(sys.modules, {"launch": launcher, "install_skill": installer, "fonts": fonts}):
            setup = load_script("setup")
            with tempfile.TemporaryDirectory() as name:
                root = Path(name).resolve()
                record_path = root / "runtime.json"
                with patch.object(setup, "ROOT", root), patch.object(setup, "install", return_value=Path(sys.executable)), \
                     patch.object(fonts, "ensure_font"), patch.object(setup.subprocess, "run") as command:
                    self.assertEqual(setup.main(["--agent", "deepseek", "--destination", str(root / "skill"),
                                                 "--runtime-record", str(record_path)]), 0)
                    self.assertIn("deepseek", command.call_args.args[0])
                    self.assertEqual(json.loads(record_path.read_text("utf-8"))["root"], str(root))
                record_path.unlink()
                with patch.object(setup, "install", side_effect=RuntimeError("failed")):
                    self.assertEqual(setup.main(["--runtime-record", str(record_path)]), 1)
                    self.assertFalse(record_path.exists())


class LyricEditingTests(unittest.TestCase):
    def test_split_uses_explicit_playback_time_and_is_undoable(self):
        initial = record(); updated = revise_lyrics(initial, {"action": "split", "id": 1, "at": 6, "time": 2.55})
        self.assertEqual([row["text"] for row in updated["lines"]], ["hello", "world", "bright sky"])
        self.assertEqual(updated["lines"][0]["end"], 2.55)
        self.assertEqual(updated["lines"][1]["start"], 2.55)
        restored = revise_lyrics(updated, {"action": "undo", "revision": 1})
        self.assertEqual(restored["lines"], initial["lines"])

    def test_split_rejects_guessed_or_outside_time(self):
        initial = record()
        for time_value in (None, 0, 9, True, float("nan")):
            with self.subTest(time=time_value), self.assertRaises(ValueError):
                revise_lyrics(initial, {"action": "split", "id": 1, "at": 6, "time": time_value})

    def test_split_unknown_line_does_not_invent_times(self):
        initial = record(); initial["lines"][0].update(start=None, end=None)
        updated = revise_lyrics(initial, {"action": "split", "id": 1, "at": 6})
        self.assertTrue(all(row["start"] is None and row["end"] is None for row in updated["lines"][:2]))

    def test_merge_keeps_both_originals_and_invalidates_only_changed_review(self):
        initial = record(); initial["lines"][0]["reviewed"] = True
        updated = revise_lyrics(initial, {"action": "merge", "id": 1})
        self.assertEqual(updated["lines"][0]["text"], "hello world bright sky")
        self.assertEqual(updated["lines"][0]["original"], "hello world\nbright sky")
        self.assertFalse(updated["lines"][0]["reviewed"])

    def test_delete_is_explicit_preserves_source_and_can_be_redone(self):
        initial = record(); initial["recognition"] = {"words": [{"word": "original", "start": 1, "end": 2}]}
        updated = revise_lyrics(initial, {"action": "delete", "id": 1})
        self.assertEqual(len(updated["lines"]), 1)
        self.assertEqual(updated["recognition"], initial["recognition"])
        restored = revise_lyrics(updated, {"action": "undo"})
        self.assertEqual(restored["lines"], initial["lines"])
        self.assertEqual(len(revise_lyrics(restored, {"action": "redo"})["lines"]), 1)

    def test_range_alignment_distinguishes_repeated_choruses(self):
        initial = record("hello world\nhello world")
        initial["recognition"] = {"words": [{"word": w, "start": s, "end": e} for w, s, e in
            [("hello", 2, 3), ("world", 3, 4), ("hello", 12, 13), ("world", 13, 14)]]}
        updated = revise_lyrics(initial, {"action": "align-range", "id": 2, "start": 10, "end": 16})
        self.assertEqual((updated["lines"][1]["start"], updated["lines"][1]["end"]), (12, 14))
        self.assertEqual(updated["lines"][0], initial["lines"][0])

    def test_range_with_no_anchors_preserves_record(self):
        initial = record(); original = copy.deepcopy(initial)
        with self.assertRaises(ValueError):
            revise_lyrics(initial, {"action": "align-range", "id": 1, "start": 10, "end": 16})
        self.assertEqual(initial, original)

    def test_structural_edit_rejects_stale_revision(self):
        with self.assertRaises(StaleRevision):
            revise_lyrics(record(), {"action": "delete", "id": 1, "revision": 9})

    def test_more_than_500_timed_lines_can_be_imported(self):
        text = "\n".join(f"[{i//60:02d}:{i%60:02d}.00]line {i}" for i in range(600))
        rows, source = parse_lyrics(text, 601)
        self.assertEqual(len(rows), 600)
        self.assertEqual(source, "supplied-lrc")


class WaveformAndApiTests(unittest.TestCase):
    def test_waveform_is_bounded_normalized_and_reads_selected_range(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "audio.wav"
            with wave.open(str(path), "wb") as output:
                output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                output.writeframes(np.concatenate([np.zeros(16000, dtype=np.int16), np.full(16000, -32768, dtype=np.int16)]).tobytes())
            silent = envelope(path, 0, 1, 50); loud = envelope(path, 1, 4, 50)
            self.assertEqual(max(silent["peaks"]), 0)
            self.assertEqual(min(loud["peaks"]), 1)
            self.assertEqual(loud["end"], 2)

    def test_waveform_rejects_nan_and_unbounded_reads(self):
        for start, end in [(float("nan"), 1), (0, 121), (-1, 1), (2, 1)]:
            with self.subTest(start=start), self.assertRaises(ValueError):
                envelope(Path("unused"), start, end)

    def test_lyrics_history_survives_app_restart(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); folder = root / "outputs/lyrics/0123456789abcdef"; folder.mkdir(parents=True)
            (folder / "state.json").write_text(json.dumps({"id": folder.name, "name": "my audio", "status": "ready", "request": {"lyrics": "private"}}))
            with TestClient(create_app(root)) as client:
                rows = client.get("/api/lyrics").json()
            self.assertEqual(rows[0]["name"], "my audio")
            self.assertNotIn("request", rows[0])

    def test_video_retry_reuses_same_job_and_requires_local_token(self):
        prepared = replan(report())
        with tempfile.TemporaryDirectory() as name, patch("muzhun.server.process", side_effect=[RuntimeError("temporary failure"), prepared]), TestClient(create_app(Path(name))) as client:
            token = client.get("/api/status").json()["token"]; headers = {"X-Muzhun-Token": token}
            job = client.post("/api/jobs", headers=headers, files={"video": ("clip.mp4", b"demo", "video/mp4")}).json()["id"]
            for _ in range(100):
                if client.get(f"/api/jobs/{job}").json()["status"] == "error": break
                time.sleep(.01)
            self.assertEqual(client.post(f"/api/jobs/{job}/retry").status_code, 403)
            response = client.post(f"/api/jobs/{job}/retry", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["id"], job)
            for _ in range(100):
                status = client.get(f"/api/jobs/{job}").json()["status"]
                if status == "ready": break
                time.sleep(.01)
            self.assertEqual(status, "ready")
            self.assertEqual(client.post(f"/api/jobs/{job}/retry", headers=headers).status_code, 409)

    def test_limits_and_invalid_language_reported_before_processing(self):
        with tempfile.TemporaryDirectory() as name, TestClient(create_app(Path(name))) as client:
            status = client.get("/api/status").json()
            self.assertEqual(status["max_duration"], 7200)
            self.assertEqual(status["max_video_bytes"], 2 * 1024 ** 3)
            response = client.post("/api/jobs", headers={"X-Muzhun-Token": status["token"]},
                data={"language": "not-a-language"}, files={"video": ("clip.mp4", b"demo")})
            self.assertEqual(response.status_code, 400)
