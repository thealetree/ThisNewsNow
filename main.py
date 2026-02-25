#!/usr/bin/env python3
"""
This News Now — Automated Alternate Reality News Channel
Main orchestrator: generates, uploads, or streams fictional news clips.

Usage:
    python main.py --mode pilot --count 5    # Phase A: generate N clips locally
    python main.py --mode upload --count 3   # Phase B: generate N clips + upload to YouTube
    python main.py --mode stream             # Phase C: continuous 24/7 livestream
    python main.py --mode dashboard          # Launch dashboard only
"""

import argparse
import random
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


def run_pilot(config, world_bible, count, dashboard=True):
    """Phase A: Generate N text stories + an hourly audio summary."""
    from agents.scraper import scrape_news_context
    from agents.writer import generate_script
    from agents.hourly_summary import generate_hourly_summary
    from agents.tts import generate_hourly_audio
    from agents.nonsense import inject_heavy_nonsense
    from dashboard.app import push_script, push_hourly_summary, push_status, start_dashboard_thread

    # Start dashboard in background
    if dashboard:
        start_dashboard_thread(port=8080)
        print(f"  Dashboard: http://localhost:8080")

    print(f"\n{'='*50}")
    print(f"  THIS NEWS NOW — Pilot Mode")
    print(f"  Generating {count} text stories + hourly audio summary")
    print(f"{'='*50}\n")

    push_status(f"Pilot run started — {count} stories + audio summary")

    # Step 1: Get current news context
    print("[1/3] Scraping real news context...")
    push_status("Scraping real news context...")
    news_context = scrape_news_context()
    push_status(f"Context ready: register={news_context.get('register')}, topics={news_context.get('trending_topics')}")

    # Log blueprint and style library status
    bp_count = len(news_context.get("story_blueprints", []))
    if bp_count:
        print(f"  {bp_count} story blueprints ready for writer")
    try:
        from agents.style_memory import load_style_library
        lib = load_style_library()
        scrapes = lib.get("total_scrapes", 0)
        templates = len(lib.get("headline_templates", []))
        if scrapes > 0:
            print(f"  Style library: {scrapes} scrapes, {templates} headline templates")
    except Exception:
        pass

    all_stories = []
    topics_covered = []  # Track topics for diversity enforcement

    # Pick which story slot gets heavy nonsense (1 per batch)
    # Never slot 0 — that's the top/featured story shown first on the site
    nonsense_slot = random.randint(1, count - 1) if count > 1 else 0

    for i in range(count):
        print(f"\n--- Story {i+1}/{count} ---")
        push_status(f"Writing story {i+1}/{count}...")

        # Step 2: Generate text-only story (no TTS)
        print("[2/3] Writing script...")
        script_data = generate_script(
            config=config,
            world_bible=world_bible,
            news_context=news_context,
            topics_covered=topics_covered if topics_covered else None,
        )

        # Apply heavy nonsense to the designated slot
        if i == nonsense_slot:
            script_data["script"], sample = inject_heavy_nonsense(
                script_data["script"], config, target_ratio=0.80
            )
            script_data["nonsense_heavy"] = True
            print(f"  ★ NONSENSE STORY — 80% Markov chain applied ('{sample}')")

        push_script(script_data)  # Text only — no audio
        all_stories.append(script_data)

        # Track topic + chyron for diversity in next iteration
        topic_tag = script_data.get("topic", "general")
        chyron = script_data.get("chyrons", [""])[0]
        topics_covered.append(f"{topic_tag}: {chyron}" if chyron else topic_tag)

        print(f"  ✓ Published: {script_data.get('chyrons', ['Story'])[0]}")
        push_status(f"Published: {script_data.get('chyrons', ['Story'])[0]}")

    # Step 3: Generate hourly audio summary from all stories
    if all_stories:
        print(f"\n--- Hourly Audio Summary ---")
        print("[3/3] Generating dual-anchor audio summary...")
        push_status(f"Generating hourly summary ({len(all_stories)} stories)...")

        summary_data = generate_hourly_summary(all_stories, config, world_bible)

        if summary_data:
            push_status("Generating dual-anchor TTS audio...")
            audio_data = generate_hourly_audio(summary_data, config)

            if audio_data:
                push_hourly_summary(summary_data, audio_path=audio_data.get("audio_path"))
                print(f"  ✓ Hourly summary: {audio_data.get('actual_duration_seconds', 0):.0f}s, {audio_data.get('segment_count', 0)} segments")
                push_status(f"Hourly summary published ({audio_data.get('actual_duration_seconds', 0):.0f}s)")

    push_status(f"Pilot complete — {count} stories + audio summary")

    print(f"\n{'='*50}")
    print(f"  Done. {count} text stories + hourly audio summary generated.")
    if dashboard:
        print(f"  Dashboard: http://localhost:8080")
        print(f"  Press Ctrl+C to stop.")
        print(f"{'='*50}\n")
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Shutting down.")
    else:
        print(f"{'='*50}\n")


def run_dashboard(config):
    """Run dashboard server standalone."""
    from dashboard.app import start_dashboard
    print(f"\n  THIS NEWS NOW — Dashboard")
    print(f"  http://localhost:8080\n")
    start_dashboard(port=8080, debug=True)


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
        choices=["pilot", "upload", "stream", "dashboard"],
        required=True,
        help="Operating mode: pilot (local clips), upload (YouTube), stream (24/7 live), dashboard (web UI only)",
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
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Disable dashboard server during pilot/upload runs",
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
        run_pilot(config, world_bible, count, dashboard=not args.no_dashboard)
    elif args.mode == "upload":
        run_upload(config, world_bible, count)
    elif args.mode == "stream":
        run_stream(config, world_bible)
    elif args.mode == "dashboard":
        run_dashboard(config)


if __name__ == "__main__":
    main()
