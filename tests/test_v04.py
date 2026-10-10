import importlib.util
import json
import os
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from muzhun import __version__
from muzhun.diagnostics import cached_models, runtime_report
from muzhun.server import create_app
from muzhun.startup import bind_port, open_when_ready

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseReadinessTests(unittest.TestCase):
    def test_dependency_change_reinstalls_an_existing_environment(self):
        launcher = load_script("launch")
        import hashlib
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            configuration = b'version = "0.4.0"\n'
            (root / "pyproject.toml").write_bytes(configuration)
            python = launcher.environment_python(root)
            python.parent.mkdir(parents=True)
            python.touch()
            marker = root / ".venv" / "muzhun-install.json"
            marker.write_text(json.dumps({"root": str(root), "fingerprint": hashlib.sha256(configuration).hexdigest()}))
            completed = subprocess.CompletedProcess([], 0)
            with patch.object(launcher, "run", return_value=completed) as command:
                launcher.install(root)
                self.assertEqual(command.call_count, 1)
            (root / "pyproject.toml").write_bytes(configuration + b'dependencies = ["new-runtime-dependency"]\n')
            with patch.object(launcher, "run", return_value=completed) as command:
                launcher.install(root)
                self.assertTrue(any("pip" in call.args[0] for call in command.call_args_list))

    def test_explicit_engine_location_overrides_an_old_skill_record(self):
        spec = importlib.util.spec_from_file_location("skill_launcher", ROOT / "skills/muzhun-subtitles/scripts/run.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            python = root / ".venv/Scripts/python.exe"
            python.parent.mkdir(parents=True)
            python.touch()
            (root / "src/muzhun").mkdir(parents=True)
            with patch.dict(os.environ, {"MUZHUN_HOME": str(root)}):
                # Windows may spell the temp directory with an 8.3 alias;
                # the launcher deliberately returns resolved absolute paths.
                self.assertEqual(launcher.find_runtime(), (python.resolve(), root.resolve()))

    def test_reserved_port_is_not_reused_and_selected_port_stays_bound(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            with bind_port(port) as selected:
                self.assertNotEqual(selected.getsockname()[1], port)
                with socket.socket() as other:
                    with self.assertRaises(OSError):
                        other.bind(selected.getsockname())

    def test_invalid_port_has_a_clear_error(self):
        for port in (0, -1, 65536):
            with self.assertRaises(ValueError):
                bind_port(port)

    def test_partial_model_download_is_not_reported_cached(self):
        with tempfile.TemporaryDirectory() as name:
            cache = Path(name)
            snapshot = cache / "models--Systran--faster-whisper-small" / "snapshots" / "abc"
            snapshot.mkdir(parents=True)
            (snapshot / "model.bin").write_bytes(b"model")
            self.assertEqual(cached_models(cache), [])
            for file in ("config.json", "tokenizer.json"):
                (snapshot / file).write_text("{}", "utf-8")
            self.assertEqual(cached_models(cache), ["small"])

    def test_font_failure_does_not_hide_other_checks_or_download_models(self):
        with tempfile.TemporaryDirectory() as name, patch("muzhun.layout.font_path", side_effect=RuntimeError("missing font")), patch("muzhun.media.whisper_model") as model:
            report = runtime_report(Path(name))
        self.assertFalse(report["ready"])
        self.assertEqual(next(item for item in report["checks"] if item["id"] == "font")["message"], "missing font")
        self.assertTrue(any(item["id"] == "output" for item in report["checks"]))
        model.assert_not_called()

    def test_turbo_cache_uses_its_actual_model_repository(self):
        with tempfile.TemporaryDirectory() as name:
            cache = Path(name)
            snapshot = cache / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/snapshots/abc"
            snapshot.mkdir(parents=True)
            for file in ("model.bin", "config.json", "tokenizer.json"):
                (snapshot / file).write_bytes(b"present")
            self.assertEqual(cached_models(cache), ["large-v3-turbo"])

    def test_health_is_lightweight_and_diagnostics_are_actionable(self):
        with tempfile.TemporaryDirectory() as name:
            with TestClient(create_app(Path(name))) as client:
                with patch("muzhun.diagnostics.runtime_report", return_value={"ready": False, "checks": [{"id": "font", "hint": "install font"}]}) as report:
                    self.assertEqual(client.get("/api/health").json(), {"app": "muzhun", "version": __version__})
                    report.assert_not_called()
                    self.assertFalse(client.get("/api/doctor").json()["ready"])

    def test_browser_does_not_open_on_another_apps_health_response(self):
        from io import BytesIO
        class Opener:
            def open(self, url, timeout):
                return BytesIO(json.dumps({"app": "other", "version": __version__}).encode())
        with patch("muzhun.startup.urllib.request.build_opener", return_value=Opener()), patch("muzhun.startup.webbrowser.open") as browser:
            open_when_ready("http://127.0.0.1:8770", timeout=0.01)
            browser.assert_not_called()

    def test_browser_opens_only_after_this_version_is_ready(self):
        from io import BytesIO
        class Opener:
            def open(self, url, timeout):
                self.url = url
                return BytesIO(json.dumps({"app": "muzhun", "version": __version__}).encode())
        opener = Opener()
        with patch("muzhun.startup.urllib.request.build_opener", return_value=opener), patch("muzhun.startup.webbrowser.open") as browser:
            open_when_ready("http://127.0.0.1:8771", timeout=1)
            self.assertEqual(opener.url, "http://127.0.0.1:8771/api/health")
            browser.assert_called_once_with("http://127.0.0.1:8771")

    def test_skill_installer_keeps_user_files_and_refreshes_runtime_record(self):
        installer = load_script("install_skill")
        with tempfile.TemporaryDirectory() as name:
            destination = Path(name) / "skills" / "muzhun-subtitles"
            installer.install(destination)
            custom = destination / "my-note.txt"
            custom.write_text("keep", "utf-8")
            with self.assertRaises(FileExistsError):
                installer.install(destination)
            installer.install(destination, update=True)
            self.assertEqual(custom.read_text("utf-8"), "keep")
            record = json.loads((destination / "references" / "runtime.json").read_text("utf-8"))
            self.assertEqual(record["version"], __version__)
            script = subprocess.run([record["python"], str(destination / "scripts" / "run.py"), "--help"], capture_output=True)
            self.assertEqual(script.returncode, 0, script.stderr.decode("utf-8", "replace"))

    def test_skill_installer_refuses_an_unrelated_destination(self):
        installer = load_script("install_skill")
        with tempfile.TemporaryDirectory() as name:
            destination = Path(name)
            (destination / "SKILL.md").write_text("name: unrelated", "utf-8")
            with self.assertRaises(ValueError):
                installer.install(destination, update=True)
            self.assertEqual((destination / "SKILL.md").read_text("utf-8"), "name: unrelated")


if __name__ == "__main__":
    unittest.main()
