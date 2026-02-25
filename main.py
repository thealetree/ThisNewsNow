#!/usr/bin/env python3
"""
This News Now — Automated Alternate Reality News Channel
Main orchestrator: generates, uploads, or streams fictional news clips.

Usage:
    python main.py --mode pilot --count 5    # Phase A: generate N clips locally
    python main.py --mode upload --count 3   # Phase B: generate N clips + upload to YouTube
    python main.py --mode stream             # Phase C: continuous 24/7 livestream
"""

import argparse
import sys
import yaml
import json
import os
from pathlib import Path


def load_config(config_path="config.yaml"):
    """Load channel configuration from YAML."""
    if not os.path.exists(config_path):
        print(f"ERROR: {config_path} not found.")
        print("Copy config.example.yaml to config.yaml and fill in your API keys.")
        sys.exit(1)
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def load_world_bible(config):
    """Load the world bible (fictional canon)."""
    path = config.get("world_bible_path", "world_bible.json")
    if not os.path.exists(path):
        print(f"ERROR: World bible not found at {path}")
        sys.exit(1)
    with open(path, "r") as f:
        return json.load(f)


def run_pilot(config, world_bible, count):
    """Phase A: Generate N clips and save to output/ for review."""
    from agents.scraper import scrape_news_context
    from agents.writer import generate_script
    from agents.tts import generate_audio
    from video.assembler import assemble_clip

    output_dir = Path(config["pilot"]["output_dir"])
    output_dir.mkdir(exist_ok=True)

    print(f"\n{'='*50}")
    print(f"  THIS NEWS NOW — Pilot Mode")
    print(f"  Generating {count} clip(s)...")
    print(f"{'='*50}\n")

    # Step 1: Get current news context (shapes our fictional stories)
    print("[1/4] Scraping real news context...")
    news_context = scrape_news_context()

    for i in range(count):
        print(f"\n--- Clip {i+1}/{count} ---")

        # Step 2: Generate anchor script
        print("[2/4] Writing script...")
        script_data = generate_script(
            config=config,
            world_bible=world_bible,
            news_context=news_context,
        )

        # Step 3: Generate TTS audio
        print("[3/4] Generating TTS audio...")
        audio_data = generate_audio(
            script_data=script_data,
            config=config,
        )

        # Step 4: Assemble final video
        print("[4/4] Assembling video...")
        output_path = assemble_clip(
            script_data=script_data,
            audio_data=audio_data,
            config=config,
            output_dir=output_dir,
        )

        print(f"  ✓ Saved: {output_path}")

    print(f"\n{'='*50}")
    print(f"  Done. {count} clip(s) saved to {output_dir}/")
    print(f"  Review them and iterate on prompts/assets.")
    print(f"{'='*50}\n")


def run_upload(config, world_bible, count):
    """Phase B: Generate N clips and upload to YouTube."""
    print("Phase B (upload) not yet implemented. Build Phase A first.")
    sys.exit(0)


def run_stream(config, world_bible):
    """Phase C: Continuous generation + RTMP stream."""
    print("Phase C (stream) not yet implemented. Build Phase A and B first.")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="This News Now — Automated News Channel Generator"
    )
    parser.add_argument(
        "--mode",
        choices=["pilot", "upload", "stream"],
        required=True,
        help="Operating mode: pilot (local clips), upload (YouTube), stream (24/7 live)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Number of clips to generate (pilot/upload modes only)",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )

    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)
    world_bible = load_world_bible(config)

    # Resolve clip count
    count = args.count
    if count is None:
        count = config.get("pilot", {}).get("default_count", 3)

    if args.mode == "pilot":
        run_pilot(config, world_bible, count)
    elif args.mode == "upload":
        run_upload(config, world_bible, count)
    elif args.mode == "stream":
        run_stream(config, world_bible)


if __name__ == "__main__":
    main()
