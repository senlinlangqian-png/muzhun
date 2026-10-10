import copy
import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from muzhun.evaluation import evaluate
from muzhun.evidence import apply_corrections, bind_regions, propose_corrections, screen_evidence, visible_terms
from muzhun.layout import overlap, plan, union_area
from muzhun.media import transcribe, write_ass
from muzhun.pipeline import process, replan
from muzhun.profiles import detect_profile, load_terms
from muzhun.subtitles import ass_escape, parse_srt, timestamp, write_srt


def frame(time=1, text="LoRA", rect=None):
    return {"time": time, "image": "frames/0000.jpg", "ocr": [
        {"text": text, "confidence": .98, "rect": rect or [.15, .80, .85, .95]}]}


def report():
    return {"metadata": {"width": 1280, "height": 720, "duration": 30},
            "settings": {"profile": "ai-code", "style": "professional", "font": "sans", "font_scale": 1, "glossary": "", "regions": [], "pins": {}},
            "frames": [frame()], "cues": [{"id": 1, "start": 0, "end": 3, "original": "现在讲罗拉。"}],
            "edits": {}, "warnings": []}


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.cue = {"id": 1, "start": 0, "end": 3, "original": "现在讲罗拉。"}
        self.terms = load_terms("ai-code")

    def test_supported_alias_is_corrected(self):
        proposals = propose_corrections(self.cue, [frame()], self.terms)
        self.assertEqual(apply_corrections(self.cue["original"], proposals), "现在讲LoRA。")
        self.assertEqual(proposals[0]["evidence"][0]["time"], 1)

    def test_without_screen_evidence_requires_review(self):
        proposals = propose_corrections(self.cue, [], self.terms)
        self.assertEqual(proposals[0]["decision"], "pending")
        self.assertEqual(apply_corrections(self.cue["original"], proposals), self.cue["original"])

    def test_other_scene_does_not_authorize_replacement(self):
        frames = [frame(20)]
        linked = propose_corrections(self.cue, frames, self.terms, True)
        independent = propose_corrections(self.cue, frames, self.terms, False)
        self.assertEqual(apply_corrections(self.cue["original"], linked), self.cue["original"])
        self.assertEqual(apply_corrections(self.cue["original"], independent), "现在讲LoRA。")

    def test_rejection_retains_original(self):
        proposals = propose_corrections(self.cue, [frame()], self.terms)
        self.assertEqual(apply_corrections(self.cue["original"], proposals, {"0": "rejected"}), self.cue["original"])

    def test_low_ocr_confidence_does_not_auto_correct(self):
        evidence = frame()
        evidence["ocr"][0]["confidence"] = .74
        proposals = propose_corrections(self.cue, [evidence], self.terms)
        self.assertEqual(proposals[0]["decision"], "pending")

    def test_acronym_not_substring_of_other_word(self):
        self.assertEqual(screen_evidence("API", [frame(text="capital")]), [])

    def test_binding_requires_a_mentioned_term(self):
        self.assertEqual(bind_regions(self.cue, "现在讲优化器。", [frame()], self.terms), [])
        self.assertTrue(bind_regions(self.cue, "现在讲LoRA。", [frame()], self.terms))

    def test_glossary_alias_and_custom_term(self):
        terms = load_terms("general", "MyAPI=我的接口|myapi\n# comment")
        cue = {**self.cue, "original": "使用我的接口"}
        proposals = propose_corrections(cue, [frame(text="MyAPI")], terms)
        self.assertEqual(apply_corrections(cue["original"], proposals), "使用MyAPI")

    def test_english_near_spelling_stays_pending(self):
        cue = {**self.cue, "original": "Use PyTorc"}
        proposals = propose_corrections(cue, [frame(text="PyTorch")], self.terms)
        self.assertTrue(proposals)
        self.assertEqual(proposals[0]["decision"], "pending")

    def test_unlisted_chinese_screen_term_can_suggest_homophone(self):
        frames = [frame(text="卷积核")]
        terms = visible_terms(frames)
        cue = {**self.cue, "original": "这里调整卷积合"}
        proposals = propose_corrections(cue, frames, terms)
        self.assertEqual(proposals[0]["to"], "卷积核")
        self.assertEqual(proposals[0]["decision"], "pending")
        self.assertEqual(apply_corrections(cue["original"], proposals), cue["original"])

    def test_chinese_homophone_requires_screen_support(self):
        cue = {**self.cue, "original": "这里调整卷积合"}
        self.assertEqual(propose_corrections(cue, [], [{"text": "卷积核", "aliases": []}]), [])

    def test_binding_groups_adjacent_parameters_on_same_line(self):
        evidence = frame(rect=[.1, .80, .2, .86])
        evidence["ocr"].append({"text": "rank = 8", "confidence": .99, "rect": [.25, .80, .50, .86]})
        regions = bind_regions(self.cue, "使用 LoRA", [evidence], self.terms)
        self.assertGreaterEqual(regions[0]["rect"][2], .50)

    def test_numeric_row_number_is_not_bound_to_decimal_substring(self):
        self.assertEqual(bind_regions(self.cue, "学习率是0.001", [frame(text="01")], []), [])

    def test_unlisted_latin_label_requires_whole_token(self):
        self.assertEqual(bind_regions(self.cue, "CAPITAL", [frame(text="API")], []), [])
        self.assertTrue(bind_regions(self.cue, "调用API", [frame(text="API")], []))


class LayoutTests(unittest.TestCase):
    def test_gaming_processing_selects_bold_by_default(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "muzhun.pipeline.probe", return_value=report()["metadata"]
        ), patch("muzhun.pipeline.extract_frames", return_value=[frame()]), patch(
            "muzhun.pipeline.recognize_frames"
        ):
            output = process(Path("source.mp4"), Path(directory), {"style": "gaming"},
                             "1\n00:00:00,000 --> 00:00:03,000\n现在讲罗拉。\n")
        self.assertEqual(output["settings"]["font"], "bold")
        self.assertEqual(output["plans"]["C"][0]["font"], "bold")

    def test_focus_is_avoided_when_space_exists(self):
        source = replan(report())
        self.assertGreater(source["plans"]["A"][0]["focus_overlap"], 0)
        self.assertEqual(source["plans"]["C"][0]["focus_overlap"], 0)

    def test_positions_fit_landscape_and_portrait(self):
        for width, height in ((1280, 720), (720, 1280), (640, 360)):
            source = report()
            source["metadata"].update(width=width, height=height)
            output = replan(source)
            for mode in ("A", "B", "C"):
                rect = output["plans"][mode][0]["rect"]
                self.assertTrue(0 <= rect[0] < rect[2] <= 1)
                self.assertTrue(0 <= rect[1] < rect[3] <= 1)

    def test_manual_pin_and_edit_persist(self):
        output = replan(report(), {"pins": {"1": [.5, .2]}}, {"1": {"text": "正确的手动字幕"}})
        self.assertEqual(output["cues"][0]["text"], "正确的手动字幕")
        self.assertEqual(output["plans"]["C"][0]["label"], "手动锁定")
        again = replan(output, {"font_scale": 1.2})
        self.assertEqual(again["cues"][0]["text"], "正确的手动字幕")

    def test_timing_edit_updates_evidence_context(self):
        source = report()
        source["frames"] = [frame(20)]
        output = replan(source, edits={"1": {"start": 19, "end": 22}})
        self.assertEqual(output["cues"][0]["text"], "现在讲LoRA。")

    def test_invalid_region_is_rejected(self):
        with self.assertRaises(ValueError):
            replan(report(), {"regions": [{"rect": [.9, .1, .1, .8]}]})

    def test_invalid_timing_is_rejected(self):
        with self.assertRaises(ValueError):
            replan(report(), edits={"1": {"start": 5, "end": 3}})

    def test_union_and_edge_touch(self):
        self.assertEqual(overlap([0, 0, .5, .5], [.5, 0, 1, .5]), 0)
        self.assertAlmostEqual(union_area([[0, 0, .5, .5], [.25, 0, .75, .5]]), .375)


class FormatAndEvaluationTests(unittest.TestCase):
    def test_numpy_word_timestamps_remain_json_serializable(self):
        words = [SimpleNamespace(start=np.int64(0), end=np.float64(.5), word="你好")]
        segment = SimpleNamespace(words=words, end=np.float64(.5))
        engine = SimpleNamespace(transcribe=lambda *_args, **_kwargs: (
            iter([segment]), SimpleNamespace(language="zh", language_probability=np.float32(.99))))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio.wav"
            with wave.open(str(audio), "wb") as source:
                source.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                source.writeframes(b"\0\0" * 16000)
            with patch("muzhun.media.whisper_model", return_value=engine), patch(
                "muzhun.media.subprocess.run", return_value=SimpleNamespace(returncode=0)
            ):
                cues, info = transcribe(root / "source.mp4", {"has_audio": True, "duration": 1},
                                       "small", root, lambda *_: None, audio, ["LoRA"])
            serialized = json.loads(json.dumps({"cues": cues, "asr": info}))
            self.assertEqual(serialized["cues"][0]["start"], 0)
            self.assertEqual(serialized["asr"]["screen_hotwords"], ["LoRA"])

    def test_ass_exports_selected_bold_and_outline(self):
        output = replan(report(), {"style": "gaming", "font": "bold"})
        exported = write_ass(output["plans"]["C"], 1280, 720)
        self.assertIn(r"\b1\bord3", exported)
        output = replan(report(), {"style": "minimal", "font": "sans"})
        self.assertIn(r"\b0\bord2", write_ass(output["plans"]["C"], 1280, 720))

    def test_srt_roundtrip_and_carry(self):
        cues = [{"start": 1.234, "end": 3.9996, "text": "LoRA"}]
        parsed = parse_srt(write_srt(cues))
        self.assertEqual(parsed[0]["end"], 4)
        self.assertEqual(timestamp(59.9996), "00:01:00,000")
        self.assertEqual(timestamp(59.996, True), "0:01:00.00")

    def test_ass_control_text_cannot_inject_style(self):
        escaped = ass_escape(r"{\pos(0,0)}test")
        self.assertNotIn("{", escaped)
        self.assertNotIn("\\pos", escaped)

    def test_invalid_srt(self):
        with self.assertRaises(ValueError):
            parse_srt("not a subtitle")

    def test_keyword_detection_and_ambiguity(self):
        self.assertEqual(detect_profile("LoRA and PyTorch")["id"], "ai-code")
        self.assertEqual(detect_profile("hello everyone")["id"], "general")
        self.assertEqual(detect_profile("CS2 VALORANT")["id"], "general")
        self.assertEqual(detect_profile("gragging")["id"], "general")

    def test_independent_labels_not_engine_estimates(self):
        output = replan(report())
        labels = {"items": [{"start": 0, "end": 3, "terms": ["LoRA"], "regions": [[.15, .80, .85, .95]]}]}
        scores = evaluate(output, labels)["scores"]
        self.assertEqual(scores["A"]["terms_correct"], 0)
        self.assertEqual(scores["C"]["terms_correct"], 1)
        self.assertEqual(scores["A"]["blocked_seconds"], 3)
        self.assertEqual(scores["C"]["blocked_seconds"], 0)

    def test_term_evaluation_requires_whole_latin_token(self):
        source = {"plans": {"C": [{"start": 0, "end": 1, "text": "CAPITAL", "rect": [0, 0, .1, .1]}]}}
        labels = {"provenance": "synthetic-test", "items": [{"start": 0, "end": 1, "terms": ["API"]}]}
        result = evaluate(source, labels)
        self.assertEqual(result["scores"]["C"]["terms_correct"], 0)
        self.assertEqual(result["source"], "supplied-annotations")
        self.assertEqual(result["provenance"], "synthetic-test")
        source["plans"]["C"][0]["text"] = "调用API"
        self.assertEqual(evaluate(source, labels)["scores"]["C"]["terms_correct"], 1)


if __name__ == "__main__":
    unittest.main()
