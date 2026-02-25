"""
TTS Agent — Converts anchor scripts to broadcast-quality audio via ElevenLabs.

Supports:
- Single-voice generation for individual stories
- Multi-voice generation for hourly summaries (alternating anchors)
"""

import re
import os
import subprocess
import tempfile
from pathlib import Path


def generate_audio(script_data, config):
    """
    Convert a single-anchor script to audio.

    Returns a dict with:
        - audio_path: path to the generated .mp3 file
        - actual_duration_seconds: measured duration
    """
    from elevenlabs import ElevenLabs

    api_key = config["apis"]["elevenlabs_key"]
    anchor_name = script_data["anchor"]
    voice_id = _get_voice_id(anchor_name, config)
    clean_script = _strip_tags(script_data["script"])

    client = ElevenLabs(api_key=api_key)

    output_dir = Path(tempfile.gettempdir()) / "tnn_audio"
    output_dir.mkdir(exist_ok=True)
    audio_path = output_dir / f"{script_data['story_id']}.mp3"

    _generate_tts_file(client, voice_id, clean_script, str(audio_path))
    actual_duration = _measure_duration(str(audio_path))

    print(f"  Audio generated: {audio_path.name} ({actual_duration:.1f}s)")

    return {
        "audio_path": str(audio_path),
        "actual_duration_seconds": actual_duration,
    }


def generate_hourly_audio(summary_data, config):
    """
    Generate multi-voice audio for an hourly summary.

    Takes the parsed segments (each with an anchor name and text),
    generates TTS for each segment with the correct voice,
    then concatenates them with ffmpeg.

    Returns a dict with:
        - audio_path: path to the final concatenated .mp3
        - actual_duration_seconds: total duration
        - segment_count: number of TTS segments generated
    """
    from elevenlabs import ElevenLabs

    api_key = config["apis"]["elevenlabs_key"]
    segments = summary_data.get("segments", [])
    story_id = summary_data.get("story_id", "hourly")

    if not segments:
        return None

    client = ElevenLabs(api_key=api_key)

    output_dir = Path(tempfile.gettempdir()) / "tnn_audio"
    output_dir.mkdir(exist_ok=True)

    # Generate each segment as a separate audio file
    segment_paths = []
    for i, seg in enumerate(segments):
        anchor_name = seg["anchor"]
        text = seg["text"]
        voice_id = _get_voice_id(anchor_name, config)

        seg_path = output_dir / f"{story_id}_seg{i:02d}.mp3"
        print(f"  TTS segment {i+1}/{len(segments)}: {anchor_name} ({len(text.split())}w)")
        _generate_tts_file(client, voice_id, text, str(seg_path))
        segment_paths.append(str(seg_path))

    # Concatenate all segments with ffmpeg
    final_path = output_dir / f"{story_id}.mp3"
    _concat_audio(segment_paths, str(final_path))

    # Clean up segment files
    for p in segment_paths:
        try:
            os.remove(p)
        except OSError:
            pass

    actual_duration = _measure_duration(str(final_path))
    print(f"  Hourly audio assembled: {final_path.name} ({actual_duration:.1f}s, {len(segments)} segments)")

    return {
        "audio_path": str(final_path),
        "actual_duration_seconds": actual_duration,
        "segment_count": len(segments),
    }


def _get_voice_id(anchor_name, config):
    """Look up the ElevenLabs voice ID for an anchor."""
    for anchor_cfg in config.get("anchors", []):
        if anchor_cfg["name"] == anchor_name:
            vid = anchor_cfg.get("elevenlabs_voice_id")
            if vid and vid != "PASTE_VOICE_ID_HERE":
                return vid
    # Fallback
    print(f"  WARNING: No voice ID for {anchor_name}, using default")
    return "21m00Tcm4TlvDq8ikWAM"


def _generate_tts_file(client, voice_id, text, output_path):
    """Generate a single TTS audio file."""
    audio_generator = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
        voice_settings={
            "stability": 0.7,
            "similarity_boost": 0.8,
            "style": 0.1,
            "use_speaker_boost": True,
        },
    )

    with open(output_path, "wb") as f:
        for chunk in audio_generator:
            f.write(chunk)


def _concat_audio(segment_paths, output_path):
    """Concatenate multiple MP3 files using ffmpeg."""
    if len(segment_paths) == 1:
        # Just copy if only one segment
        import shutil
        shutil.copy2(segment_paths[0], output_path)
        return

    # Build ffmpeg concat file
    concat_dir = Path(tempfile.gettempdir()) / "tnn_audio"
    concat_list = concat_dir / "concat_list.txt"

    with open(concat_list, "w") as f:
        for p in segment_paths:
            f.write(f"file '{p}'\n")

    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            output_path,
        ],
        capture_output=True,
        text=True,
    )

    # Clean up concat list
    try:
        concat_list.unlink()
    except OSError:
        pass

    if result.returncode != 0:
        print(f"  WARNING: ffmpeg concat error: {result.stderr[-200:]}")


def _strip_tags(script_text):
    """Remove [CHYRON: ...], [B-ROLL: ...] tags and markdown, leaving spoken text."""
    cleaned = re.sub(r'\[CHYRON:\s*[^\]]+\]', '', script_text)
    cleaned = re.sub(r'\[B-ROLL:\s*[^\]]+\]', '', cleaned)
    cleaned = re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'\*([^*]+)\*', r'\1', cleaned)
    cleaned = re.sub(r'^#+\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^[-*]\s+', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^[A-Z][A-Za-z\s]+:\s*', '', cleaned)
    cleaned = re.sub(r'\n\s*\n', '\n\n', cleaned)
    return cleaned.strip()


def _measure_duration(audio_path):
    """Use ffprobe to measure audio duration in seconds."""
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
        print("  WARNING: ffprobe not available, estimating duration")
        file_size = os.path.getsize(audio_path)
        return file_size / 16000
