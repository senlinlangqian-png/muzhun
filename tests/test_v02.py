import json
import os
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from muzhun.delivery import delivery_pack, review_manifest, template_page, verify_render
from muzhun.evaluation import blind_pack
from muzhun.layout import _cost, font_path
from muzhun.media import burn_video
from muzhun.pipeline import replan


def report():
    return {"version": "0.1.0", "metadata": {"width": 1280, "height": 720, "duration": 30, "has_audio": True},
            "asr": {"engine": "provided-srt", "model": None},
            "settings": {"profile": "general", "style": "professional", "font": "sans", "font_scale": 1, "glossary": "", "regions": [], "pins": {}},
            "frames": [], "cues": [{"id": 1, "start": 0, "end": 3, "original": "现在讲罗拉。"}],
            "edits": {}, "warnings": []}


class RevisionTests(unittest.TestCase):
    def test_legacy_decisions_follow_candidates_when_glossary_changes(self):
        source = report()
        source["cues"][0]["original"] = "阿尔法和贝塔"
        initial = replan(source, {"glossary": "Alpha=阿尔法\nBeta=贝塔"})
        changed = replan(initial, {"glossary": "Beta=贝塔"}, {"1": {"decisions": {"0": "rejected", "1": "accepted"}}})
        self.assertEqual(changed["cues"][0]["text"], "阿尔法和Beta")
        self.assertTrue(all(key.startswith("p-") for key in changed["edits"]["1"]["decisions"]))
        restored = replan(changed, {"glossary": "Alpha=阿尔法\nBeta=贝塔"})
        self.assertEqual(restored["cues"][0]["text"], "阿尔法和Beta")

    def test_clear_timing_override_restores_source_and_layout(self):
        source = replan(report(), edits={"1": {"start": 8, "end": 10}})
        reset = replan(source, edits={"1": {}})
        self.assertEqual((reset["cues"][0]["start"], reset["plans"]["C"][0]["start"]), (0, 0))

    def test_time_changes_reorder_sequence(self):
        source = report()
        source["cues"].append({"id": 2, "start": 4, "end": 6, "original": "第二句"})
        output = replan(source, edits={"1": {"start": 7, "end": 9}})
        self.assertEqual([c["id"] for c in output["cues"]], [2, 1])
        self.assertEqual([c["id"] for c in output["plans"]["C"]], [2, 1])

    def test_overlapping_single_track_is_rejected(self):
        source = report()
        source["cues"].append({"id": 2, "start": 2, "end": 6, "original": "第二句"})
        with self.assertRaisesRegex(ValueError, "不能重叠"):
            replan(source)

    def test_covering_small_title_has_cost_even_with_large_caption(self):
        candidate = {"rect": [.1, .1, .9, .5], "line_count": 2, "label": "上方"}
        title = {"rect": [.45, .15, .55, .18], "weight": 1.5}
        self.assertGreater(_cost(candidate, [title], [], "C"), 8)

    def test_manual_caption_covering_unmentioned_text_requires_review(self):
        source = report()
        source["frames"] = [{"time": 1, "image": "frames/0000.jpg", "ocr": [
            {"text": "操作说明", "confidence": .99, "rect": [.35, .82, .65, .9]}]}]
        result = replan(source, {"pins": {"1": [.5, .86]}})
        self.assertEqual(result["cues"][0]["bindings"], [])
        self.assertTrue(result["plans"]["C"][0]["needs_review"])


class DeliveryTests(unittest.TestCase):
    def test_custom_font_uses_real_family_and_reaches_renderer(self):
        default_file, _family = font_path()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"MUZHUN_FONT": default_file}):
            folder = Path(temp)
            font_path.cache_clear()
            try:
                self.assertNotEqual(font_path()[1], "Custom")
                with patch("muzhun.media.subprocess.run") as run:
                    run.return_value.returncode = 0
                    burn_video(folder / "source.mp4", folder / "subtitles.ass", folder / "video.mp4", lambda *_: None)
                    args = run.call_args.args[0]
                    self.assertEqual(args[args.index("-vf") + 1], "ass=subtitles.ass:fontsdir=fonts")
                    self.assertTrue((folder / "fonts" / ("custom" + Path(default_file).suffix.lower())).is_file())
            finally:
                font_path.cache_clear()

    def test_zero_pending_still_delivers_a_draft(self):
        source = report()
        source["cues"][0]["original"] = "普通字幕"
        manifest = review_manifest(replan(source), "C")
        self.assertEqual(manifest["summary"]["pending"], 0)
        self.assertEqual(manifest["status"], "draft-needs-listening-review")

    def test_template_treats_transcript_as_data(self):
        text = '</script><img src=x onerror="alert(1)">'
        page = template_page("delivery-review.html", {"text": text})
        payload = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S).group(1)
        self.assertNotIn("<img", payload)
        self.assertEqual(json.loads(payload)["text"], text)

    def test_render_verification_rejects_missing_audio_and_wrong_duration(self):
        source = report()["metadata"]
        for change in ({"has_audio": False}, {"duration": 31}, {"width": 720}):
            with self.assertRaises(ValueError):
                verify_render(source, {**source, **change})

    def test_delivery_zip_has_editable_subtitles_and_no_private_paths(self):
        source = report()
        source.update(source_video="C:/private/secret.mp4", demo=True)
        result = replan(source, {"profile": "ai-code"})
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            def burn(_video, _ass, target, _progress):
                target.write_bytes(b"actual-render-placeholder")
            with patch("muzhun.delivery.probe", return_value=source["metadata"]), patch(
                "muzhun.delivery.burn_video", side_effect=burn
            ), patch("muzhun.delivery.rendered_previews", return_value=[]):
                output = delivery_pack(result, folder, folder / "source.mp4")
            with zipfile.ZipFile(output["output"]) as archive:
                self.assertEqual(set(archive.namelist()), {"video.mp4", "subtitles.ass", "subtitles.srt", "review.html", "manifest.json"})
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["provenance"], "synthetic-demo")
                self.assertEqual(manifest["summary"]["pending"], 1)
                self.assertNotIn("C:/private", archive.read("manifest.json").decode("utf-8"))
                self.assertNotIn("source_video", manifest)

    def test_blind_page_batch_matches_key_and_contains_no_mapping(self):
        source = report()
        result = replan(source)
        result["edits"] = {"1": {"text": "人工修改"}}
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            def burn(_video, _ass, target, _progress):
                target.write_bytes(target.stem.encode("ascii"))
            with patch("muzhun.media.probe", return_value=source["metadata"]), patch(
                "muzhun.evaluation.burn_video", side_effect=burn
            ):
                output = blind_pack(result, folder, folder / "source.mp4")
            key = json.loads((folder / "blind-key.json").read_text("utf-8"))
            old_key_file = folder / "blind-keys" / f"{key['batch']}.json"
            old_page = folder / "friend-test" / key["batch"] / "index.html"
            self.assertEqual(json.loads(old_key_file.read_text("utf-8")), key)
            original_page = old_page.read_text("utf-8")
            with zipfile.ZipFile(output) as archive:
                self.assertNotIn("blind-key.json", archive.namelist())
                page = archive.read("index.html").decode("utf-8")
                payload = json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S).group(1))
                self.assertEqual(payload["batch"], key["batch"])
                self.assertTrue(payload["assisted"])
                self.assertTrue(key["assisted"])
                self.assertNotIn("mapping", page)
                self.assertNotIn("video-A", page)
                self.assertNotIn("video-B", page)
                self.assertNotIn("video-C", page)
                for clip in payload["clips"]:
                    self.assertEqual(archive.read(clip["file"]).decode("ascii"), "video-" + key["mapping"][clip["name"]])
            with patch("muzhun.media.probe", return_value=source["metadata"]), patch(
                "muzhun.evaluation.burn_video", side_effect=burn
            ):
                second = blind_pack(result, folder, folder / "source.mp4")
            self.assertNotEqual(output, second)
            self.assertTrue(output.is_file())
            self.assertEqual(json.loads(old_key_file.read_text("utf-8")), key)
            self.assertEqual(old_page.read_text("utf-8"), original_page)


if __name__ == "__main__":
    unittest.main()
