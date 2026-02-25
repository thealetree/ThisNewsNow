"""
This News Now — 24/7 Alternate Reality News Site

Serves the news site from docs/ (same files deployed to GitHub Pages).
In local mode, adds SSE streaming, audio serving, and a generator toggle
so you can start/stop story generation from the browser.

Run standalone:  python -m dashboard.app
Or via main.py:  imported and started on a background thread
"""

import json
import os
import queue
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml
from flask import Flask, Response, jsonify, request, send_file, send_from_directory

# Serve static files from docs/
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
app = Flask(__name__, static_folder=DOCS_DIR, static_url_path="/static")

# Thread-safe queue for SSE events
event_queue = queue.Queue(maxsize=200)

# In-memory store of recent stories
recent_stories = []
stories_lock = threading.Lock()

# Ticker headlines
ticker_headlines = []
ticker_lock = threading.Lock()

# Generator state
generator_thread = None
generator_stop_event = threading.Event()

# Paths
CONFIG_PATH = os.environ.get("TNN_CONFIG", "config.yaml")


def _load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def _load_world_bible():
    config = _load_config()
    wb_path = config.get("world_bible_path", "world_bible.json")
    with open(wb_path, "r") as f:
        return json.load(f)


def _save_stories_json():
    """Write current stories to docs/stories.json for static deployment."""
    stories_path = os.path.join(DOCS_DIR, "stories.json")
    with stories_lock:
        # Don't include audio_path (local filesystem) in static JSON
        static_stories = []
        for s in recent_stories:
            story_copy = {
                "type": s["type"],
                "timestamp": s["timestamp"],
                "data": {k: v for k, v in s["data"].items() if k != "audio_path"},
            }
            # Add audio_file reference if we copied the audio
            audio_file = f"{s['data'].get('story_id', 'unknown')}.mp3"
            audio_dest = os.path.join(DOCS_DIR, "audio", audio_file)
            if os.path.exists(audio_dest):
                story_copy["data"]["audio_file"] = audio_file
            static_stories.append(story_copy)

        with open(stories_path, "w") as f:
            json.dump(static_stories, f, indent=2)


# ---------------------------------------------------------------------------
# Public API: called by the generation pipeline
# ---------------------------------------------------------------------------

def push_script(script_data, audio_path=None):
    """Push a generated story to the news site."""
    story = {
        "type": "story",
        "timestamp": datetime.now().isoformat(),
        "data": {
            **script_data,
            "audio_path": audio_path,
            "published": datetime.now().strftime("%B %d, %Y \u2014 %I:%M %p"),
        },
    }
    with stories_lock:
        recent_stories.insert(0, story)
        if len(recent_stories) > 100:
            recent_stories.pop()

    # Copy audio to docs/audio/ for static deployment
    if audio_path and os.path.exists(audio_path):
        audio_dir = os.path.join(DOCS_DIR, "audio")
        os.makedirs(audio_dir, exist_ok=True)
        dest = os.path.join(audio_dir, f"{script_data.get('story_id', 'unknown')}.mp3")
        shutil.copy2(audio_path, dest)

    # Update ticker
    chyrons = script_data.get("chyrons", [])
    if chyrons:
        with ticker_lock:
            for c in chyrons:
                if c not in ticker_headlines:
                    ticker_headlines.insert(0, c)
            while len(ticker_headlines) > 20:
                ticker_headlines.pop()

    # Save static stories.json
    _save_stories_json()

    # Push SSE event
    try:
        event_queue.put_nowait(story)
    except queue.Full:
        pass


def push_status(message, level="info"):
    """Push a status update."""
    event = {
        "type": "status",
        "timestamp": datetime.now().isoformat(),
        "data": {"message": message, "level": level},
    }
    try:
        event_queue.put_nowait(event)
    except queue.Full:
        pass


# ---------------------------------------------------------------------------
# Generator (runs in background thread, controlled by toggle)
# ---------------------------------------------------------------------------

def _run_generator():
    """
    Generate stories in a loop until stop event is set.

    - Text stories generate continuously (no TTS — cheap, fast)
    - Hourly audio summaries generate at the top of each hour
      with both anchors alternating segments
    """
    from agents.scraper import scrape_news_context
    from agents.writer import generate_script
    from agents.hourly_summary import generate_hourly_summary
    from agents.tts import generate_hourly_audio

    config = _load_config()
    world_bible = _load_world_bible()

    push_status("Generator started — text stories + hourly audio summaries")

    # Get news context
    try:
        news_context = scrape_news_context()
    except Exception as e:
        push_status(f"Scraper error: {e}", level="error")
        news_context = {
            "trending_topics": ["politics", "economy"],
            "register": "tense",
            "dominant_formats": ["anchor_read"],
        }

    # Track stories generated this hour for the summary
    hour_stories = []
    last_summary_hour = -1

    while not generator_stop_event.is_set():
        current_hour = datetime.now().hour

        # ── Hourly Summary Check ──
        # Trigger if we've crossed into a new hour and have stories to summarize
        if current_hour != last_summary_hour and len(hour_stories) > 0:
            try:
                push_status(f"Generating hourly summary ({len(hour_stories)} stories)...")

                summary_data = generate_hourly_summary(hour_stories, config, world_bible)

                if summary_data and not generator_stop_event.is_set():
                    push_status("Generating dual-anchor audio...")
                    audio_data = generate_hourly_audio(summary_data, config)

                    if audio_data:
                        push_hourly_summary(summary_data, audio_path=audio_data.get("audio_path"))
                        push_status(f"Hourly summary published ({audio_data.get('actual_duration_seconds', 0):.0f}s)")

                last_summary_hour = current_hour
                hour_stories = []  # Reset for the new hour

            except Exception as e:
                push_status(f"Hourly summary error: {e}", level="error")
                last_summary_hour = current_hour

        # ── Regular Text Story ──
        try:
            push_status("Generating story...")
            config = _load_config()

            script_data = generate_script(config, world_bible, news_context)

            if generator_stop_event.is_set():
                break

            # Text only — no TTS for individual stories
            push_script(script_data)
            push_status(f"Published: {script_data.get('chyrons', ['Story'])[0]}")

            # Track for hourly summary
            hour_stories.append(script_data)

        except Exception as e:
            push_status(f"Error: {e}", level="error")

        # Wait between stories (check stop event every second)
        for _ in range(45):  # 45 second gap between text stories
            if generator_stop_event.is_set():
                break
            time.sleep(1)

        # Refresh news context every 30 minutes
        if len(hour_stories) % 40 == 0:
            try:
                news_context = scrape_news_context()
            except Exception:
                pass

    push_status("Generator stopped")


def push_hourly_summary(summary_data, audio_path=None):
    """Push an hourly audio summary to the news site."""
    story = {
        "type": "hourly_summary",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "story_id": summary_data["story_id"],
            "hour_label": summary_data["hour_label"],
            "anchor_a": summary_data["anchor_a"],
            "anchor_b": summary_data["anchor_b"],
            "headlines": summary_data["headlines"],
            "full_script": summary_data["full_script"],
            "story_count": summary_data["story_count"],
            "audio_path": audio_path,
            "published": datetime.now().strftime("%B %d, %Y \u2014 %I:%M %p"),
        },
    }

    with stories_lock:
        recent_stories.insert(0, story)
        if len(recent_stories) > 100:
            recent_stories.pop()

    # Copy audio to docs/audio/
    if audio_path and os.path.exists(audio_path):
        audio_dir = os.path.join(DOCS_DIR, "audio")
        os.makedirs(audio_dir, exist_ok=True)
        dest = os.path.join(audio_dir, f"{summary_data['story_id']}.mp3")
        shutil.copy2(audio_path, dest)

    _save_stories_json()

    try:
        event_queue.put_nowait(story)
    except queue.Full:
        pass


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the news site from docs/index.html."""
    return send_from_directory(DOCS_DIR, "index.html")


@app.route("/stories.json")
def static_stories():
    """Serve stories.json (for static mode compatibility)."""
    return send_from_directory(DOCS_DIR, "stories.json")


@app.route("/audio/<path:filename>")
def static_audio(filename):
    """Serve audio files from docs/audio/."""
    return send_from_directory(os.path.join(DOCS_DIR, "audio"), filename)


@app.route("/api/status")
def api_status():
    """Return server status — also used by frontend to detect local mode."""
    return jsonify({
        "mode": "local",
        "generator_running": generator_thread is not None and generator_thread.is_alive(),
        "story_count": len(recent_stories),
    })


@app.route("/api/stories")
def api_stories():
    with stories_lock:
        return jsonify(recent_stories[:30])


@app.route("/api/ticker")
def api_ticker():
    with ticker_lock:
        wb_headlines = []
        try:
            wb = _load_world_bible()
            for s in wb.get("ongoing_stories", []):
                wb_headlines.append(s.get("headline", ""))
        except Exception:
            pass
        combined = list(ticker_headlines) + wb_headlines
        seen = set()
        unique = []
        for h in combined:
            if h and h not in seen:
                seen.add(h)
                unique.append(h)
        return jsonify(unique[:15])


@app.route("/api/audio/<story_id>")
def api_audio(story_id):
    with stories_lock:
        for story in recent_stories:
            if story["data"].get("story_id") == story_id:
                audio_path = story["data"].get("audio_path")
                if audio_path and os.path.exists(audio_path):
                    return send_file(audio_path, mimetype="audio/mpeg")
    return "", 404


@app.route("/api/stream")
def api_stream():
    def generate():
        with stories_lock:
            for story in recent_stories[:10]:
                yield f"data: {json.dumps(story)}\n\n"
        while True:
            try:
                event = event_queue.get(timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                yield f": keepalive\n\n"

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/generator/start", methods=["POST"])
def api_generator_start():
    """Start the story generator."""
    global generator_thread
    if generator_thread and generator_thread.is_alive():
        return jsonify({"ok": True, "message": "Already running"})

    generator_stop_event.clear()
    generator_thread = threading.Thread(target=_run_generator, daemon=True)
    generator_thread.start()
    return jsonify({"ok": True, "message": "Generator started"})


@app.route("/api/generator/stop", methods=["POST"])
def api_generator_stop():
    """Stop the story generator."""
    generator_stop_event.set()
    return jsonify({"ok": True, "message": "Generator stopping"})


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def start_dashboard(host="0.0.0.0", port=8080, debug=False):
    app.run(host=host, port=port, debug=debug, use_reloader=False)


def start_dashboard_thread(host="0.0.0.0", port=8080):
    t = threading.Thread(
        target=start_dashboard,
        kwargs={"host": host, "port": port},
        daemon=True,
    )
    t.start()
    return t


if __name__ == "__main__":
    start_dashboard(debug=True)
