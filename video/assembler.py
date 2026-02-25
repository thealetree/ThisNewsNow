"""
Video Assembler — Composites TTS audio + graphics into final .mp4 clips.

Pure ffmpeg pipeline. No GPU required. Runs on Raspberry Pi.

Assembly pipeline per 30-second clip:
  [bumper_intro ~2s] + [anchor_bg loop ~25s] + [bumper_outro ~3s]
  + TTS audio under anchor section
  + Chyron overlays (Pillow-generated PNGs)
  + Channel logo watermark (top-right)
  + Scrolling news ticker (bottom)
"""

import subprocess
import os
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


# Video dimensions
WIDTH = 1280
HEIGHT = 720


def assemble_clip(script_data, audio_data, config, output_dir):
    """
    Assemble a complete news clip from script + audio.

    Returns the path to the output .mp4 file.
    """
    story_id = script_data["story_id"]
    audio_path = audio_data["audio_path"]
    audio_duration = audio_data["actual_duration_seconds"]
    chyrons = script_data.get("chyrons", [])
    branding = config.get("branding", {})

    output_path = Path(output_dir) / f"tnn_{story_id}.mp4"

    # Generate overlay images
    assets_dir = Path("assets")
    temp_dir = Path(output_dir) / "temp"
    temp_dir.mkdir(exist_ok=True)

    # Generate chyron overlay
    chyron_path = None
    if chyrons:
        chyron_path = temp_dir / f"chyron_{story_id}.png"
        _generate_chyron(chyrons[0], branding, str(chyron_path))

    # Generate logo/watermark
    logo_path = temp_dir / f"logo_{story_id}.png"
    _generate_logo(config["channel"]["name"], branding, str(logo_path))

    # Generate ticker bar
    ticker_path = temp_dir / f"ticker_{story_id}.png"
    ticker_text = " • ".join(
        [s.get("headline", "") for s in _get_ticker_stories(config)]
        + (chyrons if chyrons else ["This News Now"])
    )
    _generate_ticker_bar(ticker_text, branding, str(ticker_path))

    # Check if we have anchor background video, otherwise generate a solid bg
    anchor_bg = assets_dir / "anchor_bg.mp4"
    use_generated_bg = not anchor_bg.exists()

    # Build the ffmpeg command
    cmd = _build_ffmpeg_command(
        audio_path=audio_path,
        audio_duration=audio_duration,
        chyron_path=str(chyron_path) if chyron_path else None,
        logo_path=str(logo_path),
        ticker_path=str(ticker_path),
        output_path=str(output_path),
        use_generated_bg=use_generated_bg,
        anchor_bg_path=str(anchor_bg),
        branding=branding,
    )

    # Run ffmpeg
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  ERROR: ffmpeg failed:\n{result.stderr[-500:]}")
        raise RuntimeError(f"ffmpeg assembly failed for {story_id}")

    # Clean up temp files
    for f in temp_dir.glob(f"*_{story_id}.*"):
        f.unlink()
    try:
        temp_dir.rmdir()
    except OSError:
        pass

    return str(output_path)


def _build_ffmpeg_command(
    audio_path,
    audio_duration,
    chyron_path,
    logo_path,
    ticker_path,
    output_path,
    use_generated_bg,
    anchor_bg_path,
    branding,
):
    """Build the ffmpeg command for clip assembly."""
    total_duration = audio_duration + 2  # small padding
    bg_color = branding.get("primary_dark", "#2B2B2B").lstrip("#")

    inputs = []
    filter_parts = []

    if use_generated_bg:
        # Generate a solid color background
        inputs.extend([
            "-f", "lavfi",
            "-i", f"color=c=0x{bg_color}:s={WIDTH}x{HEIGHT}:r=30:d={total_duration}",
        ])
    else:
        # Use anchor background video (loop it)
        inputs.extend([
            "-stream_loop", "-1",
            "-i", anchor_bg_path,
        ])

    # Audio input
    inputs.extend(["-i", audio_path])

    # Overlay inputs
    overlay_idx = 2  # 0=video, 1=audio
    overlays = []

    if logo_path and os.path.exists(logo_path):
        inputs.extend(["-i", logo_path])
        overlays.append(("logo", overlay_idx))
        overlay_idx += 1

    if chyron_path and os.path.exists(chyron_path):
        inputs.extend(["-i", chyron_path])
        overlays.append(("chyron", overlay_idx))
        overlay_idx += 1

    if ticker_path and os.path.exists(ticker_path):
        inputs.extend(["-i", ticker_path])
        overlays.append(("ticker", overlay_idx))
        overlay_idx += 1

    # Build filter complex
    current_video = "0:v"

    for name, idx in overlays:
        out_label = f"v_{name}"
        if name == "logo":
            # Top-right corner, always on
            filter_parts.append(
                f"[{current_video}][{idx}:v]overlay=W-w-20:20[{out_label}]"
            )
        elif name == "chyron":
            # Lower-third, fade in at 3s, fade out at duration-3s
            fade_in = 3
            fade_out = max(audio_duration - 3, fade_in + 5)
            filter_parts.append(
                f"[{current_video}][{idx}:v]overlay=0:H-h-60:"
                f"enable='between(t,{fade_in},{fade_out})'[{out_label}]"
            )
        elif name == "ticker":
            # Bottom of screen, always on
            filter_parts.append(
                f"[{current_video}][{idx}:v]overlay=0:H-h[{out_label}]"
            )
        current_video = out_label

    cmd = ["ffmpeg", "-y"]
    cmd.extend(inputs)

    if filter_parts:
        filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", f"[{current_video}]", "-map", "1:a"])
    else:
        cmd.extend(["-map", "0:v", "-map", "1:a"])

    cmd.extend([
        "-t", str(total_duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        output_path,
    ])

    return cmd


def _generate_chyron(text, branding, output_path):
    """Generate a lower-third chyron graphic using Pillow."""
    bar_color = branding.get("accent_blue", "#1A3A6B")
    accent_color = branding.get("accent_red", "#C41E2A")
    text_color = branding.get("text_white", "#FFFFFF")

    # Create transparent image at video resolution
    img = Image.new("RGBA", (WIDTH, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Main bar background
    draw.rectangle([0, 10, WIDTH, 90], fill=bar_color)

    # Red accent line on top
    draw.rectangle([0, 6, WIDTH, 10], fill=accent_color)

    # Text
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 32)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
        except (OSError, IOError):
            font = ImageFont.load_default()

    draw.text((30, 30), text.upper(), fill=text_color, font=font)

    img.save(output_path, "PNG")


def _generate_logo(channel_name, branding, output_path):
    """Generate a small channel logo/watermark."""
    accent_red = branding.get("accent_red", "#C41E2A")
    text_color = branding.get("text_white", "#FFFFFF")

    img = Image.new("RGBA", (200, 50), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Semi-transparent background
    draw.rectangle([0, 0, 200, 50], fill=(43, 43, 43, 180))
    # Red accent bar
    draw.rectangle([0, 0, 5, 50], fill=accent_red)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        except (OSError, IOError):
            font = ImageFont.load_default()

    draw.text((15, 14), channel_name.upper(), fill=text_color, font=font)

    img.save(output_path, "PNG")


def _generate_ticker_bar(text, branding, output_path):
    """Generate a static ticker bar for the bottom of the screen."""
    bg_color = branding.get("primary_dark", "#2B2B2B")
    accent_red = branding.get("accent_red", "#C41E2A")
    text_color = branding.get("text_light", "#E0E0E0")

    img = Image.new("RGBA", (WIDTH, 36), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dark background bar
    draw.rectangle([0, 0, WIDTH, 36], fill=bg_color)
    # Red top accent
    draw.rectangle([0, 0, WIDTH, 3], fill=accent_red)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        except (OSError, IOError):
            font = ImageFont.load_default()

    # Truncate text to fit
    draw.text((20, 8), text.upper()[:120], fill=text_color, font=font)

    img.save(output_path, "PNG")


def _get_ticker_stories(config):
    """Load ongoing story headlines from world bible for the ticker."""
    wb_path = config.get("world_bible_path", "world_bible.json")
    try:
        with open(wb_path, "r") as f:
            wb = json.load(f)
        return wb.get("ongoing_stories", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []
