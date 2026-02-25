"""
TTS Agent — Converts anchor scripts to broadcast-quality audio via ElevenLabs.

Strips markup tags from scripts before sending to TTS.
Uses locked voice profiles for anchor consistency.
"""

import re
import os
import tempfile
from pathlib import Path


def generate_audio(script_data, config):
    """
    Convert script text to audio via ElevenLabs API.

    Returns a dict with:
        - audio_path: path to the generated .mp3 file
        - actual_duration_seconds: measured duration of the audio
    """
    from elevenlabs import ElevenLabs

    api_key = config["apis"]["elevenlabs_key"]

    # Find the matching anchor's voice ID
    anchor_name = script_data["anchor"]
    voice_id = None
    for anchor_cfg in config.get("anchors", []):
        if anchor_cfg["name"] == anchor_name:
            voice_id = anchor_cfg.get("elevenlabs_voice_id")
            break

    if not voice_id or voice_id == "PASTE_VOICE_ID_HERE":
        print(f"  WARNING: No voice ID configured for {anchor_name}. Using default.")
        # Fall back to first available voice or a known default
        voice_id = "21m00Tcm4TlvDq8ikWAM"  # ElevenLabs "Rachel" default

    # Strip [CHYRON: ...] and [B-ROLL: ...] tags from script
    clean_script = _strip_tags(script_data["script"])

    # Generate audio via ElevenLabs
    client = ElevenLabs(api_key=api_key)

    # Create a temp file for the audio
    output_dir = Path(tempfile.gettempdir()) / "tnn_audio"
    output_dir.mkdir(exist_ok=True)
    audio_path = output_dir / f"{script_data['story_id']}.mp3"

    audio_generator = client.text_to_speech.convert(
        voice_id=voice_id,
        text=clean_script,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
        voice_settings={
            "stability": 0.7,
            "similarity_boost": 0.8,
            "style": 0.1,
            "use_speaker_boost": True,
        },
    )

    # Write audio bytes to file
    with open(audio_path, "wb") as f:
        for chunk in audio_generator:
            f.write(chunk)

    # Measure actual duration using ffprobe
    actual_duration = _measure_duration(str(audio_path))

    print(f"  Audio generated: {audio_path.name} ({actual_duration:.1f}s)")

    return {
        "audio_path": str(audio_path),
        "actual_duration_seconds": actual_duration,
    }


def _strip_tags(script_text):
    """Remove [CHYRON: ...] and [B-ROLL: ...] tags, leaving just spoken text."""
    cleaned = re.sub(r'\[CHYRON:\s*[^\]]+\]', '', script_text)
    cleaned = re.sub(r'\[B-ROLL:\s*[^\]]+\]', '', cleaned)
    # Clean up extra whitespace
    cleaned = re.sub(r'\n\s*\n', '\n\n', cleaned)
    return cleaned.strip()


def _measure_duration(audio_path):
    """Use ffprobe to measure audio duration in seconds."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    except (ValueError, FileNotFoundError):
        print("  WARNING: ffprobe not available, estimating duration from file size")
        # Rough estimate: 128kbps MP3 ≈ 16KB per second
        file_size = os.path.getsize(audio_path)
        return file_size / 16000
