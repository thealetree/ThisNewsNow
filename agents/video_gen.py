"""
Video Generation Agent — Generates anchor videos via HeyGen API.

Produces 720p MP4 video of an anchor reading the hourly summary script.
The avatar's voice is linked to ElevenLabs in HeyGen, so we only send text.
"""

import re
import time
import requests
from pathlib import Path

# Polling configuration
POLL_INTERVAL_SECONDS = 15
MAX_POLL_ATTEMPTS = 80  # 80 * 15s = 20 minutes max wait


def generate_video(summary_data, config):
    """
    Generate an anchor video for an hourly summary via HeyGen.

    Args:
        summary_data: hourly summary dict with full_script, story_id, etc.
        config: channel config

    Returns a dict with:
        - video_path: path to the downloaded .mp4 file
        - story_id: story ID
    Or None if generation fails.
    """
    api_key = config.get("apis", {}).get("heygen_key")
    if not api_key:
        print("  WARNING: No heygen_key configured. Skipping video generation.")
        return None

    video_config = config.get("video", {})
    dimension = video_config.get("dimension", {"width": 1280, "height": 720})

    # Find the anchor with a HeyGen avatar
    avatar_id, anchor_name, voice_id = _find_heygen_anchor(config)
    if not avatar_id:
        print("  WARNING: No HeyGen avatar configured on any anchor. Skipping video.")
        return None
    if not voice_id:
        print("  WARNING: No heygen_voice_id configured for anchor. Skipping video.")
        return None

    # Clean the script for TTS (remove anchor tags, markdown, etc.)
    script_text = _clean_script_for_video(summary_data.get("full_script", ""))

    if not script_text:
        print("  WARNING: No script text for video generation.")
        return None

    # HeyGen has a 5000 character limit per scene
    if len(script_text) > 4900:
        print(f"  WARNING: Script too long ({len(script_text)} chars), truncating to 4900.")
        script_text = script_text[:4900]

    story_id = summary_data.get("story_id", "hourly")

    # Step 1: Submit video generation request
    video_id = _submit_video(api_key, avatar_id, script_text, dimension, voice_id)
    if not video_id:
        return None

    print(f"  HeyGen video submitted: {video_id} (polling for completion...)")

    # Step 2: Poll until complete
    video_url = _poll_video_status(api_key, video_id)
    if not video_url:
        return None

    # Step 3: Download the video
    output_dir = Path("docs") / "video"
    output_dir.mkdir(exist_ok=True)
    video_path = output_dir / f"{story_id}.mp4"

    if not _download_video(video_url, str(video_path)):
        return None

    file_size_mb = video_path.stat().st_size / (1024 * 1024)
    print(f"  Video downloaded: {video_path.name} ({file_size_mb:.1f} MB)")

    return {
        "video_path": str(video_path),
        "story_id": story_id,
    }


def _find_heygen_anchor(config):
    """Find the first anchor with a heygen_avatar_id configured.

    Returns (avatar_id, anchor_name, voice_id) where voice_id is the
    HeyGen voice ID (if set), or None.
    """
    for anchor in config.get("anchors", []):
        avatar_id = anchor.get("heygen_avatar_id")
        if avatar_id and avatar_id not in ("PASTE_AVATAR_LOOK_ID_HERE", ""):
            voice_id = anchor.get("heygen_voice_id")
            return avatar_id, anchor["name"], voice_id
    return None, None, None


def _clean_script_for_video(script_text):
    """
    Clean the hourly summary script for HeyGen TTS.

    Removes [ANCHOR_A]/[ANCHOR_B] tags, [CHYRON:...], [B-ROLL:...],
    markdown formatting, and normalizes whitespace.
    """
    if not script_text:
        return ""

    cleaned = script_text
    # Remove anchor tags
    cleaned = re.sub(r'\[ANCHOR_[AB]\]\s*', '', cleaned)
    # Remove chyron/broll tags
    cleaned = re.sub(r'\[CHYRON:\s*[^\]]+\]', '', cleaned)
    cleaned = re.sub(r'\[B-ROLL:\s*[^\]]+\]', '', cleaned)
    # Remove markdown bold/italic
    cleaned = re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'\*([^*]+)\*', r'\1', cleaned)
    # Normalize whitespace
    cleaned = re.sub(r'\n\s*\n', '\n\n', cleaned)
    cleaned = re.sub(r'  +', ' ', cleaned)
    return cleaned.strip()


def _submit_video(api_key, avatar_id, script_text, dimension, voice_id):
    """
    Submit a video generation request to HeyGen v2 API.

    Returns the video_id or None on failure.
    """
    try:
        response = requests.post(
            "https://api.heygen.com/v2/video/generate",
            headers={
                "X-Api-Key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "video_inputs": [
                    {
                        "character": {
                            "type": "avatar",
                            "avatar_id": avatar_id,
                            "avatar_style": "normal",
                        },
                        "voice": {
                            "type": "text",
                            "voice_id": voice_id,
                            "input_text": script_text,
                        },
                    }
                ],
                "dimension": dimension,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        video_id = data.get("data", {}).get("video_id")
        if not video_id:
            print(f"  WARNING: HeyGen response missing video_id: {data}")
            return None

        return video_id

    except requests.exceptions.RequestException as e:
        print(f"  WARNING: HeyGen video submission failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                print(f"  HeyGen error detail: {e.response.json()}")
            except Exception:
                print(f"  HeyGen status code: {e.response.status_code}")
        return None


def _poll_video_status(api_key, video_id):
    """
    Poll HeyGen video status until completion.

    Returns the video download URL or None on failure/timeout.
    """
    for attempt in range(MAX_POLL_ATTEMPTS):
        try:
            response = requests.get(
                f"https://api.heygen.com/v1/video_status.get?video_id={video_id}",
                headers={"X-Api-Key": api_key},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json().get("data", {})
            status = data.get("status")

            if status == "completed":
                video_url = data.get("video_url")
                if video_url:
                    elapsed = (attempt + 1) * POLL_INTERVAL_SECONDS
                    print(f"  HeyGen video ready ({elapsed}s)")
                    return video_url
                else:
                    print("  WARNING: HeyGen completed but no video_url in response")
                    return None

            elif status == "failed":
                error = data.get("error", "Unknown error")
                print(f"  WARNING: HeyGen video generation failed: {error}")
                return None

            elif status in ("processing", "pending", "waiting"):
                if attempt % 4 == 0:  # Log every ~60 seconds
                    elapsed = (attempt + 1) * POLL_INTERVAL_SECONDS
                    print(f"  HeyGen: {status}... ({elapsed}s elapsed)")
                time.sleep(POLL_INTERVAL_SECONDS)

            else:
                print(f"  WARNING: Unknown HeyGen status '{status}', continuing to poll...")
                time.sleep(POLL_INTERVAL_SECONDS)

        except requests.exceptions.RequestException as e:
            print(f"  WARNING: HeyGen poll error (attempt {attempt + 1}): {e}")
            time.sleep(POLL_INTERVAL_SECONDS)

    elapsed = MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS
    print(f"  WARNING: HeyGen video timed out after {elapsed}s ({MAX_POLL_ATTEMPTS} attempts)")
    return None


def _download_video(url, output_path):
    """Download the video file from HeyGen's URL."""
    try:
        response = requests.get(url, timeout=120, stream=True)
        response.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return True
    except requests.exceptions.RequestException as e:
        print(f"  WARNING: Video download failed: {e}")
        return False
