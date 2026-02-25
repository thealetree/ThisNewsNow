"""
Hourly Summary Agent — Generates a top-of-the-hour recap with dual anchors.

Collects the hour's stories, generates a ~60-90 second anchor-to-anchor
summary script, then produces multi-voice TTS audio with both anchors
alternating segments.
"""

import anthropic
import json
import random
import re
import uuid
from datetime import datetime


def generate_hourly_summary(stories, config, world_bible):
    """
    Generate an hourly news summary from the past hour's stories.

    Args:
        stories: list of story dicts from the past hour
        config: channel config
        world_bible: world bible dict

    Returns a dict with:
        - segments: list of {anchor, text} dicts for TTS
        - full_script: the complete script text
        - headlines: list of headline strings covered
        - story_id: unique ID for this summary
        - hour_label: formatted hour string
    """
    if not stories:
        return None

    client = anthropic.Anthropic(api_key=config["apis"]["anthropic_key"])
    all_anchors = world_bible.get("anchors", [])
    anchors = [a for a in all_anchors if not a.get("paused", False)]
    if not anchors:
        anchors = all_anchors  # Fallback if all paused

    # Pick one male and one female anchor for the desk
    males = [a for a in anchors if a.get("gender") == "male"]
    females = [a for a in anchors if a.get("gender") == "female"]
    if males and females:
        anchor_a = random.choice(females)   # Female leads
        anchor_b = random.choice(males)
        # Randomly swap who leads (50/50)
        if random.random() < 0.5:
            anchor_a, anchor_b = anchor_b, anchor_a
    elif len(anchors) >= 2:
        desk = random.sample(anchors, 2)
        anchor_a = desk[0]
        anchor_b = desk[1]
    else:
        anchor_a = anchors[0] if len(anchors) > 0 else {"name": "Patricia Holt", "gender": "female"}
        anchor_b = anchors[1] if len(anchors) > 1 else {"name": "Marcus Webb", "gender": "male"}

    # Build story summaries for the prompt
    story_briefs = []
    for s in stories[:8]:  # Cap at 8 stories
        headline = s.get("chyrons", ["Developing Story"])[0] if s.get("chyrons") else "Developing Story"
        # Strip tags from script for summary
        script = s.get("script", "")
        clean = re.sub(r'\[[A-Z_-]+:\s*[^\]]+\]', '', script).strip()
        story_briefs.append(f"- {headline}: {clean[:200]}")

    stories_block = "\n".join(story_briefs)
    story_count = len(story_briefs)
    hour_label = datetime.now().strftime("%I %p").lstrip("0")

    # Determine how many words based on story count
    # 3-4 stories = ~150 words, 5+ = ~200 words
    target_words = 150 if story_count <= 4 else 200

    system_msg = """You are a broadcast script writer for a two-anchor news desk. You write precise, concise news copy. You format output exactly as instructed with anchor tags. No markdown formatting ever."""

    prompt = f"""Write a top-of-the-hour news summary for This News Now (TNN).

Two anchors share the desk:
- {anchor_a['name']} ({anchor_a['gender']}) — lead anchor, opens and closes
- {anchor_b['name']} ({anchor_b['gender']}) — co-anchor, picks up alternate stories

STORIES FROM THE PAST HOUR:
{stories_block}

REQUIREMENTS:
- Total spoken words: approximately {target_words} (roughly 60-90 seconds at broadcast pace)
- Cover the top {min(story_count, 5)} stories from above. Summarize, don't repeat verbatim.
- Anchors ALTERNATE. {anchor_a['name']} opens with a brief greeting and the first story, {anchor_b['name']} takes the next, and so on. {anchor_a['name']} closes with a brief sign-off.
- Each anchor gets 2-4 segments depending on story count.
- Transitions between anchors should be natural: "Marcus?", "Thanks Patricia, turning to...", "And Patricia, we're also watching...", etc.
- Completely deadpan. No humor. This is a real news recap.
- ALL acronyms must be fully capitalized (EPA, FBI, FAA, DHS, NATO, etc.). ALL country names and proper nouns must be correctly capitalized. This is broadcast copy.
- *** NO REAL NAMES *** — Every person named in the summary MUST be fictional. Every company MUST be fictional. Do NOT use any real politician names (no Marco Rubio, no senators, no cabinet members by name). Do NOT use any real company names (no Boeing, no Amazon, etc.). For the President or VP just say "the President" or "the administration." INVENT all names.

FORMAT — use these EXACT tags to mark who speaks. Each segment on its own line.

CRITICAL: The VERY FIRST LINE must begin EXACTLY like this (word for word):
[ANCHOR_A] Now on This News Now, I'm {anchor_a['name']} here with {anchor_b['name']}.

Then continue with the first story, followed by alternating segments:
[ANCHOR_B] Thanks {anchor_a['name'].split()[0]}. In other developments tonight...
[ANCHOR_A] And finally...

Do NOT change the opening line. It MUST start with "Now on This News Now, I'm..."

Output ONLY the tagged script. No notes, no explanations."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system_msg,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_script = message.content[0].text.strip()

    # Fix capitalization of acronyms and proper nouns
    from agents.writer import _fix_capitalization, _scrub_real_names
    raw_script = _fix_capitalization(raw_script)
    raw_script = _scrub_real_names(raw_script)

    # Parse into segments
    segments = _parse_segments(raw_script, anchor_a["name"], anchor_b["name"])

    # Apply heavy nonsense to one random segment (not the first/last)
    from agents.nonsense import inject_heavy_nonsense
    if len(segments) > 2:
        # Pick a middle segment (not the opening or closing)
        nonsense_candidates = list(range(1, len(segments) - 1))
        nonsense_idx = random.choice(nonsense_candidates)
        segments[nonsense_idx]["text"], sample = inject_heavy_nonsense(
            segments[nonsense_idx]["text"], config, target_ratio=0.80
        )
        print(f"  ★ Nonsense segment #{nonsense_idx + 1} — 80% Markov ('{sample}')")

    # Add sponsor segment if configured
    sponsor = config.get("sponsor", {})
    if sponsor.get("enabled", False):
        sponsor_name = sponsor.get("name", "")
        sponsor_text = sponsor.get("text", "")
        if sponsor_name and sponsor_text:
            sponsor_read = f"This hourly update is brought to you by {sponsor_name}. {sponsor_text}"
            segments.append({
                "anchor": anchor_a["name"],
                "text": sponsor_read,
            })
            raw_script += f"\n\n[ANCHOR_A] {sponsor_read}"

    # Build headlines list
    headlines = []
    for s in stories[:5]:
        if s.get("chyrons"):
            headlines.append(s["chyrons"][0])

    story_id = "hourly_" + str(uuid.uuid4())[:8]

    result = {
        "segments": segments,
        "full_script": raw_script,
        "headlines": headlines,
        "story_count": story_count,
        "story_id": story_id,
        "hour_label": hour_label,
        "anchor_a": anchor_a["name"],
        "anchor_b": anchor_b["name"],
    }

    print(f"  Hourly summary generated: {len(segments)} segments, {story_count} stories covered")
    return result


def _parse_segments(script, anchor_a_name, anchor_b_name):
    """Parse [ANCHOR_A]/[ANCHOR_B] tagged script into segments."""
    segments = []
    # Split on anchor tags
    parts = re.split(r'\[(ANCHOR_[AB])\]\s*', script)

    current_anchor = None
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part == "ANCHOR_A":
            current_anchor = anchor_a_name
        elif part == "ANCHOR_B":
            current_anchor = anchor_b_name
        elif current_anchor:
            # Clean up any markdown
            clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', part)
            clean = re.sub(r'\[CHYRON:\s*[^\]]+\]', '', clean)
            clean = re.sub(r'\[B-ROLL:\s*[^\]]+\]', '', clean)
            clean = clean.strip()
            if clean:
                segments.append({
                    "anchor": current_anchor,
                    "text": clean,
                })

    return segments
