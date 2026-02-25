"""
Image Generation Agent — Generates article header images via OpenAI GPT Image 1.

Creates photorealistic news images for large and medium story cards
using story context (headline, topic, B-roll descriptions) as prompts.
"""

import base64
import os
import re
import requests
from pathlib import Path


def generate_story_image(script_data, config):
    """
    Generate a header image for a story card.

    Args:
        script_data: story dict with chyrons, broll_descriptions, topic, story_id
        config: channel config

    Returns a dict with:
        - image_path: path to the saved .jpg file
        - story_id: story ID
    Or None if generation fails.
    """
    api_key = config.get("apis", {}).get("openai_key")
    if not api_key:
        print("  WARNING: No openai_key configured. Skipping image generation.")
        return None

    image_config = config.get("images", {})
    model = image_config.get("model", "gpt-image-1")
    quality = image_config.get("quality", "medium")
    size = image_config.get("size", "1024x1024")

    # Build the image prompt from story data
    prompt = _build_image_prompt(script_data, config)
    story_id = script_data.get("story_id", "unknown")

    try:
        response = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": size,
                "quality": quality,
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()

        image_data = data["data"][0]

        # Save the image
        output_dir = Path("docs") / "images"
        output_dir.mkdir(exist_ok=True)
        image_path = output_dir / f"{story_id}.jpg"

        if "b64_json" in image_data:
            img_bytes = base64.b64decode(image_data["b64_json"])
            with open(image_path, "wb") as f:
                f.write(img_bytes)
        elif "url" in image_data:
            img_resp = requests.get(image_data["url"], timeout=60)
            img_resp.raise_for_status()
            with open(image_path, "wb") as f:
                f.write(img_resp.content)
        else:
            print(f"  WARNING: No image data in response for {story_id}")
            return None

        print(f"  Image generated: {image_path.name}")
        return {
            "image_path": str(image_path),
            "story_id": story_id,
        }

    except requests.exceptions.RequestException as e:
        print(f"  WARNING: Image generation failed for {story_id}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                print(f"  OpenAI error detail: {e.response.json()}")
            except Exception:
                pass
        return None
    except (KeyError, IndexError) as e:
        print(f"  WARNING: Unexpected image API response for {story_id}: {e}")
        return None


def _build_image_prompt(script_data, config):
    """
    Build an image generation prompt from story data.

    Combines B-roll descriptions, headline context, and topic
    to produce a photorealistic news image prompt.
    """
    # Primary content: B-roll descriptions are the best image source
    broll = script_data.get("broll_descriptions", [])
    chyrons = script_data.get("chyrons", [])
    topic = script_data.get("topic", "general")

    # Clean script for context (strip tags)
    script = script_data.get("script", "")
    clean_script = re.sub(r'\[[A-Z_-]+:\s*[^\]]+\]', '', script).strip()

    # Build prompt parts
    parts = []

    # Scene description from B-roll
    if broll:
        parts.append(f"News photograph: {broll[0]}")
    elif chyrons:
        parts.append(f"News photograph related to: {chyrons[0]}")
    else:
        parts.append(f"News photograph about {topic}")

    # Add brief context from the script
    if clean_script:
        first_sentence = clean_script.split('.')[0].strip()
        if len(first_sentence) > 20:
            parts.append(f"Context: {first_sentence[:150]}")

    # Style guidance
    parts.append(
        "Photorealistic, editorial news photography style. "
        "Wide or medium shot, natural lighting, no text overlays, no watermarks, no captions. "
        "Cinematic but documentary feel. Slightly desaturated, gritty realism."
    )

    # Safety: ensure fictional / no recognizable faces
    parts.append(
        "All people shown must be generic and anonymous — no recognizable public figures. "
        "Faces should be turned away, in shadow, or at a distance."
    )

    return " ".join(parts)
