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
    """Phase A: Generate N text stories + images + hourly video/audio summary."""
    from agents.scraper import scrape_news_context
    from agents.writer import generate_script
    from agents.hourly_summary import generate_hourly_summary
    from agents.tts import generate_hourly_audio
    from agents.nonsense import inject_heavy_nonsense
    from agents.image_gen import generate_story_image
    from agents.video_gen import generate_video
    from dashboard.app import (
        push_script, push_hourly_summary, push_status,
        push_story_image, start_dashboard_thread,
    )
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Check if AI media features are enabled
    video_enabled = bool(config.get("video", {}).get("provider"))
    image_enabled = bool(config.get("images", {}).get("provider"))
    image_card_sizes = config.get("images", {}).get("generate_for", [])

    # Start dashboard in background
    if dashboard:
        start_dashboard_thread(port=8080)
        print(f"  Dashboard: http://localhost:8080")

    media_desc = []
    if image_enabled:
        media_desc.append("images")
    if video_enabled:
        media_desc.append("video summary")
    else:
        media_desc.append("audio summary")
    media_str = " + ".join(media_desc)

    print(f"\n{'='*50}")
    print(f"  THIS NEWS NOW — Pilot Mode")
    print(f"  Generating {count} stories + {media_str}")
    print(f"{'='*50}\n")

    push_status(f"Pilot run started — {count} stories + {media_str}")

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
    image_futures = {}

    # Pick which story slot gets heavy nonsense (1 per batch)
    # Never slot 0 — that's the top/featured story shown first on the site
    nonsense_slot = random.randint(1, count - 1) if count > 1 else 0

    # Thread pool for parallel image generation
    executor = ThreadPoolExecutor(max_workers=3) if image_enabled else None

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

        # Queue image generation for large/medium stories (first 4: 1 featured + 3 medium)
        if executor and i < 4:
            card_size = "large" if i == 0 else "medium"
            if card_size in image_card_sizes:
                future = executor.submit(generate_story_image, script_data, config)
                image_futures[future] = script_data["story_id"]
                print(f"  📷 Image queued ({card_size})")

        # Track topic + chyron for diversity in next iteration
        topic_tag = script_data.get("topic", "general")
        chyron = script_data.get("chyrons", [""])[0]
        topics_covered.append(f"{topic_tag}: {chyron}" if chyron else topic_tag)

        print(f"  ✓ Published: {script_data.get('chyrons', ['Story'])[0]}")
        push_status(f"Published: {script_data.get('chyrons', ['Story'])[0]}")

    # Collect completed images
    if image_futures:
        print(f"\n--- Collecting AI Images ({len(image_futures)} queued) ---")
        push_status(f"Waiting for {len(image_futures)} AI images...")
        for future in as_completed(image_futures, timeout=180):
            story_id = image_futures[future]
            try:
                img_result = future.result()
                if img_result:
                    push_story_image(story_id, img_result["image_path"])
                    print(f"  ✓ Image: {story_id}")
                else:
                    print(f"  ✗ Image failed: {story_id}")
            except Exception as e:
                print(f"  ✗ Image error for {story_id}: {e}")
        push_status("Images complete")

    if executor:
        executor.shutdown(wait=False)

    # Backfill images for the first 4 visible stories on the site
    # (covers stories from previous runs that never had images generated)
    if image_enabled:
        import json as _json
        stories_path = os.path.join("docs", "stories.json")
        if os.path.exists(stories_path):
            with open(stories_path) as _f:
                _all = _json.load(_f)
            visible_stories = [s for s in _all if s.get("type") == "story"][:4]
            backfill_count = 0
            for vs in visible_stories:
                d = vs.get("data", {})
                sid = d.get("story_id", "")
                img_path = os.path.join("docs", "images", f"{sid}.jpg")
                if sid and not d.get("image_file") and not os.path.exists(img_path):
                    print(f"  📷 Backfilling image for {sid}...")
                    try:
                        img_result = generate_story_image(d, config)
                        if img_result:
                            push_story_image(sid, img_result["image_path"])
                            print(f"  ✓ Backfill image: {sid}")
                            backfill_count += 1
                    except Exception as e:
                        print(f"  ✗ Backfill image error for {sid}: {e}")
            if backfill_count:
                print(f"  Backfilled {backfill_count} missing images")

    # Step 3: Generate hourly summary (video or audio)
    if all_stories:
        if video_enabled:
            print(f"\n--- Hourly Video Summary ---")
            print("[3/3] Generating solo-anchor video summary...")
            push_status(f"Generating video summary ({len(all_stories)} stories)...")

            summary_data = generate_hourly_summary(
                all_stories, config, world_bible, video_mode=True
            )

            if summary_data:
                push_status("Generating HeyGen anchor video...")
                video_result = generate_video(summary_data, config)

                if video_result:
                    push_hourly_summary(
                        summary_data,
                        video_path=video_result.get("video_path"),
                    )
                    print(f"  ✓ Video summary published")
                    push_status("Video summary published")
                else:
                    # Fallback to audio
                    print("  ✗ Video failed, falling back to audio...")
                    push_status("Video failed, generating audio fallback...")
                    summary_data = generate_hourly_summary(
                        all_stories, config, world_bible, video_mode=False
                    )
                    if summary_data:
                        audio_data = generate_hourly_audio(summary_data, config)
                        if audio_data:
                            push_hourly_summary(
                                summary_data,
                                audio_path=audio_data.get("audio_path"),
                            )
                            print(f"  ✓ Audio fallback: {audio_data.get('actual_duration_seconds', 0):.0f}s")
                            push_status("Audio fallback summary published")
        else:
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

    push_status(f"Pilot complete — {count} stories + {media_str}")

    print(f"\n{'='*50}")
    print(f"  Done. {count} stories + {media_str} generated.")
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
