import tempfile
import unittest
from pathlib import Path

from muzhun.delivery import review_manifest
from muzhun.evaluation import evaluate
from muzhun.evidence import bind_regions
from muzhun.media import write_ass
from muzhun.pipeline import replan, save_exports
from muzhun.subtitles import parse_srt


TOP = [.02, .02, .98, .73]
BOTTOM = [.02, .27, .98, .98]


def observation(time, rect):
    return {"time": time, "image": f"frames/{time:06.2f}.jpg", "ocr": [
        {"text": "LoRA", "confidence": .99, "rect": rect}]}


def report(frames=None):
    return {"version": "0.2.0", "metadata": {"width": 1280, "height": 720, "duration": 15},
            "asr": {"engine": "provided-srt", "model": None},
            "settings": {"profile": "ai-code", "style": "professional", "font": "sans", "font_scale": 1,
                         "glossary": "", "regions": [], "pins": {}},
            "frames": frames if frames is not None else [observation(t, TOP if t < 4 or t >= 8 else BOTTOM) for t in range(12)],
            "cues": [{"id": 1, "start": 0, "end": 12, "original": "这里讲罗拉参数"}], "edits": {}}


class TemporalLayoutTests(unittest.TestCase):
    def test_same_sentence_moves_to_avoid_changing_panel(self):
        source = report()
        labels = {"provenance": "synthetic-test", "items": [
            {"start": a, "end": b, "terms": ["LoRA"], "regions": [rect]}
            for a, b, rect in [(0, 4, TOP), (4, 8, BOTTOM), (8, 12, TOP)]]}
        adaptive = replan(source)
        fixed = replan(source, {"position_policy": "static"})
        self.assertEqual(evaluate(adaptive, labels)["scores"]["C"]["blocked_seconds"], 0)
        self.assertGreater(evaluate(fixed, labels)["scores"]["C"]["blocked_seconds"], 0)
        segments = adaptive["plans"]["C"]
        self.assertEqual([(p["start"], p["end"]) for p in segments], [(0, 4), (4, 8), (8, 12)])
        self.assertEqual(adaptive["summary"]["within_cue_changes"], 2)
        self.assertTrue(all(p["end"] - p["start"] >= 1.2 for p in segments))

    def test_stable_picture_does_not_create_repeated_events(self):
        output = replan(report([observation(t, TOP) for t in range(12)]))
        self.assertEqual(len(output["plans"]["C"]), 1)
        self.assertEqual(output["summary"]["adaptive_cues"], 0)

    def test_short_flash_cannot_cause_rapid_position_oscillation(self):
        output = replan(report([observation(0, TOP), observation(1, BOTTOM), observation(1.2, TOP)]))
        self.assertEqual(len(output["plans"]["C"]), 1)
        self.assertAlmostEqual(output["estimates"]["C"]["focus_overlap_seconds"], .2)
        self.assertEqual(output["estimates"]["C"]["review_cues"], 1)

    def test_safe_position_is_kept_after_obstruction_disappears(self):
        frames = [observation(0, BOTTOM), {"time": 4, "image": "frames/empty.jpg", "ocr": []}]
        output = replan(report(frames))
        self.assertEqual(len(output["plans"]["C"]), 1)
        self.assertEqual(output["plans"]["C"][0]["label"], "上方")

    def test_pin_locks_whole_cue_even_if_picture_changes(self):
        output = replan(report(), {"pins": {"1": [.5, .88]}})
        self.assertEqual(len(output["plans"]["C"]), 1)
        self.assertEqual(output["plans"]["C"][0]["movement_reason"], "手动锁定整句")
        self.assertTrue(output["plans"]["C"][0]["needs_review"])

    def test_timed_manual_regions_apply_only_during_their_interval(self):
        output = replan(report([]), {"regions": [
            {"rect": TOP, "start": 0, "end": 4, "label": "面板甲"},
            {"rect": BOTTOM, "start": 4, "end": 12, "label": "面板乙"}]})
        segments = output["plans"]["C"]
        self.assertEqual([(p["start"], p["end"]) for p in segments], [(0, 4), (4, 12)])
        self.assertEqual(segments[0]["protected_labels"], ["面板甲"])
        self.assertEqual(segments[1]["protected_labels"], ["面板乙"])

    def test_binding_observations_keep_later_times_beyond_preview_limit(self):
        frames = [observation(t, TOP if t < 30 else BOTTOM) for t in range(40)]
        bindings = bind_regions({"start": 0, "end": 40}, "LoRA", frames, [{"text": "LoRA"}])
        self.assertEqual({b["time"] for b in bindings}, set(range(40)))
        self.assertTrue(any(b["time"] == 39 and b["rect"][1] >= .26 for b in bindings))

    def test_srt_keeps_each_cue_once_and_ass_preserves_position_events(self):
        source = report()
        source["cues"].append({"id": 2, "start": 13, "end": 14, "original": "第二条普通字幕"})
        output = replan(source)
        with tempfile.TemporaryDirectory() as directory:
            save_exports(output, Path(directory))
            exported = parse_srt((Path(directory) / "subtitles-C.srt").read_text("utf-8"))
        self.assertEqual(len(exported), 2)
        self.assertEqual(exported[0]["original"], output["cues"][0]["text"])
        self.assertEqual((exported[0]["start"], exported[0]["end"]), (0, 12))
        self.assertEqual(write_ass(output["plans"]["C"], 1280, 720).count("Dialogue:"), 4)

    def test_review_matches_cue_ids_when_first_cue_has_multiple_positions(self):
        source = report()
        source["cues"].append({"id": 2, "start": 13, "end": 14, "original": "最后这句"})
        output = replan(source)
        manifest = review_manifest(output, "C")
        self.assertEqual([c["id"] for c in manifest["cues"]], [1, 2])
        self.assertEqual(manifest["cues"][1]["text"], "最后这句")
        self.assertEqual(len(manifest["cues"][0]["segments"]), 3)
        self.assertEqual(manifest["summary"]["within_cue_changes"], 2)

    def test_policy_and_nonfinite_times_are_rejected(self):
        for settings, edits in [({"position_policy": "random"}, None),
                                ({"regions": [{"rect": TOP, "start": 4, "end": 2}]}, None),
                                ({"regions": [{"rect": TOP, "end": float("nan")}]}, None),
                                ({}, {"1": {"start": float("nan")}})]:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                replan(report(), settings, edits)

    def test_manual_pin_over_user_protection_requires_review(self):
        output = replan(report([]), {"pins": {"1": [.5, .88]}, "regions": [{"rect": BOTTOM, "start": 0, "end": 12}]})
        self.assertTrue(output["plans"]["C"][0]["needs_review"])

    def test_clear_layout_prefers_readable_lines_without_a_tiny_final_fragment(self):
        source = report([])
        source["cues"][0]["original"] = "这里的LoRA参数面板中途换位，字幕也要避开正在讲的区域。"
        placement = replan(source)["plans"]["C"][0]
        self.assertGreaterEqual(len(placement["text"].splitlines()[-1]), 5)
        pinned = replan(source, {"pins": {"1": [.5, .15]}})["plans"]["C"][0]
        self.assertGreaterEqual(len(pinned["text"].splitlines()[-1]), 5)


if __name__ == "__main__":
    unittest.main()
