import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from muzhun.cli import main
from muzhun.delivery import review_manifest
from muzhun.editing import (HISTORY_LIMIT, StaleRevision, mark_review, replacement_preview,
                            replace_result, revise_result, travel_history)
from muzhun.media import read_json, write_json
from muzhun.pipeline import replan, save_exports
from muzhun.server import create_app
from test_v02 import report
from test_v03 import report as moving_report


def neutral_report():
    source = report()
    source["cues"] = [{"id": 1, "start": 0, "end": 3, "original": "使用 LoRA。"},
                      {"id": 2, "start": 4, "end": 7, "original": "再检查 LoRA 的版本。"}]
    return replan(source)


class EditingTests(unittest.TestCase):
    def test_preview_is_non_mutating_and_scoped(self):
        source = neutral_report()
        before = copy.deepcopy(source)
        preview = replacement_preview(source, {"find": "LoRA", "replace": "QLoRA", "ids": [2]})
        self.assertEqual(source, before)
        self.assertEqual((preview["cues"], preview["occurrences"]), (1, 1))
        self.assertEqual(preview["matches"][0]["id"], 2)

    def test_identifier_boundaries_and_case_options(self):
        source = replan(neutral_report(), edits={"1": {"text": "LoRA LoRA2 my_LoRA LoRAX lora"}})
        preview = replacement_preview(source, {"find": "LoRA", "replace": "QLoRA"})
        self.assertEqual(preview["matches"][0]["after"], "QLoRA LoRA2 my_LoRA LoRAX lora")
        insensitive = replacement_preview(source, {"find": "LoRA", "replace": "QLoRA", "case_sensitive": False})
        self.assertEqual(insensitive["matches"][0]["count"], 2)
        substring = replacement_preview(source, {"find": "LoRA", "replace": "X", "whole_word": False})
        self.assertEqual(substring["matches"][0]["count"], 4)

    def test_regex_metacharacters_and_replacement_are_literal(self):
        source = replan(neutral_report(), edits={"1": {"text": "函数 a.b 和 aXb"}})
        preview = replacement_preview(source, {"find": "a.b", "replace": r"C:\\new\1"})
        self.assertEqual(preview["matches"][0]["after"], r"函数 C:\\new\1 和 aXb")

    def test_chinese_aliases_and_multiple_occurrences(self):
        source = replan(neutral_report(), edits={"1": {"text": "罗拉参数和罗拉权重"}})
        preview = replacement_preview(source, {"find": "罗拉", "replace": "LoRA", "ids": [1]})
        self.assertEqual(preview["occurrences"], 2)
        self.assertEqual(preview["matches"][0]["after"], "LoRA参数和LoRA权重")

    def test_invalid_ids_flags_and_empty_output_do_not_apply(self):
        source = neutral_report()
        for payload in ({"find": " ", "replace": "x"}, {"find": "LoRA", "replace": "x", "ids": [99]},
                        {"find": "LoRA", "replace": "x", "case_sensitive": "false"},
                        {"find": source["cues"][0]["text"], "replace": "", "ids": [1]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                replace_result(source, payload)
        self.assertEqual(source["revision"], 0)

    def test_preview_limit_reports_hidden_matches(self):
        source = neutral_report()
        preview = replacement_preview(source, {"find": "LoRA", "replace": "x"}, limit=1)
        self.assertEqual((preview["cues"], len(preview["matches"]), preview["omitted"]), (2, 1, 1))

    def test_batch_rebinds_terms_and_replans_footprint(self):
        source = replan(moving_report())
        self.assertTrue(source["cues"][0]["bindings"])
        changed = replace_result(source, {"find": "LoRA", "replace": "很长的人工字幕内容", "revision": 0})
        self.assertEqual(changed["cues"][0]["original"], source["cues"][0]["original"])
        self.assertFalse(changed["cues"][0]["bindings"])
        self.assertNotEqual(changed["plans"]["C"], source["plans"]["C"])
        self.assertEqual(changed["revision"], 1)

    def test_review_is_manual_and_pending_must_be_resolved(self):
        source = replan(report(), {"profile": "ai-code"})
        self.assertGreater(source["cues"][0]["pending"], 0)
        with self.assertRaisesRegex(ValueError, "待确认纠词"):
            mark_review(source, {"ids": [1]})
        key = source["cues"][0]["proposals"][0]["key"]
        resolved = revise_result(source, {"edits": {"1": {"decisions": {key: "rejected"}}}})
        self.assertFalse(resolved["cues"][0]["reviewed"])
        self.assertTrue(mark_review(resolved, {"ids": [1]})["cues"][0]["reviewed"])

    def test_review_only_does_not_replan_or_run_recognition(self):
        with patch("muzhun.pipeline.replan", side_effect=AssertionError("unnecessary planning")):
            marked = mark_review(neutral_report_cached, {"ids": [1]})
        self.assertEqual(marked["summary"]["reviewed"], 1)

    def test_changing_one_cue_invalidates_only_its_review(self):
        source = mark_review(neutral_report(), {"ids": [1, 2]})
        changed = replace_result(source, {"find": "LoRA", "replace": "QLoRA", "ids": [1]})
        self.assertEqual([c["reviewed"] for c in changed["cues"]], [False, True])
        self.assertEqual(changed["summary"]["reviewed"], 1)

    def test_time_pin_and_font_changes_invalidate_review(self):
        source = mark_review(neutral_report(), {"ids": [1, 2]})
        for payload in ({"edits": {"1": {"start": .3, "end": 2.9}}},
                        {"settings": {"pins": {"1": [.5, .15]}}},
                        {"settings": {"font_scale": 1.3}}):
            with self.subTest(payload=payload):
                self.assertFalse(revise_result(source, payload)["cues"][0]["reviewed"])

    def test_undo_redo_restore_text_layout_and_exact_review(self):
        source = mark_review(neutral_report(), {"ids": [1]})
        changed = revise_result(source, {"settings": {"pins": {"1": [.4, .2]}}, "edits": {"1": {"text": "人工校正", "start": .2, "end": 2.8}}})
        undone = travel_history(changed, {"action": "undo", "revision": changed["revision"]})
        self.assertEqual(undone["plans"], source["plans"])
        self.assertTrue(undone["cues"][0]["reviewed"])
        redone = travel_history(undone, {"action": "redo", "revision": undone["revision"]})
        self.assertEqual(redone["plans"], changed["plans"])
        self.assertFalse(redone["cues"][0]["reviewed"])
        self.assertGreater(redone["revision"], undone["revision"])

    def test_new_edit_after_undo_clears_redo_and_history_is_bounded(self):
        source = neutral_report()
        for index in range(HISTORY_LIMIT + 3):
            source = revise_result(source, {"edits": {"1": {"text": f"人工修改 {index}"}}})
        self.assertEqual(source["history"]["undo"], HISTORY_LIMIT)
        undone = travel_history(source, {"action": "undo"})
        self.assertEqual(undone["history"]["redo"], 1)
        changed = revise_result(undone, {"edits": {"1": {"text": "另一种修改"}}})
        self.assertEqual(changed["history"]["redo"], 0)
        self.assertTrue(all(set(s) == {"label", "settings", "edits", "review_marks"} for s in changed["edit_history"]["undo"]))

    def test_noop_does_not_consume_history(self):
        source = neutral_report()
        same = revise_result(source, {})
        self.assertEqual(same["revision"], 0)
        self.assertEqual(same["history"]["undo"], 0)
        self.assertEqual(replace_result(source, {"find": "absent", "replace": "x"})["revision"], 0)

    def test_all_mutations_reject_stale_or_invalid_revision(self):
        source = revise_result(neutral_report(), {"edits": {"1": {"text": "更新"}}})
        for operation, payload in ((revise_result, {}), (mark_review, {"ids": [1]}),
                                   (replacement_preview, {"find": "更新", "replace": "旧内容"}),
                                   (replace_result, {"find": "更新", "replace": "旧内容"}),
                                   (travel_history, {"action": "undo"})):
            with self.subTest(operation=operation.__name__), self.assertRaises(StaleRevision):
                operation(source, {**payload, "revision": 0})

    def test_json_reload_retains_history_and_review(self):
        source = mark_review(neutral_report(), {"ids": [1]})
        changed = replace_result(source, {"find": "LoRA", "replace": "QLoRA"})
        restored = travel_history(json.loads(json.dumps(changed)), {"action": "undo"})
        self.assertTrue(restored["cues"][0]["reviewed"])
        self.assertEqual(restored["cues"][0]["text"], source["cues"][0]["text"])

    def test_delivery_records_human_review_separately_from_quality(self):
        source = mark_review(neutral_report(), {"ids": [1]})
        manifest = review_manifest(source, "C")
        self.assertEqual(manifest["summary"]["human_reviewed"], 1)
        self.assertEqual(manifest["status"], "draft-needs-listening-review")
        self.assertEqual(review_manifest(source, "A")["summary"]["human_reviewed"], 0)


neutral_report_cached = neutral_report()


class EditingAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.job = "1234567890abcdef"
        self.folder = self.root / "outputs" / self.job
        self.folder.mkdir(parents=True)
        self.source = neutral_report()
        self.source["source_video"] = str(self.folder / "source.mp4")
        self.source["metadata"]["filename"] = "source.mp4"
        save_exports(self.source, self.folder)
        write_json(self.folder / "state.json", {"id": self.job, "name": "example.mp4", "status": "ready", "progress": 1})
        self.client = TestClient(create_app(self.root))
        self.headers = {"X-Muzhun-Token": self.client.get("/api/status").json()["token"]}
        self.url = f"/api/jobs/{self.job}"

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def post(self, action, payload):
        return self.client.post(self.url + "/" + action, headers=self.headers, json=payload)

    def test_two_pages_cannot_silently_overwrite_each_other(self):
        self.assertEqual(self.post("revise", {"revision": 0, "edits": {"1": {"text": "先保存的内容"}}}).status_code, 200)
        stale = self.post("replace", {"revision": 0, "find": "LoRA", "replace": "x"})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.client.get(self.url).json()["result"]["cues"][0]["text"], "先保存的内容")

    def test_history_and_review_survive_new_app_instance(self):
        self.post("review", {"revision": 0, "ids": [1]})
        self.post("replace", {"revision": 1, "find": "LoRA", "replace": "QLoRA"})
        with TestClient(create_app(self.root)) as second:
            token = second.get("/api/status").json()["token"]
            response = second.post(self.url + "/history", headers={"X-Muzhun-Token": token}, json={"revision": 2, "action": "undo"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["cues"][0]["reviewed"])

    def test_review_only_keeps_subtitle_files_unchanged(self):
        path = self.folder / "subtitles-C.ass"
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        self.assertEqual(self.post("review", {"ids": [1], "revision": 0}).status_code, 200)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_preview_cannot_write_and_requires_page_token(self):
        path = self.folder / "result.json"
        before = path.read_bytes()
        payload = {"find": "LoRA", "replace": "QLoRA", "revision": 0}
        self.assertEqual(self.client.post(self.url + "/replace-preview", json=payload).status_code, 403)
        self.assertEqual(self.post("replace-preview", payload).json()["cues"], 2)
        self.assertEqual(path.read_bytes(), before)

    def test_export_reserves_edition_before_worker_and_invalidates_on_edit(self):
        def burn(_video, _ass, target, _progress):
            target.write_bytes(b"rendered-placeholder")
        with patch("muzhun.server.ThreadPoolExecutor.submit") as submit:
            response = self.post("export", {"mode": "C", "revision": 0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.post("review", {"ids": [1], "revision": 0}).status_code, 409)
        with patch("muzhun.server.burn_video", side_effect=burn):
            submit.call_args.args[0]()
        exported = self.client.get(self.url).json()
        self.assertEqual(exported["status"], "ready")
        self.assertEqual(exported["export_revision"], 0)
        self.assertTrue(exported["export_url"].endswith("video-C-r0.mp4"))
        self.post("revise", {"edits": {"1": {"text": "新字幕"}}, "revision": 0})
        self.assertIsNone(self.client.get(self.url).json()["export_url"])

    def test_export_failure_never_leaves_job_stuck(self):
        source = json.loads((self.folder / "result.json").read_text("utf-8"))
        del source["source_video"]
        write_json(self.folder / "result.json", source)
        with patch("muzhun.server.ThreadPoolExecutor.submit") as submit:
            self.assertEqual(self.post("export", {"mode": "C", "revision": 0}).status_code, 200)
        submit.call_args.args[0]()
        current = self.client.get(self.url).json()
        self.assertEqual(current["status"], "ready")
        self.assertIn("导出失败", current["message"])
        self.assertIsNone(current["export_url"])

    def test_missing_report_does_not_reserve_export(self):
        (self.folder / "result.json").unlink()
        self.assertEqual(self.post("export", {"mode": "C", "revision": 0}).status_code, 409)
        self.assertEqual(self.client.get(self.url).json()["status"], "ready")


class SkillEditingCLITests(unittest.TestCase):
    def test_preview_apply_review_undo_redo_through_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            save_exports(neutral_report(), folder)
            path = folder / "result.json"
            before = path.read_bytes()
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["replace", str(path), "--find", "LoRA", "--replace", "QLoRA"]), 0)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(main(["replace", str(path), "--find", "LoRA", "--replace", "QLoRA", "--apply", "--revision", "0"]), 0)
                self.assertEqual(main(["review", str(path), "--ids", "1", "--revision", "1"]), 0)
                self.assertEqual(main(["undo", str(path), "--revision", "2"]), 0)
                self.assertFalse(json.loads(path.read_text("utf-8"))["cues"][0]["reviewed"])
                self.assertEqual(main(["redo", str(path), "--revision", "3"]), 0)
                self.assertTrue(json.loads(path.read_text("utf-8"))["cues"][0]["reviewed"])
                self.assertEqual(main(["undo", str(path), "--revision", "0"]), 1)


class AtomicSaveTests(unittest.TestCase):
    def test_read_retries_a_windows_file_replacement_in_progress(self):
        error = PermissionError("replacement in progress")
        error.winerror = 32
        with patch("muzhun.media.Path.read_text", side_effect=[error, '{"revision": 3}']) as read, patch("muzhun.media.time.sleep"):
            self.assertEqual(read_json(Path("result.json")), {"revision": 3})
            self.assertEqual(read.call_count, 2)

    def test_temporary_windows_sharing_error_retries_without_partial_report(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "result.json"
            write_json(target, {"revision": 1})
            real_replace = Path.replace
            attempts = []
            def replace(temporary, destination):
                attempts.append(temporary)
                if len(attempts) <= 2:
                    self.assertEqual(json.loads(target.read_text("utf-8"))["revision"], 1)
                    error = PermissionError("reader holds file")
                    error.winerror = 32
                    raise error
                return real_replace(temporary, destination)
            with patch("muzhun.media.Path.replace", new=replace), patch("muzhun.media.time.sleep"):
                write_json(target, {"revision": 2})
            self.assertEqual(len(attempts), 3)
            self.assertEqual(json.loads(target.read_text("utf-8"))["revision"], 2)
            self.assertFalse(list(Path(temp).glob("*.tmp")))

    def test_persistent_failure_keeps_old_report_and_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "result.json"
            write_json(target, {"revision": 1})
            before = target.read_bytes()
            error = PermissionError("persistent denial")
            error.winerror = 5
            with patch("muzhun.media.Path.replace", side_effect=error) as replace, patch("muzhun.media.time.sleep"):
                with self.assertRaises(PermissionError):
                    write_json(target, {"revision": 2})
                self.assertEqual(replace.call_count, 6)
            self.assertEqual(target.read_bytes(), before)
            self.assertFalse(list(Path(temp).glob("*.tmp")))

    def test_other_permission_errors_are_not_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("muzhun.media.Path.replace", side_effect=PermissionError("not a sharing error")) as replace:
                with self.assertRaises(PermissionError):
                    write_json(Path(temp) / "result.json", {"revision": 2})
            self.assertEqual(replace.call_count, 1)


if __name__ == "__main__":
    unittest.main()
