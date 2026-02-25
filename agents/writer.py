"""
Writer Agent — Generates deadpan, believable anchor scripts for This News Now.

Uses Claude API to produce 25-second broadcast scripts complete with
chyron tags and B-roll descriptions. All content is fictional but
designed to be indistinguishable from real local/national news.
"""

import anthropic
import json
import random
import uuid


def generate_script(config, world_bible, news_context):
    """
    Generate a single anchor script using Claude.

    Returns a dict with:
        - script: full anchor script text
        - chyrons: list of chyron strings
        - broll_descriptions: list of B-roll shot descriptions
        - anchor: anchor name
        - estimated_seconds: ~25
        - topic: story topic category
        - story_id: unique ID
    """
    client = anthropic.Anthropic(api_key=config["apis"]["anthropic_key"])

    # Pick a random anchor
    anchor = random.choice(world_bible["anchors"])

    # Build world bible summary for context injection
    world_summary = _build_world_summary(world_bible)

    # Get operator dial settings
    dials = config.get("dials", {})
    tone = dials.get("tone", "concerned")
    topic_weights = dials.get("topic_weights", {})

    prompt = f"""You are a script writer for This News Now (TNN), a fictional but completely realistic-sounding television news channel.

WORLD BIBLE CONTEXT:
{world_summary}

CURRENT NEWS REGISTER: {news_context.get('register', 'tense')}
DOMINANT TOPICS TODAY: {', '.join(news_context.get('trending_topics', ['politics', 'economy']))}
OPERATOR TONE SETTING: {tone}
STORY TOPIC WEIGHT: {json.dumps(topic_weights)}

Write a 25-second anchor script (spoken aloud at broadcast pace this should land at ~25 seconds — leave room for intro/outro bumpers to reach 30 seconds total). Rules:
- Anchor name: {anchor['name']}. Gender: {anchor['gender']}.
- Completely deadpan. No humor, no irony, no winking.
- Story must be fictional but completely believable. Use real-sounding place names from the world bible or invent new ones that fit. Use real-sounding names for officials.
- You may continue an ongoing story from the world bible OR introduce a new story that fits the current news register.
- Include: [CHYRON: text] tags for lower-third graphics (1-2 chyrons per script)
- Include: [B-ROLL: description] tags for cutaway shot descriptions (1-2 per script)
- Story should feel like it belongs in today's real news cycle.
- End with a one-line toss to commercial or next segment.
- Do NOT reference real named politicians, real companies, or real specific events.
- Output ONLY the script. No notes, no explanations, no metadata."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    script_text = message.content[0].text.strip()

    # Parse chyrons and B-roll from the script
    chyrons = _extract_tags(script_text, "CHYRON")
    broll_descriptions = _extract_tags(script_text, "B-ROLL")

    # Determine topic from script content (simple heuristic)
    topic = _classify_topic(script_text, topic_weights)

    story_id = str(uuid.uuid4())[:8]

    script_data = {
        "script": script_text,
        "chyrons": chyrons,
        "broll_descriptions": broll_descriptions,
        "anchor": anchor["name"],
        "anchor_gender": anchor["gender"],
        "estimated_seconds": 25,
        "topic": topic,
        "story_id": story_id,
    }

    print(f"  Script generated: [{topic}] {chyrons[0] if chyrons else 'No chyron'}")
    return script_data


def _build_world_summary(world_bible):
    """Build a concise world bible summary for prompt injection."""
    lines = []

    nation = world_bible.get("nation", {})
    lines.append(f"Country: {nation.get('name', 'United States')}")
    lines.append(f"President: {nation.get('president', 'Unknown')}")
    lines.append(f"Vice President: {nation.get('vice_president', 'Unknown')}")

    lines.append("\nOngoing stories:")
    for story in world_bible.get("ongoing_stories", []):
        lines.append(f"  - {story['headline']} ({story['status']}): {story['summary']}")

    lines.append("\nFictional places available:")
    for place in world_bible.get("fictional_places", []):
        if isinstance(place, dict):
            lines.append(f"  - {place['name']}, {place['state']}")
        else:
            lines.append(f"  - {place}")

    lines.append("\nFictional organizations:")
    for org in world_bible.get("fictional_organizations", []):
        lines.append(f"  - {org}")

    return "\n".join(lines)


def _extract_tags(script, tag_name):
    """Extract [TAG: content] values from script text."""
    import re
    pattern = rf'\[{tag_name}:\s*(.+?)\]'
    return re.findall(pattern, script, re.IGNORECASE)


def _classify_topic(script_text, topic_weights):
    """Simple keyword-based topic classification of the generated script."""
    text = script_text.lower()
    scores = {}

    keyword_map = {
        "politics": ["senator", "governor", "president", "legislation", "vote", "bill", "committee", "caucus"],
        "infrastructure": ["bridge", "road", "port", "rail", "construction", "pipeline", "transit", "grid"],
        "science": ["study", "research", "university", "climate", "species", "lab", "data", "findings"],
        "crime": ["arrest", "police", "investigation", "suspect", "charges", "detective", "victim"],
        "international": ["embassy", "foreign", "treaty", "summit", "allies", "trade", "sanctions"],
    }

    for topic, keywords in keyword_map.items():
        scores[topic] = sum(1 for kw in keywords if kw in text)

    if max(scores.values()) == 0:
        return "general"
    return max(scores, key=scores.get)
