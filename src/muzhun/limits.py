"""Shared limits for the CLI, uploads, decoders, and browser capabilities."""
MAX_DURATION = 2 * 60 * 60
MAX_VIDEO_BYTES = 2 * 1024 ** 3
MAX_AUDIO_BYTES = 512 * 1024 ** 2
MAX_TEXT_BYTES = 2 * 1024 ** 2
MAX_TEXT_CHARS = 200_000
MAX_LYRIC_LINES = 3_000
LANGUAGES = {"auto", "zh", "en", "ja", "ko", "es", "fr", "de", "ru"}


def capabilities():
    return {"max_duration": MAX_DURATION, "max_video_bytes": MAX_VIDEO_BYTES,
            "max_audio_bytes": MAX_AUDIO_BYTES, "max_text_bytes": MAX_TEXT_BYTES,
            "max_lyric_lines": MAX_LYRIC_LINES}
