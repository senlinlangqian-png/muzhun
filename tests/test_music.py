"""Regression coverage for dialogue hiding later music vocals (no private media)."""
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import numpy as np
from fastapi.testclient import TestClient

from muzhun.lyrics import recognition_issues
from muzhun.pipeline import settings_check
from muzhun.server import create_app
from muzhun.transcription import recognize, recover_uncovered, speech_cues, uncovered_intervals


def segment(text, start, end, probability=.9, logprob=-.3):
    return NS(words=[NS(word=text, start=start, end=end, probability=probability)],
              text=text, start=start, end=end, avg_logprob=logprob, no_speech_prob=.2)


def write_audio(path, duration=5, silent=False):
    signal = np.zeros(round(16000 * duration), np.int16) if silent else (
        np.sin(np.arange(round(16000 * duration)) * .1) * 3000).astype(np.int16)
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(signal.tobytes())


class MusicRecoveryTests(unittest.TestCase):
    def test_gaps_merge_overlapping_anchors_and_keep_leading_and_trailing_gaps(self):
        words = [{"start": 2, "end": 3}, {"start": 2.5, "end": 4}, {"start": 4.2, "end": 5}]
        self.assertEqual(list(uncovered_intervals(0, 8, words)), [(0, 2), (5, 8)])

    def test_recovery_offsets_multilingual_words_and_does_not_complete_sequences(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); path = root / "audio.wav"; write_audio(path)
            calls = []
            def transcribe(samples, **options):
                calls.append(options)
                if len(calls) == 1:
                    return iter([segment("对白", 0, 1)]), NS(language="zh", language_probability=.99)
                if options["language"] is None:
                    return iter([segment("wrong", .2, 1, .2, -1.5)]), NS(
                        language="zh", all_language_probs=[("zh", .6), ("en", .3)])
                # Intentionally non-consecutive numbers: no inferred missing number.
                return iter([segment(" 2,", .4, .9), segment(" 5", 1.1, 1.5)]), NS(language="en")
            factory = lambda *_: NS(transcribe=transcribe)
            words, cues, info = recognize(path, "small", root, lambda *_: None, singing=True,
                                          recover_gaps=True, engine_factory=factory)
            self.assertEqual([w["word"] for w in words], ["对白", " 2,", " 5"])
            self.assertEqual([(w["start"], w["end"]) for w in words[1:]], [(1.4, 1.9), (2.1, 2.5)])
            self.assertEqual(info["recovered_words"], 2)
            self.assertEqual(info["recovery"][0]["candidate_languages"], ["zh", "en"])
            rows = speech_cues(words, cues, 5)
            self.assertEqual(len(rows), 2)
            self.assertFalse(rows[0]["recognition_review"])
            self.assertTrue(rows[1]["background_recovered"])
            self.assertTrue(rows[1]["recognition_review"])
            self.assertTrue(all(not c["vad_filter"] for c in calls))
            with patch("muzhun.media.whisper_model", side_effect=AssertionError("reuse completed recovery")):
                cached_words, _, cached = recognize(path, "small", root, lambda *_: None,
                                                   singing=True, recover_gaps=True)
            self.assertEqual(cached_words, words)
            self.assertEqual(cached["cached_chunks"], 1)
            self.assertEqual(cached["recovery"], info["recovery"])

    def test_near_silence_does_not_decode_or_generate_words(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "audio.wav"; write_audio(path, silent=True)
            record = {"words": [], "cues": []}
            transcribe = Mock(side_effect=AssertionError("silence must not be decoded"))
            recover_uncovered(NS(transcribe=transcribe), path, 0, 5, record, None, lambda *_: None)
            transcribe.assert_not_called()
            self.assertEqual(record["words"], [])

    def test_explicit_language_is_respected_and_zero_length_edge_guesses_are_dropped(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "audio.wav"; write_audio(path)
            seen = []
            def transcribe(_, **options):
                seen.append(options["language"])
                return iter([segment(" lyric", .2, .8), segment("extra", 1, 1)]), NS(language="en")
            record = {"words": [], "cues": []}
            recover_uncovered(NS(transcribe=transcribe), path, 0, 5, record, "en", lambda *_: None)
            self.assertEqual(seen, ["en"])
            self.assertEqual([w["word"] for w in record["words"]], [" lyric"])

    def test_unreliable_gap_transcript_is_not_added(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "audio.wav"; write_audio(path)
            engine = NS(transcribe=lambda *_a, **_k: (iter([segment("guessed", 0, 2, .15, -1.8)]), NS(language="en")))
            record = {"words": [], "cues": []}
            recover_uncovered(engine, path, 0, 5, record, "en", lambda *_: None)
            self.assertEqual(record["words"], [])

    def test_low_scoring_edge_word_in_a_supported_phrase_stays_flagged(self):
        words = [{"word": " first", "start": 1, "end": 1.4, "probability": .02, "background_recovered": True},
                 {"word": " second", "start": 1.5, "end": 1.9, "probability": .99, "background_recovered": True}]
        cue = speech_cues(words, [], 2)[0]
        self.assertTrue(cue["recognition_review"])
        self.assertEqual(cue["original"], "first second")
        self.assertIn("补识别", recognition_issues({**cue, "text": cue["original"]}, "en")[0])

    def test_settings_and_api_reject_unknown_modes_before_processing(self):
        with self.assertRaises(ValueError):
            settings_check({"audio_content": "made-up"})
        with tempfile.TemporaryDirectory() as name, TestClient(create_app(Path(name))) as client:
            token = client.get("/api/status").json()["token"]
            response = client.post("/api/jobs", headers={"X-Muzhun-Token": token},
                data={"audio_content": "made-up"}, files={"video": ("clip.mp4", b"demo")})
            self.assertEqual(response.status_code, 400)

    def test_video_media_routes_mixed_to_unfiltered_gap_recognition(self):
        from muzhun.media import transcribe
        with patch("muzhun.transcription.decode_audio", return_value=2), patch(
            "muzhun.transcription.recognize", return_value=([], [{"text": "hello", "start": 0, "end": 1}], {})) as recognize_mock:
            transcribe(Path("clip.mp4"), {"has_audio": True, "duration": 2}, "small", Path("cache"),
                       lambda *_: None, Path("audio.wav"), content="mixed")
            self.assertTrue(recognize_mock.call_args.kwargs["singing"])
            self.assertTrue(recognize_mock.call_args.kwargs["recover_gaps"])

    def test_song_auto_transcript_exports_recovered_words_and_review_notes(self):
        from muzhun.lyrics import process_lyrics
        words = [{"word": " speech", "start": 0, "end": 1, "probability": .9},
                 {"word": " lyric", "start": 2, "end": 3, "probability": .9, "background_recovered": True}]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); path = root / "audio.wav"; write_audio(path)
            with patch("muzhun.lyrics.recognize_audio", return_value=(words,
                [{"text": "speech", "start": 0, "end": 1}], {"language": "en"})):
                result = process_lyrics(path, root / "out", "", "small", root, content="song")
            self.assertEqual([line["text"] for line in result["lines"]], ["speech", "lyric"])
            self.assertTrue(result["lines"][1]["issues"])
            self.assertIn("lyric", (root / "out/lyrics.lrc").read_text("utf-8"))
